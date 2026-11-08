"""Selection of qualified strategy versions for newly created watches."""
from hotwatch_contract import EngineError

DEFAULT_ID='escape_momentum'
DEFAULT_VERSION='1.0.0'
EARLY_EDITABLE=('news_max_age_minutes','watch_gain_pct','watch_volume','watch_no_news_volume','momentum_window_minutes','momentum_pct','min_relative_volume','min_acceleration','confirmation_count','minimum_signal_s','max_spread_pct','use_macd_confirmation','rsi_cap','heat_limit_pct','heat_high_pct')
LEGACY_EDITABLE=('momentum_pct','min_relative_volume','max_spread_pct')


def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS hw_strategy_preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id),mode TEXT NOT NULL,strategy_id TEXT,version TEXT,updated TEXT NOT NULL)")


def resolve(connect,uid,scope='entry'):
    """Existing watches carry their own snapshot; no live session is modified."""
    if scope=='exit':
        return {'strategy_id':DEFAULT_ID,'version':DEFAULT_VERSION,'reason':'Beholdningen bruger den kvalificerede standardstrategi','mode':'auto'}
    with connect() as c:
        pref=c.execute('SELECT * FROM hw_strategy_preferences WHERE user_id=?',(uid,)).fetchone()
        if pref and pref['mode']=='manual':
            row=c.execute("SELECT * FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1",(uid,pref['strategy_id'],pref['version'])).fetchone()
            if row and row['validation_status']=='baseline_tested':
                return {'strategy_id':row['strategy_id'],'version':row['version'],'reason':'Valgt i dine strategiindstillinger','mode':'manual'}
            return {'strategy_id':DEFAULT_ID,'version':DEFAULT_VERSION,'reason':'Valgt strategi er ikke længere tilgængelig; standardstrategien anvendes','mode':'fallback'}
    return {'strategy_id':DEFAULT_ID,'version':DEFAULT_VERSION,'reason':'Automatisk standardvalg: Momentum','mode':'auto'}


def preferences(connect,uid):
    import hotwatch_engine
    with connect() as c:
        row=c.execute('SELECT mode,strategy_id,version FROM hw_strategy_preferences WHERE user_id=?',(uid,)).fetchone()
    result=hotwatch_engine.strategies(connect,uid)
    with connect() as c:
        import json
        for item in result['strategies']:
            raw=c.execute('SELECT payload FROM hw_strategies WHERE owner_id=? AND strategy_id=? AND version=?',(item['owner_id'],item['strategy_id'],item['version'])).fetchone()
            spec=json.loads(raw['payload']);item['description']=spec['description'];item['schema_version']=spec['schema_version'];item['editable']=list(EARLY_EDITABLE if spec['schema_version']==2 else LEGACY_EDITABLE);item['parameters']={k:spec['parameters'][k] for k in item['editable']};item['supports_example']=spec['schema_version']==1 and any(r.get('metric')=='catalyst_verified' for r in spec['entry_rules'].get('all',[]))
    return {'preference':dict(row) if row else {'mode':'auto','strategy_id':None,'version':None},'selection':resolve(connect,uid),**result}


def save(connect,uid,data,now):
    mode=data.get('mode')
    if mode not in ('auto','manual'):raise ValueError('Vælg automatisk eller manuel strategi.')
    sid=data.get('strategy_id');version=data.get('version')
    if mode=='manual':
        if not isinstance(sid,str) or not isinstance(version,str):raise ValueError('Vælg en tilgængelig strategi.')
        with connect() as c:
            row=c.execute("SELECT validation_status FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1",(uid,sid,version)).fetchone()
        if not row or row['validation_status']!='baseline_tested':raise ValueError('Strategien er endnu ikke kvalificeret til drift.')
    else:sid=version=None
    with connect() as c:
        c.execute('INSERT INTO hw_strategy_preferences VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode,strategy_id=excluded.strategy_id,version=excluded.version,updated=excluded.updated',(uid,mode,sid,version,now))
    return preferences(connect,uid)


def draft(connect,uid,data):
    """Create an immutable, private and unqualified research version."""
    import copy,json,secrets
    import hotwatch_engine
    if set(data)!={'source_id','source_version','description','parameters'}:raise ValueError('Ugyldige strategioplysninger.')
    sid=data['source_id'];version=data['source_version'];description=data['description'];changes=data['parameters']
    if not isinstance(sid,str) or not isinstance(version,str) or not isinstance(description,str) or not description.strip() or len(description)>400 or not isinstance(changes,dict):raise ValueError('Udfyld beskrivelsen og alle strategiindstillinger.')
    if any(not isinstance(v,str) or len(v)>30 for v in changes.values()):raise ValueError('Grænserne skal være tal.')
    with connect() as c:
        source=c.execute('SELECT * FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1',(uid,sid,version)).fetchone()
        if not source:raise ValueError('Strategien blev ikke fundet.')
        spec=json.loads(source['payload'])
        editable=EARLY_EDITABLE if spec['schema_version']==2 else LEGACY_EDITABLE
        if set(changes)!=set(editable):raise ValueError('Udfyld alle strategiindstillinger.')
        if source['owner_id']==0:
            spec['strategy_id']='custom-'+secrets.token_hex(12);spec['version']='0.1.0'
        else:
            versions=c.execute('SELECT version FROM hw_strategies WHERE owner_id=? AND strategy_id=?',(uid,sid)).fetchall()
            numbers=[tuple(map(int,r['version'].split('.'))) for r in versions]
            major,minor,patch=max(numbers);spec['version']=f'{major}.{minor}.{patch+1}'
    spec=copy.deepcopy(spec);spec['description']=description.strip()
    for key,value in changes.items():
        if type(spec['parameters'][key]) is bool:
            if value not in ('true','false'):raise ValueError('Vælg ja eller nej til MACD-bekræftelse.')
            value=value=='true'
        if type(spec['parameters'][key]) is int:
            try:
                if not value.isdecimal():raise ValueError()
                value=int(value)
            except ValueError:raise ValueError('Antal og minutter skal være hele tal.')
        spec['parameters'][key]=value
    from hotwatch_strategy import validate_strategy
    if validate_strategy(spec):raise ValueError('Kontrollér strategiindstillingerne, herunder grænser og tidsintervaller.')
    result=hotwatch_engine.upload_strategy(connect,uid,'Bruger',spec)
    return {'ok':True,'strategy_id':spec['strategy_id'],'version':spec['version'],'checksum':result['checksum'],'status':'draft'}


