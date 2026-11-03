"""Append-only observation and delivery evidence. Never imports broker clients."""
import hashlib,json
from datetime import datetime,timezone
from decimal import Decimal,localcontext
from report_validation import issue,stamp,schema_errors,ReportValidationError
from report_v2 import OBSERVATION,DECISION

def canonical(data):return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def now():return datetime.now(timezone.utc).isoformat()
def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS hot_watch_observations(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),is_test INTEGER NOT NULL,observation_id TEXT NOT NULL,candidate_id TEXT NOT NULL,report_row_id INTEGER NOT NULL REFERENCES ingested_reports(id),observed REAL NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,received TEXT NOT NULL,UNIQUE(user_id,observation_id))')
    c.execute('CREATE INDEX IF NOT EXISTS hot_watch_timeline ON hot_watch_observations(user_id,is_test,candidate_id,observed,id)')
    existing=c.execute("SELECT 1 FROM sqlite_master WHERE name='candidate_decision_events'").fetchone()
    c.execute('CREATE TABLE IF NOT EXISTS candidate_decision_events(user_id INTEGER NOT NULL REFERENCES users(id),is_test INTEGER NOT NULL,candidate_id TEXT NOT NULL,decided REAL NOT NULL,payload TEXT NOT NULL,origin TEXT NOT NULL,PRIMARY KEY(user_id,is_test,candidate_id,decided))')
    if not existing:
        for row in c.execute('SELECT user_id,payload FROM ingested_reports ORDER BY generated_epoch,id').fetchall():
            d=json.loads(row['payload'])
            if d.get('schema_version')==2:index_report(c,row['user_id'],d)
    c.execute('CREATE TABLE IF NOT EXISTS report_delivery_evidence(report_row_id INTEGER NOT NULL REFERENCES ingested_reports(id),kind TEXT NOT NULL,observed TEXT NOT NULL,PRIMARY KEY(report_row_id,kind))')

def evidence(c,row_id,kind):
    c.execute('INSERT OR IGNORE INTO report_delivery_evidence VALUES(?,?,?)',(row_id,kind,now()))

def delivery(c,row_id):
    events={r['kind']:r['observed'] for r in c.execute('SELECT kind,observed FROM report_delivery_evidence WHERE report_row_id=?',(row_id,))}
    return {'status':'readback_verified' if 'readback_verified' in events else 'stored' if 'stored' in events else 'unknown','events':events,'note':'Tilbageslæsning betyder, at serveren har hentet og kontrolleret det uændrede indhold. Klientens modtagelse kan ikke bevises af serveren.'}

def readback(c,row):
    # Do not normalize old payloads. The digest was computed at insertion.
    digest=hashlib.sha256(row['payload'].encode()).hexdigest()
    if digest==row['digest']:evidence(c,row['id'],'readback_verified')

def index_decision(c,uid,mode,cid,d,origin):
    if not d:return
    payload=canonical(d)
    c.execute('INSERT OR IGNORE INTO candidate_decision_events(user_id,is_test,candidate_id,decided,payload,origin) VALUES(?,?,?,?,?,?)',(uid,int(mode),cid,stamp(d['decided_at']).timestamp(),payload,origin))

def index_report(c,uid,data):
    for candidate in data.get('candidates',[]):
        index_decision(c,uid,data['is_test'],candidate['candidate_id'],candidate.get('decision'),data['report_id'])

def prior_decision(c,uid,mode,cid,before=None):
    args=[uid,int(mode),cid];bound=''
    if before is not None:bound=' AND decided<=?';args.append(before)
    row=c.execute('SELECT decided,payload,origin FROM candidate_decision_events WHERE user_id=? AND is_test=? AND candidate_id=?'+bound+' ORDER BY decided DESC LIMIT 1',args).fetchone()
    return (row['decided'],json.loads(row['payload']),row['origin']) if row else None

