"""Selection of qualified strategy versions for newly created watches."""
from hotwatch_contract import EngineError

DEFAULT_ID='escape_momentum'
DEFAULT_VERSION='1.0.0'
EARLY_EDITABLE=('news_max_age_minutes','watch_gain_pct','watch_volume','watch_no_news_volume','momentum_window_minutes','momentum_pct','min_relative_volume','min_acceleration','confirmation_count','minimum_signal_s','max_spread_pct','use_macd_confirmation','rsi_cap','heat_limit_pct','heat_high_pct')
LEGACY_EDITABLE=('momentum_pct','min_relative_volume','max_spread_pct')


def deployment(row):
    """Allow only baseline or structurally constrained Early Catalyst pilots."""
    if not row:return 'NOT_FOUND'
    if row['validation_status']=='baseline_tested':return 'QUALIFIED'
    if row['validation_status']!='schema_validated' or 'payload' not in row.keys():return 'UNQUALIFIED'
    import json
    from hotwatch_strategy import EARLY_CATALYST_V1,validate_strategy
    from hotwatch_contract import checksum
    try:
        spec=json.loads(row['payload'])
        if checksum(spec)!=row['checksum'] or validate_strategy(spec):return 'UNQUALIFIED'
        if row['owner_id']==0:
            return 'PILOT' if spec==EARLY_CATALYST_V1 else 'UNQUALIFIED'
        if not spec['strategy_id'].startswith('custom-') or spec.get('schema_version')!=2:return 'UNQUALIFIED'
        if any(spec.get(key)!=EARLY_CATALYST_V1[key] for key in ('watch_rules','entry_rules','exit_rules')):return 'UNQUALIFIED'
        fixed=set(EARLY_CATALYST_V1['parameters'])-set(EARLY_EDITABLE)
        if any(spec['parameters'].get(key)!=EARLY_CATALYST_V1['parameters'][key] for key in fixed):return 'UNQUALIFIED'
        return 'PILOT'
    except (ValueError,TypeError,KeyError):return 'UNQUALIFIED'



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
            if deployment(row) in ('QUALIFIED','PILOT'):
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
            row=c.execute("SELECT * FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1",(uid,sid,version)).fetchone()
        if deployment(row) not in ('QUALIFIED','PILOT'):raise ValueError('Strategien kan endnu ikke vælges til overvågning.')
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
    row=c.execute('SELECT * FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1',(uid,proposal['strategy_id'],proposal['version'])).fetchone()
    return deployment(row)


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


def _reference(c,row,request,sample,reported,now):
    """Corroborate the reported close against local EODHD and exchange calendar."""
    import json
    from datetime import timedelta,datetime
    from decimal import Decimal
    from zoneinfo import ZoneInfo
    from report_validation import stamp
    try:
        quote=reported.get('reference_close') or {};price=quote['price'];observed=stamp(quote['observed_at']);available=stamp(quote['available_at']);at=stamp(sample['event_time'])
        if sample.get('source')!='eodhd' or sample.get('verification')!='verified' or price['currency']!=request['quote_currency'] or observed>available or available>now or observed>at:return None
        exchange=request['provider_symbol'].rsplit('.',1)[1].upper()
        calendar=c.execute('SELECT * FROM hw_exchange_calendar WHERE exchange=?',(exchange,)).fetchone()
        if not calendar or not 0<=(now-stamp(calendar['received'])).total_seconds()<=300:return None
        zone=ZoneInfo(calendar['timezone']);schedule=json.loads(calendar['calendar']);local=at.astimezone(zone);close=datetime.strptime(schedule['close'],'%H:%M:%S').time();reference_day=local.date()
        def open_day(day):return day.strftime('%a') in schedule['working_days'] and day.isoformat() not in schedule['excluded_dates']
        # Latest ordinary close strictly before this observation.
        if not open_day(reference_day) or local.time()<close:reference_day-=timedelta(days=1)
        for _ in range(10):
            if open_day(reference_day):break
            reference_day-=timedelta(days=1)
        else:return None
        closing=datetime.combine(reference_day,close,tzinfo=zone);observed_local=observed.astimezone(zone)
        if observed_local.date()!=reference_day or not 0<=(closing-observed_local).total_seconds()<=300:return None
        # For after-close news, the close must also precede publication.
        catalyst=reported.get('catalyst') or {}
        if catalyst and reported.get('news_session')=='after_close' and observed>stamp(catalyst['published_at']):return None
        provider_previous=sample.get('previous_close')
        if provider_previous is None:
            for old in c.execute("SELECT payload,received FROM hw_samples WHERE watch_row_id=? AND source='eodhd' AND event_epoch<=? ORDER BY event_epoch DESC LIMIT 120",(row['id'],at.timestamp())):
                prior=json.loads(old['payload'])
                if stamp(old['received'])>now or prior.get('verification')!='verified' or prior.get('asset_id')!=sample['asset_id'] or prior.get('currency')!=sample['currency'] or stamp(prior['event_time']).astimezone(zone).date()!=local.date():continue
                if prior.get('previous_close') and str(prior.get('feed_type','')).startswith('EODHD REST real-time endpoint'):provider_previous=prior['previous_close'];break
        expected=Decimal(str(price['amount']));provider=Decimal(str(provider_previous));current=Decimal(str(sample['price']))
        if not all(x.is_finite() and x>0 for x in (expected,provider,current)) or abs(expected-provider)/provider>Decimal('0.000001'):return None
        return format((current/expected-1)*100,'f')
    except (KeyError,ValueError,TypeError,ArithmeticError,AttributeError,IndexError):return None