def simulate(connect,uid,data):
    """Evaluate one explicitly fictitious snapshot; no historical or risk claims."""
    import json
    from decimal import Decimal,InvalidOperation
    from hotwatch_strategy import matches
    if set(data)!={'strategy_id','version','metrics'} or not isinstance(data.get('metrics'),dict):raise ValueError('Ugyldigt testeksempel.')
    m=data['metrics'];fields={'return_3_pct','relative_volume','spread_pct','catalyst_age_minutes','catalyst_verified'}
    if set(m)!=fields or type(m['catalyst_verified']) is not bool:raise ValueError('Udfyld alle testtal.')
    for key in fields-{'catalyst_verified'}:
        if not isinstance(m[key],str) or len(m[key])>30:raise ValueError('Testtal skal være gyldige tal.')
        try:n=Decimal(m[key])
        except InvalidOperation:raise ValueError('Testtal skal være gyldige tal.')
        if not n.is_finite() or abs(n)>1000 or key!='return_3_pct' and n<0:raise ValueError('Kontrollér testtallene.')
    with connect() as c:
        row=c.execute('SELECT payload,checksum FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1',(uid,data['strategy_id'],data['version'])).fetchone()
    if not row:raise ValueError('Strategien blev ikke fundet.')
    spec=json.loads(row['payload'])
    if spec['strategy_id']=='escape_momentum' or not any(rule.get('metric')=='catalyst_verified' for rule in spec['entry_rules'].get('all',[])):raise ValueError('Eksemplet er kun til Early Catalyst og kopier af den.')
    verdict=matches(spec['entry_rules'],m,spec['parameters'])
    return {'matches':verdict,'checksum':row['checksum'],'notice':'Fiktivt eksempel. Ingen historisk test, risikokontrol, købssignal eller ordre.'}


def qualification(c,uid,proposal):
    """Qualification is server-owned, never supplied by the report."""
    row=c.execute('SELECT validation_status FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1',(uid,proposal['strategy_id'],proposal['version'])).fetchone()
    return 'QUALIFIED' if row and row['validation_status']=='baseline_tested' else 'UNQUALIFIED' if row else 'NOT_FOUND'


def handoff(connect,uid,candidate_id,mode=False):
    """Read receipt, last discovery attempt and actual pinned session separately."""
    import json
    with connect() as c:
        row=c.execute("SELECT r.report_id,r.payload FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.candidate_id=? AND r.report_type!='deep_analysis' ORDER BY l.generated DESC,r.id DESC LIMIT 1",(uid,int(mode),candidate_id)).fetchone()
        if not row:return {'candidate_id':candidate_id,'delivery':'NOT_FOUND','session':None}
        candidate=next(x for x in json.loads(row['payload'])['candidates'] if x['candidate_id']==candidate_id)
        proposed=candidate.get('strategy_proposal');state=qualification(c,uid,proposed) if proposed else 'NOT_SPECIFIED'
        attempt=c.execute('SELECT report_id,status,updated,watch_id FROM hw_discovery_attempts WHERE user_id=? AND is_test=? AND candidate_id=?',(uid,int(mode),candidate_id)).fetchone()
        if attempt and attempt['report_id']!=row['report_id']:attempt=None
        session=c.execute("SELECT watch_id,status,request,updated FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') AND COALESCE(json_extract(request,'$.watch_mode'),'both')!='exit' ORDER BY id DESC LIMIT 1",(uid,int(mode),candidate_id)).fetchone()
        pinned=None
        if session:
            req=json.loads(session['request']);pinned={'watch_id':session['watch_id'],'status':session['status'],'strategy_id':req['strategy_id'],'version':req['strategy_version'],'updated':session['updated']}
        same=bool(pinned and (not proposed or (pinned['strategy_id']==proposed['strategy_id'] and pinned['version']==proposed['version'])))
        if pinned:handoff_status='SESSION_PRESENT' if same else 'EXISTING_DIFFERENT_STRATEGY'
        elif state in ('NOT_FOUND','UNQUALIFIED'):handoff_status='STRATEGY_'+state
        elif mode:handoff_status='TEST_NOT_AUTO_STARTED'
        elif attempt:handoff_status=attempt['status']
        else:handoff_status='AWAITING_DISCOVERY'
        return {'candidate_id':candidate_id,'report_id':row['report_id'],'delivery':'STORED','proposed_strategy':proposed,'qualification':state,'handoff_status':handoff_status,'discovery_attempt':dict(attempt) if attempt else None,'session':pinned,'note':'Modtaget rapport er ikke bevis for en aktiv session, friske data eller en ordre.'}