def decision_errors(decision,path,at,previous=None):
    errors=[]
    if not isinstance(decision,dict):return errors
    def add(field,code,message):errors.append(issue(path+'.'+field,code,message))
    try:
        if stamp(decision.get('decided_at'))>stamp(at):add('decided_at','future_evidence','Decision cannot be later than its enclosing observation/report')
        if decision.get('data_as_of') and stamp(decision['data_as_of'])>stamp(decision['decided_at']):add('data_as_of','future_evidence','Data time cannot be later than decision')
        if decision.get('deadline') and stamp(decision['deadline'])<stamp(decision['decided_at']):add('deadline','invalid_deadline','Deadline cannot precede decision')
    except (ValueError,TypeError):pass
    buy=decision.get('buy_plan')
    if isinstance(buy,dict):
        if isinstance(buy.get('amount_dkk'),dict) and buy['amount_dkk'].get('currency')!='DKK':add('buy_plan.amount_dkk.currency','currency_mismatch','Expected DKK')
        try:
            if stamp(buy.get('expires_at'))<=stamp(decision.get('decided_at')):add('buy_plan.expires_at','invalid_deadline','Buy proposal must expire after decision')
        except (ValueError,TypeError):pass
    if previous:
        old=previous[1]
        if old.get('status')=='FRAVÆLG' and decision.get('status')!='FRAVÆLG' and not decision.get('reactivation_reason'):add('reactivation_reason','reactivation_evidence_required','Reactivation requires a documented new catalyst or material price/volume change')
        try:
            if stamp(old['decided_at'])==stamp(decision['decided_at']) and old!=decision:add('decided_at','decision_conflict','Same candidate and decision time already have different decision content')
        except (ValueError,TypeError,KeyError):pass
    return errors

def report_semantic(data,errors,warnings,c,uid):
    for i,candidate in enumerate(data.get('candidates',[]) if isinstance(data.get('candidates'),list) else []):
        if not isinstance(candidate,dict) or not isinstance(candidate.get('decision'),dict):continue
        d=candidate['decision'];previous=None
        if c is not None and uid is not None and type(data.get('is_test')) is bool and isinstance(candidate.get('candidate_id'),str):
            try:previous=prior_decision(c,uid,data['is_test'],candidate['candidate_id'],stamp(d.get('decided_at')).timestamp())
            except (ValueError,TypeError):pass
        errors.extend(decision_errors(d,f'candidates[{i}].decision',data.get('generated_at'),previous))
    for i,o in enumerate(data.get('orders',[]) if isinstance(data.get('orders'),list) else []):
        if not isinstance(o,dict):continue
        try:
            filled=Decimal(o['filled_quantity']) if isinstance(o.get('filled_quantity'),str) else None
            requested=Decimal(o['requested_quantity']) if isinstance(o.get('requested_quantity'),str) else None
            if filled is not None and requested is not None and filled>requested:errors.append(issue(f'orders[{i}].filled_quantity','invalid_quantity','Filled quantity cannot exceed requested quantity'))
            # Old reports remain accepted: inconsistent legacy status is a warning.
            if 'execution_source' in o and filled==0 and o.get('lifecycle') in ['filled','partial']:warnings.append(issue(f'orders[{i}].lifecycle','unconfirmed_fill','Status claims execution but quantity is zero; no completed sale will be shown'))
        except ArithmeticError:pass