def _news_attestation(doc,proposal,now,max_age_minutes=120):
    """Accept only a source-attributed ChatGPT check; not independent verification."""
    from report_validation import stamp
    try:
        check=proposal.get('news_check') or {};at=stamp(check['checked_at']);proposed=stamp(proposal['proposed_at'])
        if not 0<=(now-at).total_seconds()<=max_age_minutes*60 or at>proposed:return None
        sources={x['source_id']:x for x in doc.get('sources',[])}
        checked=check.get('source_ids') or []
        good={key for key in checked if key in sources and sources[key].get('verification')=='verified' and sources[key].get('verified_at') and stamp(sources[key]['verified_at'])<=at}
        if not good:return None
        if check['status']=='no_verified_news':return 'no_verified_news'
        news=proposal.get('catalyst') or {};published=stamp(news['published_at']);available=stamp(news['available_at'])
        if check['status']!='verified_news' or published>available or available>at:return None
        source_ids=set(news.get('source_ids') or [])&good
        if not any(sources[key].get('published_at') and stamp(sources[key]['published_at'])==published and stamp(sources[key]['verified_at'])>=published for key in source_ids):return None
        return 'verified_news'
    except (KeyError,ValueError,TypeError,AttributeError):return None


def _news_session(c,request,catalyst,now):
    """Derive market phase from the local provider calendar, never report text."""
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from report_validation import stamp
    try:
        exchange=request['provider_symbol'].rsplit('.',1)[1].upper();calendar=c.execute('SELECT * FROM hw_exchange_calendar WHERE exchange=?',(exchange,)).fetchone()
        if not calendar or not 0<=(now-stamp(calendar['received'])).total_seconds()<=300:return None
        zone=ZoneInfo(calendar['timezone']);schedule=json.loads(calendar['calendar']);local=stamp(catalyst['published_at']).astimezone(zone)
        opening=datetime.strptime(schedule['open'],'%H:%M:%S').time();closing=datetime.strptime(schedule['close'],'%H:%M:%S').time()
        if opening>=closing:return None
        if local.strftime('%a') not in schedule['working_days'] or local.date().isoformat() in schedule['excluded_dates']:return 'after_close'
        return 'before_open' if local.time()<opening else 'after_close' if local.time()>=closing else 'during_regular'
    except (KeyError,ValueError,TypeError,AttributeError,IndexError):return None


