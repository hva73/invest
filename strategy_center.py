"""Selection of qualified strategy versions for newly created watches."""
from hotwatch_contract import EngineError

DEFAULT_ID='escape_momentum'
DEFAULT_VERSION='1.0.0'


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
            spec=json.loads(raw['payload']);item['description']=spec['description'];item['parameters']={k:spec['parameters'][k] for k in ('momentum_pct','min_relative_volume','max_spread_pct')};item['supports_example']=any(r.get('metric')=='catalyst_verified' for r in spec['entry_rules'].get('all',[]))
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
    if not isinstance(sid,str) or not isinstance(version,str) or not isinstance(description,str) or not description.strip() or len(description)>400 or not isinstance(changes,dict) or set(changes)!={'momentum_pct','min_relative_volume','max_spread_pct'}:raise ValueError('Udfyld beskrivelsen og de tre grænser.')
    if any(not isinstance(v,str) or len(v)>30 for v in changes.values()):raise ValueError('Grænserne skal være tal.')
    with connect() as c:
        source=c.execute('SELECT * FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1',(uid,sid,version)).fetchone()
        if not source:raise ValueError('Strategien blev ikke fundet.')
        spec=json.loads(source['payload'])
        if source['owner_id']==0:
            spec['strategy_id']='custom-'+secrets.token_hex(12);spec['version']='0.1.0'
        else:
            versions=c.execute('SELECT version FROM hw_strategies WHERE owner_id=? AND strategy_id=?',(uid,sid)).fetchall()
            numbers=[tuple(map(int,r['version'].split('.'))) for r in versions]
            major,minor,patch=max(numbers);spec['version']=f'{major}.{minor}.{patch+1}'
    spec=copy.deepcopy(spec);spec['description']=description.strip();spec['parameters'].update(changes)
    from hotwatch_strategy import validate_strategy
    if validate_strategy(spec):raise ValueError('Kontrollér at alle grænser er positive og højst 1000.')
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