def validate_observation(data,c,uid):
    errors=schema_errors(data,OBSERVATION);warnings=[]
    result={'valid':False,'errors':errors,'warnings':warnings}
    if not isinstance(data,dict):return result
    try:
        if len(canonical(data).encode())>131072:errors.append(issue('$','max_bytes','Maximum observation size 131072 bytes'))
    except (ValueError,TypeError,UnicodeError):errors.append(issue('$','invalid_json','Expected finite JSON'))
    # Only access structurally safe data below. No records are changed here.
    if errors:return result
    old=c.execute('SELECT digest FROM hot_watch_observations WHERE user_id=? AND observation_id=?',(uid,data['observation_id'])).fetchone()
    if old and old['digest']!=hashlib.sha256(canonical(data).encode()).hexdigest():errors.append(issue('observation_id','observation_id_conflict','Immutable observation ID already has different content'))
    parent=c.execute('SELECT id,payload FROM ingested_reports WHERE user_id=? AND report_id=? AND is_test=?',(uid,data['report_id'],int(data['is_test']))).fetchone()
    if not parent:errors.append(issue('report_id','unknown_reference','Expected owned report in the same test category'));return result
    report=json.loads(parent['payload']);candidate=next((x for x in report.get('candidates',[]) if x.get('candidate_id')==data['candidate_id']),None)
    if not candidate:errors.append(issue('candidate_id','unknown_reference','Expected candidate in the referenced v2 report'))
    elif data['instrument']['ticker'].casefold()!=candidate['ticker'].casefold():errors.append(issue('instrument.ticker','identity_mismatch','Ticker must match the stable candidate identity'))
    previous_asset=c.execute('SELECT payload FROM hot_watch_observations WHERE user_id=? AND is_test=? AND candidate_id=? ORDER BY observed DESC,id DESC LIMIT 1',(uid,int(data['is_test']),data['candidate_id'])).fetchone()
    known_assets={p.get('asset_id') for p in report.get('positions',[]) if p.get('candidate_id')==data['candidate_id'] and p.get('asset_id')}
    if previous_asset:
        old_asset=json.loads(previous_asset['payload'])['instrument']['asset_id']
        if old_asset:known_assets.add(old_asset)
    if data['instrument']['asset_id'] and known_assets and data['instrument']['asset_id'] not in known_assets:errors.append(issue('instrument.asset_id','identity_mismatch','Stable candidate is linked to another Pluto asset'))
    refs=data['position_ref']
    if refs and not any(all(p.get(k)==v for k,v in refs.items()) for p in report.get('positions',[])):errors.append(issue('position_ref','unknown_reference','Expected exact portfolio and position pair in the referenced report'))
    for i,key in enumerate(data['order_ids']):
        order=next((o for o in report.get('orders',[]) if o['order_id']==key),None)
        if not order:errors.append(issue(f'order_ids[{i}]','unknown_reference','Expected order in referenced report'))
        elif order.get('candidate_id') not in [None,data['candidate_id']] or refs and order['portfolio_id']!=refs['portfolio_id']:errors.append(issue(f'order_ids[{i}]','reference_mismatch','Order belongs to a different candidate or portfolio'))
    sources={s['source_id']:s for s in data['sources']}
    if len(sources)!=len(data['sources']):errors.append(issue('sources','duplicate_id','Source IDs must be unique'))
    def references(value,path=''):
        if isinstance(value,dict):
            for i,key in enumerate(value.get('source_ids',[])):
                if key not in sources:errors.append(issue(path+f'.source_ids[{i}]','unknown_reference','Expected source in observation.sources'))
            for k,v in value.items():references(v,(path+'.' if path else '')+k)
        elif isinstance(value,list):
            for i,v in enumerate(value):references(v,path+f'[{i}]')
    references(data)
    at=stamp(data['observed_at']);m=data['market']
    if stamp(data['deadline'])<at:errors.append(issue('deadline','invalid_deadline','Observation must be within its watch deadline'))
    for field in ['price_at','bid_at','ask_at','volume_at']:
        if m[field] and stamp(m[field])>at:errors.append(issue('market.'+field,'future_evidence','Market time cannot exceed observation time'))
    for value,timefield in [('price','price_at'),('bid','bid_at'),('ask','ask_at'),('volume','volume_at')]:
        if m[value] is not None and m[timefield] is None:errors.append(issue('market.'+timefield,'required_evidence','Known market value requires its actual timestamp'))
    if m['price_source']=='pluto' and m['price'] is not None and data['instrument']['asset_id'] is None:errors.append(issue('instrument.asset_id','required_evidence','Pluto price requires its asset ID'))
    if m['spread'] is not None and (m['bid_at'] is None or m['ask_at'] is None):errors.append(issue('market.spread','required_evidence','Spread requires bid and ask timestamps'))
    if m['bid'] and m['ask'] and m['spread'] and m['bid_at']==m['ask_at'] and len({m[k]['currency'] for k in ['bid','ask','spread']})==1:
        with localcontext() as ctx:
            ctx.prec=60
            if Decimal(m['ask']['amount'])-Decimal(m['bid']['amount'])!=Decimal(m['spread']['amount']):errors.append(issue('market.spread','inconsistent_spread','Spread must match simultaneous ask minus bid'))
    if m['verification']!='verified' and any(m[k] is not None for k in ['price','bid','ask','spread','spread_percent','volume','intraday_percent']):errors.append(issue('market.verification','unverified_value','Unverified market values must be null'))
    if m['verification']=='verified' and (not m['source_ids'] or any(sources.get(k,{}).get('verification')!='verified' for k in m['source_ids'])):errors.append(issue('market.source_ids','required_evidence','Verified market data requires verified sources'))
    amounts=[m[k] for k in ['price','bid','ask','spread'] if m[k]]
    if len({x['currency'] for x in amounts})>1:errors.append(issue('market','currency_mismatch','Market monetary observations must use the same currency'))
    if m['bid'] and m['ask'] and Decimal(m['bid']['amount'])>Decimal(m['ask']['amount']):errors.append(issue('market.ask','crossed_market','Ask cannot be below bid'))
    if data['decision']:errors.extend(decision_errors(data['decision'],'decision',data['observed_at'],prior_decision(c,uid,data['is_test'],data['candidate_id'],at.timestamp())))
    trades=set()
    for i,trade in enumerate(data['recent_trades']):
        if trade['trade_id'] in trades:errors.append(issue(f'recent_trades[{i}].trade_id','duplicate_id','Trade IDs must be unique within observation'))
        trades.add(trade['trade_id'])
        if not trade['source_ids'] or any(sources.get(k,{}).get('verification')!='verified' for k in trade['source_ids']):errors.append(issue(f'recent_trades[{i}].source_ids','required_evidence','Feed trades require verified sources'))
        if stamp(trade['occurred_at'])>at:errors.append(issue(f'recent_trades[{i}].occurred_at','future_evidence','Trade cannot be later than observation'))
    if data['position_action'] and stamp(data['position_action']['assessed_at'])>at:errors.append(issue('position_action.assessed_at','future_evidence','Position assessment cannot be later than observation'))
    if data['position_action'] and not refs:errors.append(issue('position_ref','required_evidence','Position action requires a specific owned position'))
    result['valid']=not errors
    return result