def _previous_session_earnings(c,request,sample,catalyst,now):
    import json
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from report_validation import stamp
    try:
        if str(catalyst.get('kind','')).strip().casefold() not in ('earnings','regnskab'):return False
        published=stamp(catalyst['published_at']);exchange=request['provider_symbol'].rsplit('.',1)[1].upper()
        calendar=c.execute('SELECT * FROM hw_exchange_calendar WHERE exchange=?',(exchange,)).fetchone()
        if not calendar or not 0<=(now-stamp(calendar['received'])).total_seconds()<=300:return None
        zone=ZoneInfo(calendar['timezone']);local=stamp(sample['event_time']).astimezone(zone);schedule=json.loads(calendar['calendar']);day=local.date()-timedelta(days=1)
        for _ in range(10):
            if day.strftime('%a') in schedule['working_days'] and day.isoformat() not in schedule['excluded_dates']:return published.astimezone(zone).date()==day
            day-=timedelta(days=1)
    except (KeyError,ValueError,TypeError,AttributeError,IndexError):return None
    return None


def _pre_news(c,row,request,sample,reported,now):
    """Compare the reported pre-news price to an earlier locally stored provider sample."""
    import json
    from decimal import Decimal
    from report_validation import stamp
    try:
        quote=reported['pre_news_price'];price=quote['price'];observed=stamp(quote['observed_at']);available=stamp(quote['available_at']);published=stamp(reported['published_at'])
        if price['currency']!=request['quote_currency'] or not 0<=(published-observed).total_seconds()<=120 or observed>available or available>now:return None
        candidates=c.execute("SELECT s.payload,s.received FROM hw_samples s JOIN hw_sessions w ON w.id=s.watch_row_id WHERE w.user_id=? AND w.is_test=? AND json_extract(w.request,'$.asset_id')=? AND s.source='eodhd' AND s.event_epoch BETWEEN ? AND ? ORDER BY s.event_epoch DESC LIMIT 100",(row['user_id'],row['is_test'],request['asset_id'],observed.timestamp()-1,observed.timestamp()+1)).fetchall()
        expected=Decimal(str(price['amount']));current=Decimal(str(sample['price']))
        if not expected.is_finite() or not current.is_finite() or expected<=0 or current<=0:return None
        for item in candidates:
            old=json.loads(item['payload']);value=Decimal(str(old.get('price')))
            if stamp(item['received'])<=now and old.get('verification')=='verified' and old.get('asset_id')==request['asset_id'] and old.get('currency')==price['currency'] and stamp(old['event_time'])<=published and value>0 and abs(value-expected)/expected<=Decimal('0.000001'):
                return format((current/expected-1)*100,'f')
    except (KeyError,ValueError,TypeError,ArithmeticError,AttributeError):pass
    return None


