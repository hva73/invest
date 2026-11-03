"""Authoritative broker holdings + optional exact report assessments. Read-only dashboard."""
import json,hashlib
from datetime import datetime,timezone
from decimal import Decimal
import display_policy as policy

def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS display_holdings_cache(portfolio_id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,observed TEXT NOT NULL,payload TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS display_price_observations(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,portfolio_id INTEGER NOT NULL,asset_id TEXT NOT NULL,event_time TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,UNIQUE(user_id,portfolio_id,digest))')
 c.execute('CREATE INDEX IF NOT EXISTS display_price_history ON display_price_observations(user_id,portfolio_id,asset_id,id)')

def observation(row):
 price=row.get('price') or {};meta=row.get('market_context') or {}
 return {'asset_id':row.get('asset_id'),'source':'pluto','currency':price.get('currency'),'price':price.get('amount'),'event_time':row.get('price_time'),'feed_type':meta.get('feed_type'),'venue':meta.get('venue'),'market_phase':meta.get('market_phase'),'session_key':meta.get('session_key'),'price_type':meta.get('price_type'),'adjustment_basis':meta.get('adjustment_basis')}

def remember(c,uid,pid,payload):
 if payload.get('positions_complete'):
  c.execute('INSERT INTO display_holdings_cache VALUES(?,?,?,?) ON CONFLICT(portfolio_id) DO UPDATE SET observed=excluded.observed,payload=excluded.payload WHERE excluded.observed>=display_holdings_cache.observed',(pid,uid,payload['observed'],json.dumps(payload)))
 for row in payload.get('positions',[]):
  data=observation(row)
  if row.get('kind')!='holding' or not data['asset_id'] or not policy.stamp(data['event_time']) or policy.decimal(data['price']) is None:continue
  raw=json.dumps(data,sort_keys=True,separators=(',',':'));digest=hashlib.sha256(raw.encode()).hexdigest()
  c.execute('INSERT OR IGNORE INTO display_price_observations(user_id,portfolio_id,asset_id,event_time,payload,digest) VALUES(?,?,?,?,?,?)',(uid,pid,data['asset_id'],data['event_time'],raw,digest))

def assessment_candidates(c,uid):
 rows=c.execute("SELECT payload,report_id,generated_epoch FROM ingested_reports WHERE user_id=? AND is_test=0 AND json_extract(payload,'$.schema_version')=2 ORDER BY generated_epoch DESC,id DESC LIMIT 300",(uid,)).fetchall()
 result=[]
 for row in rows:
  data=json.loads(row['payload']);ports={p['portfolio_id']:p for p in data.get('portfolios',[])}
  for position in data.get('positions',[]):
   if position.get('asset_id') and position.get('assessment'):result.append((position,ports.get(position['portfolio_id'],{}),row['report_id'],data['generated_at']))
 return result

def build(connect,uid,owned,snapshots,now=None):
 now=now or datetime.now(timezone.utc);result=[];warnings=[];totals={};accounts=[];orders=[]
 with connect() as c:
  reports=assessment_candidates(c,uid)
  for p in owned:
   if p['source']!='pluto' or not p['active']:continue
   snapshot=snapshots.get(str(p['id']));data=snapshot.get('data') if snapshot else None
   if not data:
    warnings.append({'portfolio':p['name'],'reason':'NOT_FETCHED'});continue
   failed=bool(snapshot.get('last_error'));scope_time=data.get('observed');position_data=data
   if not data.get('positions_complete'):
    cached=c.execute('SELECT payload FROM display_holdings_cache WHERE user_id=? AND portfolio_id=?',(uid,p['id'])).fetchone()
    if cached:position_data=json.loads(cached['payload'])
    warnings.append({'portfolio':p['name'],'reason':'SOURCE_ERROR' if failed else 'INCOMPLETE_SNAPSHOT'})
   if failed:warnings.append({'portfolio':p['name'],'reason':'SOURCE_ERROR'})
   value=(data.get('value') or {}).get('value')
   if p['kind']=='portfolio' and value and policy.decimal(value.get('amount')) is not None and value.get('currency'):
    totals[value['currency']]=totals.get(value['currency'],Decimal(0))+Decimal(value['amount'])
   accounts.append({'id':p['id'],'name':p['name'],'kind':p['kind'],'parent_external_id':p.get('parent_external_id'),'value':value,'as_of':(data.get('value') or {}).get('source_time'),'snapshot_at':scope_time,'failed':failed})
   for order in data.get('pending_orders',[])+data.get('unconfirmed_orders',[]):
    orders.append(dict(order,portfolio_id=p['id'],portfolio_name=p['name'],source='Pluto',observed_at=scope_time,verification='last_known' if failed else 'broker_snapshot'))
   for index,row in enumerate(position_data.get('positions',[])):
    if row.get('kind')=='collection':continue
    qty=policy.decimal(row.get('quantity'))
    if qty==0:continue
    aid=row.get('asset_id');identity=f"pluto:{p['id']}:{aid}" if aid else f"unmatched:{p['id']}:{index}"
    matches=[]
    for pos,port,rid,at in reports:
     ref=port.get('broker_reference') or {};exact=port.get('portfolio_id')==p['external_id'] or ref.get('provider')=='pluto' and ref.get('external_id')==p['external_id']
     if aid and pos['asset_id']==aid and exact:matches.append((pos,rid,at))
    matched=matches[0] if matches else None;report=matched[0] if matched else None;a=report.get('assessment') if report else None
    conflicts=[]
    if report and policy.decimal(report.get('quantity'))!=qty:conflicts.append('Antal i rapporten afviger fra Pluto')
    if report and report.get('ticker') and row.get('ticker') and report['ticker'].casefold()!=row['ticker'].casefold():conflicts.append('Tickernavn afviger; kontrollér aktividentiteten')
    if not aid:conflicts.append('Aktiv-ID mangler; ingen automatisk analysekobling')
    raw_value=row.get('value') or {};dkk=row.get('value_in_portfolio_currency') or {};shown=dkk if dkk.get('currency')=='DKK' and policy.decimal(dkk.get('amount')) is not None else raw_value
    pnl_dkk=row.get('unrealized_in_portfolio_currency') or {};raw_pnl=row.get('unrealized') or {}
    pnl=pnl_dkk if pnl_dkk.get('currency')=='DKK' and policy.decimal(pnl_dkk.get('amount')) is not None else raw_pnl
    if row.get('unrealized_basis'):pnl=None # legacy estimate lacks documented fees; do not claim broker P/L.
    if pnl and policy.decimal(pnl.get('amount')) is None:pnl=None
    cost=row.get('cost_basis') or {};pnl_percent=None
    if pnl and pnl.get('currency')==cost.get('currency') and policy.decimal(cost.get('amount')) is not None and Decimal(cost['amount'])>0:pnl_percent=str(Decimal(pnl['amount'])/Decimal(cost['amount'])*100)
    obs=observation(row);since=None
    if aid and policy.stamp(obs['event_time']):
     previous=c.execute('SELECT payload FROM display_price_observations WHERE user_id=? AND portfolio_id=? AND asset_id=? ORDER BY id DESC LIMIT 120',(uid,p['id'],aid)).fetchall()
     for old in previous:
      prior=json.loads(old['payload'])
      if policy.stamp(prior['event_time']) and policy.stamp(prior['event_time'])<policy.stamp(obs['event_time']):
       since=policy.comparison(obs,prior);break
    market=row.get('market_context') or {};market_state=market.get('session') if isinstance(market.get('session'),dict) else None
    daily=policy.daily_change(obs,row.get('official_close_reference'))
    price_age=policy.freshness('snapshot',row.get('price_time'),now,market_state,failed,obs.get('session_key'))
    analysis_age=policy.freshness('analysis',a.get('assessed_at'),now) if a else {'state':'unknown','reason':'NOT_PROVIDED'}
    action=a.get('action') if a else None
    result.append({'key':identity,'portfolio_id':p['id'],'portfolio_name':p['name'],'portfolio_kind':p['kind'],'external_id':p['external_id'],'asset_id':aid,'ticker':row.get('ticker'),'name':row.get('name'),'quantity':row.get('quantity'),'price':row.get('price'),'price_time':row.get('price_time'),'value':shown,'original_value':raw_value,'cost_basis':cost,'average_entry':row.get('average_entry'),'unrealized':pnl,'unrealized_percent':pnl_percent,'daily':daily,'since_last':since,'assessment':a,'assessment_report_id':matched[1] if matched else None,'reported_position':report,'action':action,'critical':action in ['SÆLG','REDUCÉR'] or bool(conflicts),'price_freshness':price_age,'analysis_freshness':analysis_age,'snapshot_at':position_data.get('observed'),'verification':'last_known' if failed or not data.get('positions_complete') else 'broker_snapshot','conflicts':conflicts,'missing':{'daily':'NOT_PROVIDED' if daily is None else None,'since_last':'NOT_PROVIDED' if since is None else None,'fx':'NOT_PROVIDED' if shown.get('currency')!='DKK' else None,'assessment':'NOT_PROVIDED' if not a else None},'raw':row})
  try:
   sessions=[dict(r) for r in c.execute("SELECT watch_id,status,last_error,last_data FROM hw_sessions WHERE user_id=? AND is_test=0 AND status IN ('DEGRADED','ERROR')",(uid,)).fetchall()]
  except Exception:sessions=[]
 currencies={r['value'].get('currency') for r in result if r['value']}
 result.sort(key=lambda r:(not r['critical'],r['portfolio_name'].casefold(),r['value'].get('currency') or '',-(policy.decimal(r['value'].get('amount')) or Decimal(0)),r['ticker'] or ''))
 return {'version':'design-1','positions':result,'count':len(result),'accounts':accounts,'totals':[{'currency':k,'amount':str(v)} for k,v in totals.items()],'daily_result':None,'daily_result_reason':'Pengestrømme og dokumenteret dagsreference er ikke tilgængelige','orders':orders,'warnings':warnings,'critical_sessions':sessions,'snapshot_at':max((a['snapshot_at'] for a in accounts if a['snapshot_at']),default=None),'mixed_value_currencies':len(currencies)>1}