def record(connect,uid,data):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');checked=validate_observation(data,c,uid)
        if not checked['valid']:
            if any(e['code']=='observation_id_conflict' for e in checked['errors']):return 409,{'ok':False,**checked}
            raise ReportValidationError(checked)
        old=c.execute('SELECT id FROM hot_watch_observations WHERE user_id=? AND observation_id=?',(uid,data['observation_id'])).fetchone()
        if old:return 200,{'ok':True,'observation_id':data['observation_id'],'duplicate':True}
        parent=c.execute('SELECT id FROM ingested_reports WHERE user_id=? AND report_id=?',(uid,data['report_id'])).fetchone()
        payload=canonical(data)
        c.execute('INSERT INTO hot_watch_observations(user_id,is_test,observation_id,candidate_id,report_row_id,observed,payload,digest,received) VALUES(?,?,?,?,?,?,?,?,?)',(uid,int(data['is_test']),data['observation_id'],data['candidate_id'],parent['id'],stamp(data['observed_at']).timestamp(),payload,hashlib.sha256(payload.encode()).hexdigest(),now()))
        index_decision(c,uid,data['is_test'],data['candidate_id'],data['decision'],data['observation_id'])
        return 201,{'ok':True,'observation_id':data['observation_id'],'duplicate':False,'warnings':checked['warnings']}

def order_state(o):
    """Explicit precedence; execution quantity is required before a filled label."""
    status=(o.get('status') or '').upper();life=o.get('lifecycle');approval=o.get('approval_status')
    try:filled=Decimal(o['filled_quantity']) if o.get('filled_quantity') is not None else None;requested=Decimal(o['requested_quantity']) if o.get('requested_quantity') is not None else None
    except ArithmeticError:filled=requested=None
    if filled is not None and filled>0:
        if life=='filled' and requested is not None and requested>0 and filled==requested:return 'Fuldt udført'
        return 'Delvist udført' if requested is not None and filled<requested else 'Fyldning oplyst · slutstatus ukendt'
    if life=='expired' or status in ['EXPIRED','UDLØBET']:return 'Udløbet'
    if life=='cancelled' or status in ['CANCELLED','CANCELED']:return 'Annulleret'
    if life=='rejected' or status=='REJECTED' or approval=='rejected':return 'Afvist'
    if status in ['ACCEPTED','ACTIVE','ACTIVE_STOP','OPEN','NEW','ACTIVE_BUY']:return 'Accepteret / aktiv · ingen bekræftet fyldning'
    if approval in ['proposed','awaiting_approval','approved']:return {'proposed':'Forslag','awaiting_approval':'Afventer godkendelse','approved':'Godkendt · afsendelse ikke bekræftet'}[approval]
    return 'Afventer · udførelse ikke bekræftet' if life=='pending' else 'Ukendt status'

def delta(a,b):
    if not a or not b or a['currency']!=b['currency']:return None
    with localcontext() as ctx:
        ctx.prec=60
        return {'amount':format(Decimal(a['amount'])-Decimal(b['amount']),'f'),'currency':a['currency']}