def early_inputs(c,row,request,sample,metrics,now):
    """Live-pilot evidence; report claims never become independently verified facts."""
    import json
    from decimal import Decimal
    from report_validation import stamp
    context=sample.get('context') or {};now_epoch=now.timestamp()
    fresh=lambda t,limit:bool(t and 0<=now_epoch-stamp(t).timestamp()<=limit)
    ordinary=None;tradable=None
    try:
        if context.get('status')=='verified' and fresh(context.get('as_of'),300):
            if context.get('tradability')=='available':tradable=True
            elif context.get('tradability')=='unavailable':tradable=False
            kind=context.get('instrument_type')
            if kind and fresh(context.get('instrument_type_at'),300):
                upper=kind.upper()
                if upper in ('CS','COMMON_STOCK','COMMON_SHARE'):ordinary=True
                elif upper in ('ETF','CRYPTO','BOND','FUND','PREFERRED_STOCK'):ordinary=False
    except (ValueError,TypeError,AttributeError):ordinary=tradable=None
    inputs={'ordinary_share':ordinary,'pluto_tradable':tradable,'catalyst_verified':None,'catalyst_age_minutes':None,'earnings_previous_session':None,'no_verified_news':None,'reference_gain_pct':None,'news_reaction_pct':None,'consolidating':None,'new_breakout':None,'new_setup':None}
    if metrics.get('sample_count',0)>json.loads(row['strategy'])['parameters']['breakout_window'] and type(metrics.get('breakout')) is bool:inputs['new_breakout']=metrics['breakout']
    reported=None
    if request.get('report_id') not in ('manual-pluto','automatic-holdings'):
        latest=c.execute("SELECT r.report_id,r.payload FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.candidate_id=? AND r.report_type!='deep_analysis' AND l.generated<=? AND julianday(r.received)<=julianday(?) ORDER BY l.generated DESC,r.id DESC LIMIT 1",(row['user_id'],row['is_test'],row['candidate_id'],now_epoch,now.isoformat())).fetchone()
        if latest:
            doc=json.loads(latest['payload']);candidate=next((x for x in doc.get('candidates',[]) if x.get('candidate_id')==row['candidate_id']),None);proposal=(candidate or {}).get('strategy_proposal') or {}
            if proposal.get('strategy_id')==request.get('strategy_id') and proposal.get('version')==request.get('strategy_version'):
                catalyst=proposal.get('catalyst') or {};reported={'report_id':latest['report_id'],'verification':'sender_reported','kind':catalyst.get('kind'),'published_at':catalyst.get('published_at'),'available_at':catalyst.get('available_at'),'catalyst':catalyst,'news_check':proposal.get('news_check'),'reference_close':proposal.get('reference_close'),'pre_news_price':proposal.get('pre_news_price'),'news_session':proposal.get('news_session')}
                detected_session=_news_session(c,request,catalyst,now) if catalyst else None
                reported['detected_news_session']=detected_session
                proof={**reported,'news_session':detected_session}
                inputs['reference_gain_pct']=_reference(c,row,request,sample,proof,now) if not catalyst or detected_session else None
                attested=_news_attestation(doc,proposal,now,json.loads(row['strategy'])['parameters']['news_max_age_minutes'])
                if attested=='verified_news':
                    inputs['catalyst_verified']=True
                    inputs['earnings_previous_session']=_previous_session_earnings(c,request,sample,catalyst,now)
                elif attested=='no_verified_news':inputs['no_verified_news']=True
                reported['attestation']=attested or 'unverified'
                if detected_session=='during_regular':inputs['news_reaction_pct']=_pre_news(c,row,request,sample,reported,now)
                elif detected_session=='after_close':inputs['news_reaction_pct']=inputs['reference_gain_pct']
                try:
                    if catalyst.get('available_at') and catalyst.get('published_at') and stamp(catalyst['available_at'])<=now and stamp(catalyst['published_at'])<=stamp(catalyst['available_at']):
                        inputs['catalyst_age_minutes']=str(Decimal(str((now-stamp(catalyst['published_at'])).total_seconds()))/Decimal(60))
                except (ValueError,TypeError):pass
    metrics.update(inputs)
    missing=[]
    for key,label in [('ordinary_share','Pluto har ikke bekræftet almindelig aktie'),('pluto_tradable','Pluto-handelsbarhed er ikke bekræftet'),('catalyst_verified','Nyhed er ikke uafhængigt verificeret'),('reference_gain_pct','Verificeret ordinær lukkekurs mangler'),('news_reaction_pct','Verificeret kurs før nyheden mangler'),('relative_volume','Sammenlignelig relativ volumen mangler'),('return_window_pct','Kursdata for tidsvinduet mangler'),('spread_pct','Frisk bid/ask mangler'),('rsi','RSI-grundlag mangler')]:
        if metrics.get(key) is None:missing.append(label)
    risk=request.get('risk') or {}
    for key,label in [('proposed_quantity','Handelsstørrelse til risikokontrol mangler'),('stop_price','Stopkurs til risikokontrol mangler')]:
        if risk.get(key) is None:missing.append(label)
    for key,label in [('fx_to_dkk','Bekræftet valutakurs til kroner mangler'),('fees_dkk','Bekræftede handelsomkostninger mangler'),('portfolio_equity_dkk','Bekræftet depotværdi i kroner mangler'),('exposure_dkk','Bekræftet eksponering i kroner mangler')]:
        if context.get(key) is None:missing.append(label)
    return {'mode':'live_pilot','watch_state':'BLOCKED' if ordinary is False or tradable is False else 'WAITING_FOR_EVIDENCE','missing':missing,'reported_evidence':reported,'note':'En eventuel nyhedskontrol er oplyst af rapportens afsender og er ikke uafhængigt verificeret af ESCAPE. Kurs, Pluto og risikokontrol kontrolleres særskilt.'}