def observation_view(d,previous=None):
    m=d['market'];old=previous['market'] if previous else {};changes={'price':None,'spread':None,'volume':None,'decision':None,'momentum':m['momentum']}
    if previous:
        for field,at in [('price','price_at'),('spread','bid_at')]:
            # Spread comparisons require paired bid/ask times; no interpolation.
            comparable=m['verification']==old['verification']=='verified' and m.get(at) and old.get(at) and stamp(m[at])>stamp(old[at])
            if field=='spread':comparable=comparable and m['bid_at']==m['ask_at'] and old['bid_at']==old['ask_at']
            if comparable:changes[field]=delta(m[field],old[field])
        if m['verification']==old['verification']=='verified' and m['volume_basis'] and m['volume_basis']==old['volume_basis'] and m['volume'] is not None and old['volume'] is not None and m['volume_at'] and old['volume_at'] and stamp(m['volume_at'])>stamp(old['volume_at']):
            with localcontext() as ctx:ctx.prec=60;changes['volume']=format(Decimal(m['volume'])-Decimal(old['volume']),'f')
        if d['decision'] and previous['decision'] and d['decision']['status']!=previous['decision']['status']:changes['decision']={'from':previous['decision']['status'],'to':d['decision']['status'],'reason':d['decision']['reason']}
    return {'data':d,'changes':changes}

def watch(connect,uid,is_test=False,candidate_id=None):
    with connect() as c:
        args=[uid,int(is_test)];where=''
        if candidate_id:where=' AND candidate_id=?';args.append(candidate_id)
        rows=c.execute('SELECT payload FROM hot_watch_observations WHERE user_id=? AND is_test=?'+where+' ORDER BY observed DESC,id DESC LIMIT 501',args).fetchall()
        groups={}
        for row in reversed(rows[:500]):
            d=json.loads(row['payload']);cid=d['candidate_id'];group=groups.setdefault(cid,{'candidate_id':cid,'observations':[]})
            prior=group['observations'][-1]['data'] if group['observations'] else None
            group['observations'].append(observation_view(d,prior))
        for group in groups.values():
            latest=group['observations'][-1]['data'];decision=prior_decision(c,uid,is_test,group['candidate_id']);group['decision']=decision[1] if decision else None
            group['active']=stamp(latest['deadline'])>=datetime.now(timezone.utc) and (not decision or decision[1]['status']!='FRAVÆLG')
            group['observations'].reverse()
            report=c.execute('SELECT payload FROM ingested_reports WHERE user_id=? AND is_test=? AND report_id=?',(uid,int(is_test),latest['report_id'])).fetchone();d=json.loads(report['payload'])
            group['positions']=[p for p in d.get('positions',[]) if p.get('candidate_id')==group['candidate_id'] or latest['position_ref'] and all(p.get(k)==v for k,v in latest['position_ref'].items())]
            # Current order facts may be newer than the last watch measurement.
            # Keep only the latest immutable report observation per order ID.
            order_rows=c.execute("SELECT j.value,r.report_id,r.generated_epoch FROM ingested_reports r JOIN json_each(r.payload,'$.orders') j WHERE r.user_id=? AND r.is_test=? AND r.report_type!='deep_analysis' AND (json_extract(j.value,'$.candidate_id')=? OR json_extract(j.value,'$.order_id') IN (SELECT value FROM json_each(?))) ORDER BY r.generated_epoch DESC,r.id DESC",(uid,int(is_test),group['candidate_id'],json.dumps(latest['order_ids']))).fetchall()
            orders={}
            for row in order_rows:
                order=json.loads(row['value'])
                if order['order_id'] not in orders:orders[order['order_id']]=dict(order,display_status=order_state(order),report_id=row['report_id'])
            group['orders']=list(orders.values())
        return {'waiting_candidates':[r for r in candidates(c,uid,is_test,include_history_market=False) if r.get('display_group')=='waiting'],'active_candidates':[r for r in candidates(c,uid,is_test,include_history_market=False) if r.get('display_group') in ['active','buy','exit']],'groups':sorted(groups.values(),key=lambda x:stamp(x['observations'][0]['data']['observed_at']).timestamp(),reverse=True),'is_test':is_test,'history_truncated':len(rows)>500}

def candidates(c,uid,mode=False,candidate_id=None,include_history_market=True):
    ids=[candidate_id] if candidate_id is not None else [r[0] for r in c.execute('SELECT DISTINCT candidate_id FROM report_candidate_links WHERE user_id=? AND is_test=?',(uid,int(mode)))]
    result=[]
    query='SELECT r.payload,r.report_id,r.received,l.generated FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=? AND l.candidate_id=? '
    for cid in ids:
        args=(uid,int(mode),cid)
        latest=c.execute(query+'ORDER BY l.generated DESC,r.id DESC LIMIT 1',args).fetchone()
        if not latest:continue
        oldest=c.execute(query+'ORDER BY l.generated,r.id LIMIT 1',args).fetchone()
        d=json.loads(latest['payload']);candidate=next(x for x in d['candidates'] if x['candidate_id']==cid);current_decision=prior_decision(c,uid,mode,cid)
        first=json.loads(oldest['payload']);initial=next(x for x in first['candidates'] if x['candidate_id']==cid)
        observations=c.execute('SELECT payload FROM hot_watch_observations WHERE user_id=? AND is_test=? AND candidate_id=? ORDER BY observed DESC,id DESC LIMIT 1',args).fetchone()
        observed=json.loads(observations['payload']) if observations else None
        markets=[]
        current_market=candidate['market']
        if current_market['verification']=='verified' and current_market['price'] and current_market['as_of']:markets.append(dict(current_market,origin=d['report_id']))
        if include_history_market:
            # Fetch only this candidate's object, never every full report per ID.
            for row in c.execute("SELECT j.value,r.report_id FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id JOIN json_each(r.payload,'$.candidates') j WHERE l.user_id=? AND l.is_test=? AND l.candidate_id=? AND json_extract(j.value,'$.candidate_id')=l.candidate_id AND json_extract(j.value,'$.market.verification')='verified' AND json_type(j.value,'$.market.price')='object'",args):
                m=json.loads(row['value'])['market']
                if m['as_of']:markets.append(dict(m,origin=row['report_id']))
            obs_rows=c.execute("SELECT payload FROM hot_watch_observations WHERE user_id=? AND is_test=? AND candidate_id=? AND json_extract(payload,'$.market.verification')='verified' AND json_type(payload,'$.market.price')='object'",args)
        else:obs_rows=[observations] if observed and observed['market']['verification']=='verified' and observed['market']['price'] else []
        for row in obs_rows:
            obs=json.loads(row['payload']);m=obs['market']
            if m['price_at']:markets.append({'price':m['price'],'as_of':m['price_at'],'verification':'verified','source_ids':m['source_ids'],'origin':obs['observation_id']})
        latest_market=max(markets,key=lambda m:stamp(m['as_of'])) if markets else None
        last_seen=max([d['generated_at']]+([observed['observed_at']] if observed else []),key=lambda t:stamp(t))
        import candidate_lifecycle
        status=candidate_lifecycle.projection(c,uid,mode,candidate,current_decision[1] if current_decision else None)
        import display_policy
        status['display_group']=display_policy.candidate_group(status)
        result.append({**status,'latest_verified_market':latest_market,'candidate':candidate,'decision':current_decision[1] if current_decision else None,'decision_origin':current_decision[2] if current_decision else None,'active':status['lifecycle']['status'] not in ['CLOSED','ARCHIVED'] and (not current_decision or current_decision[1]['status']!='FRAVÆLG'),'first_seen':first['generated_at'],'last_seen':last_seen,'first_price':initial['market']['price'],'report_id':d['report_id'],'received':latest['received'],'generated_at':d['generated_at'],'schema_version':2,'quality':d.get('data_quality',{}).get('status','unknown')})
    return result

def account_projection(report):
    d=report.get('data',{}) if report else {};portfolios=d.get('portfolios',[])
    roots=[p for p in portfolios if p['kind']=='portfolio' and p['parent_portfolio_id'] is None];ais=[p for p in portfolios if p['role']=='ai_trader' and p['kind']=='collection']
    result={'root':None,'ai':None,'main_ex_ai':None,'available':[],'reason':'Sammenligneligt talgrundlag ikke oplyst'}
    if len(roots)!=1 or len(ais)!=1:return result
    root,ai=roots[0],ais[0];result.update(root=root,ai=ai,available=(root.get('liquidity') or {}).get('available',[]))
    try:
        sources={s['source_id']:s for s in d.get('sources',[])}
        if any(not p['source_ids'] or any(sources.get(k,{}).get('verification')!='verified' for k in p['source_ids']) for p in [root,ai]):return result
        if root['includes_collections'] is not True or ai['parent_portfolio_id']!=root['portfolio_id'] or not root.get('valuation_method') or root['valuation_method']!=ai.get('valuation_method') or stamp(root['as_of'])!=stamp(ai['as_of']) or not root['value'] or not ai['value'] or root['value']['currency']!=ai['value']['currency']:return result
        result['main_ex_ai']=delta(root['value'],ai['value']);result['reason']='Root minus AI · samme valuta, datatid og værdiansættelsesmetode; AI er allerede inkluderet i root'
    except (ValueError,TypeError):pass
    return result
