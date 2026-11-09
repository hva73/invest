"""Authoritative broker holdings + optional exact report assessments. Read-only dashboard."""
import json,hashlib
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import display_policy as policy

def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS display_holdings_cache(portfolio_id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,observed TEXT NOT NULL,payload TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS display_portfolio_values(user_id INTEGER NOT NULL,scope TEXT NOT NULL,observed_epoch REAL NOT NULL,observed TEXT NOT NULL,amount TEXT NOT NULL,currency TEXT NOT NULL,source_time TEXT,reported_result TEXT,PRIMARY KEY(user_id,scope,observed_epoch))')
 exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='display_price_observations'").fetchone()
 columns={r['name']:dict(r) for r in c.execute('PRAGMA table_info(display_price_observations)')} if exists else {}
 if exists and ('received_at' not in columns or columns.get('event_time',{}).get('notnull')):
  # Keep real market event times nullable and store API receipt/snapshot time separately.
  c.execute('DROP INDEX IF EXISTS display_price_history')
  c.execute('ALTER TABLE display_price_observations RENAME TO display_price_observations_legacy')
  c.execute('CREATE TABLE display_price_observations(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,portfolio_id INTEGER NOT NULL,asset_id TEXT NOT NULL,event_time TEXT,received_at TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,UNIQUE(user_id,portfolio_id,digest))')
  for row in c.execute('SELECT id,user_id,portfolio_id,asset_id,event_time,payload,digest FROM display_price_observations_legacy').fetchall():
   # Legacy rows have a true price event time; receipt time was not captured.
   c.execute('INSERT INTO display_price_observations VALUES(?,?,?,?,?,?,?,?)',(row['id'],row['user_id'],row['portfolio_id'],row['asset_id'],row['event_time'],'',row['payload'],row['digest']))
  c.execute('DROP TABLE display_price_observations_legacy')
 c.execute('CREATE TABLE IF NOT EXISTS display_price_observations(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,portfolio_id INTEGER NOT NULL,asset_id TEXT NOT NULL,event_time TEXT,received_at TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,UNIQUE(user_id,portfolio_id,digest))')
 c.execute('CREATE INDEX IF NOT EXISTS display_price_history ON display_price_observations(user_id,portfolio_id,asset_id,id)')

def portfolio_value_snapshot(c,uid,allow_failed=False):
 """Aggregate only complete, comparable root snapshots; collections are included."""
 rows=c.execute("SELECT p.id,s.observed,s.payload,s.last_error FROM portfolios p LEFT JOIN portfolio_snapshots s ON s.portfolio_id=p.id AND s.user_id=p.user_id WHERE p.user_id=? AND p.source='pluto' AND p.active=1 AND p.kind='portfolio' ORDER BY p.id",(uid,)).fetchall()
 if not rows:return None
 amounts=[];times=[];source_times=[];profits=[];currency=None
 for row in rows:
  if (row['last_error'] and not allow_failed) or not row['payload']:return None
  try:
   payload=json.loads(row['payload']);value=payload.get('value') or {};money=value.get('value') or {};amount=policy.decimal(money.get('amount'));code=money.get('currency');observed=policy.stamp(row['observed'])
   if amount is None or not isinstance(code,str) or not observed or currency and currency!=code:return None
   currency=code;amounts.append(amount);times.append(observed)
   source=policy.stamp(value.get('source_time'));source_times.append(source)
   profit=value.get('reported_result') or {};p=policy.decimal(profit.get('amount'))
   profits.append(p if p is not None and profit.get('currency')==code else None)
  except (ValueError,TypeError,AttributeError):return None
 if (max(times)-min(times)).total_seconds()>300:return None
 scope=hashlib.sha256(('|'.join(str(row['id']) for row in rows)+'|'+currency).encode()).hexdigest()
 return {'scope':scope,'observed':max(times),'amount':sum(amounts,Decimal(0)),'currency':currency,'source_time':min(source_times).isoformat() if all(source_times) else None,'reported_result':sum(profits,Decimal(0)) if all(x is not None for x in profits) else None}

def remember_portfolio_value(c,uid):
 value=portfolio_value_snapshot(c,uid)
 if not value:return
 at=value['observed']
 c.execute('INSERT OR IGNORE INTO display_portfolio_values VALUES(?,?,?,?,?,?,?,?)',(uid,value['scope'],at.timestamp(),at.isoformat(),str(value['amount']),value['currency'],value['source_time'],str(value['reported_result']) if value['reported_result'] is not None else None))

def portfolio_value_history(c,uid,now):
 """Return recorded, scope-matched points with bounded sampling per period."""
 from calendar import monthrange
 from zoneinfo import ZoneInfo
 current=portfolio_value_snapshot(c,uid)
 fresh_snapshot=bool(current)
 if not current:current=portfolio_value_snapshot(c,uid,allow_failed=True)
 if not current:return {'periods':{},'reported_result':None}
 local=now.astimezone(ZoneInfo('Europe/Copenhagen'));local_midnight=local.replace(hour=0,minute=0,second=0,microsecond=0);midnight=local_midnight.astimezone(timezone.utc);next_midnight=(local_midnight+timedelta(days=1)).astimezone(timezone.utc)
 def months_before(months):
  index=local.year*12+local.month-1-months;year,month=divmod(index,12);month+=1
  return local.replace(year=year,month=month,day=min(local.day,monthrange(year,month)[1])).astimezone(timezone.utc)
 periods={}
 for name,start,bucket in [('day',midnight,300),('week',(local-timedelta(days=7)).astimezone(timezone.utc),3600),('month',months_before(1),21600),('year',months_before(12),86400)]:
  args=(uid,current['scope'],start.timestamp(),now.timestamp())
  first=c.execute('SELECT observed_epoch,observed,amount,currency,source_time,reported_result FROM display_portfolio_values WHERE user_id=? AND scope=? AND observed_epoch BETWEEN ? AND ? ORDER BY observed_epoch LIMIT 1',args).fetchone()
  rows=c.execute('SELECT observed_epoch,observed,amount,currency,source_time,reported_result FROM display_portfolio_values WHERE user_id=? AND scope=? AND observed_epoch IN (SELECT MAX(observed_epoch) FROM display_portfolio_values WHERE user_id=? AND scope=? AND observed_epoch BETWEEN ? AND ? GROUP BY CAST(observed_epoch / ? AS INTEGER)) ORDER BY observed_epoch',(uid,current['scope'],*args,bucket)).fetchall()
  points=([first] if first and (not rows or first['observed_epoch']!=rows[0]['observed_epoch']) else [])+list(rows)
  periods[name]=[{'at':r['observed'],'amount':r['amount'],'currency':r['currency'],'source_time':r['source_time'],'reported_result':r['reported_result']} for r in points]
 result=current['reported_result'] if fresh_snapshot else None
 return {'periods':periods,'day_start':midnight.isoformat(),'day_end':next_midnight.isoformat(),'current_value':{'amount':str(current['amount']),'currency':current['currency']} if fresh_snapshot else None,'reported_result':{'amount':str(result),'currency':current['currency']} if result is not None else None}

def observation(row,received_at=None):
 price=row.get('price') or {};meta=row.get('market_context') or {}
 price_type=meta.get('price_type') or row.get('price_type') or ('get_asset_latest' if row.get('price_source')=='Pluto get_asset · senest kendte pris' else None)
 return {'asset_id':row.get('asset_id'),'source':'pluto','currency':price.get('currency'),'price':price.get('amount'),'event_time':row.get('price_time'),'received_at':received_at,'feed_type':meta.get('feed_type'),'venue':meta.get('venue'),'market_phase':meta.get('market_phase'),'session_key':meta.get('session_key'),'price_type':price_type,'adjustment_basis':meta.get('adjustment_basis')}

def remember(c,uid,pid,payload):
 if payload.get('positions_complete'):
  c.execute('INSERT INTO display_holdings_cache VALUES(?,?,?,?) ON CONFLICT(portfolio_id) DO UPDATE SET observed=excluded.observed,payload=excluded.payload WHERE excluded.observed>=display_holdings_cache.observed',(pid,uid,payload['observed'],json.dumps(payload)))
 for row in payload.get('positions',[]):
  data=observation(row,payload.get('observed'))
  if row.get('kind')!='holding' or not data['asset_id'] or not policy.stamp(data['received_at']) or policy.decimal(data['price']) is None:continue
  raw=json.dumps(data,sort_keys=True,separators=(',',':'));digest=hashlib.sha256(raw.encode()).hexdigest()
  c.execute('INSERT OR IGNORE INTO display_price_observations(user_id,portfolio_id,asset_id,event_time,received_at,payload,digest) VALUES(?,?,?,?,?,?,?)',(uid,pid,data['asset_id'],data['event_time'],data['received_at'],raw,digest))

def snapshot_comparison(current,previous):
 # A Pluto retrieval is a known observation of its latest-price field, not proof of
 # the underlying market event time. Keep those two clocks visibly distinct.
 required=['asset_id','source','currency','price_type']
 if any(not current.get(k) or current.get(k)!=previous.get(k) for k in required):return None
 for key in ['venue','adjustment_basis']:
  if current.get(key) and previous.get(key) and current[key]!=previous[key]:return None
 now=policy.stamp(current.get('received_at'));old=policy.stamp(previous.get('received_at'))
 x=policy.decimal(current.get('price'));y=policy.decimal(previous.get('price'))
 if not now or not old or now<=old or x is None or y is None or x<=0 or y<=0:return None
 return {'percent':str((x-y)/y*100),'amount':str(x-y),'currency':current['currency'],'from':previous['received_at'],'to':current['received_at'],'basis':'pluto_snapshot_received_at','prior_received_at':previous['received_at'],'price_event_time_known':bool(current.get('event_time') and previous.get('event_time'))}

def assessment_candidates(c,uid):
 rows=c.execute("SELECT payload,report_id,generated_epoch FROM ingested_reports WHERE user_id=? AND is_test=0 AND json_extract(payload,'$.schema_version')=2 ORDER BY generated_epoch DESC,id DESC LIMIT 300",(uid,)).fetchall()
 result=[]
 for row in rows:
  data=json.loads(row['payload']);ports={p['portfolio_id']:p for p in data.get('portfolios',[])}
  for position in data.get('positions',[]):
   if position.get('asset_id'):result.append((position,ports.get(position['portfolio_id'],{}),row['report_id'],data['generated_at']))
 return result

def position_hotwatch(c,uid,portfolio_id,asset_id,report_position):
 candidate_id=report_position.get('candidate_id') if report_position else None
 cycle=report_position.get('trade_cycle_id') if report_position else None
 rows=c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND is_test=0 ORDER BY id DESC",(uid,)).fetchall()
 matches=[]
 for row in rows:
  request=json.loads(row['request'])
  scopes=request.get('portfolio_ids',[])
  if not asset_id or request.get('asset_id')!=asset_id or request.get('watch_mode','both')=='entry' or scopes and portfolio_id not in scopes:continue
  if candidate_id:
   if request.get('candidate_id')!=candidate_id:continue
   if cycle and request.get('trade_cycle_id') and request['trade_cycle_id']!=cycle:continue
  elif cycle and request.get('trade_cycle_id')!=cycle:continue
  matches.append((row,request))
 if not candidate_id and cycle and len({r['candidate_id'] for r,_ in matches})==1 and matches:candidate_id=matches[0][0]['candidate_id']
 lifecycle=None
 if candidate_id:
  lifecycle=c.execute('SELECT status,reported_status,occurred_at,reason,cycle_id,evidence FROM candidate_lifecycle_events WHERE user_id=? AND is_test=0 AND candidate_id=? ORDER BY occurred DESC,id DESC LIMIT 1',(uid,candidate_id)).fetchone()
 active=[(r,req) for r,req in matches if r['status'] in ['CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED']]
 session=(active[0] if len(active)==1 else None) if not candidate_id and not cycle else next(iter(active),matches[0] if matches else None)
 asset_fallback=False
 if not session and asset_id:
  fallback=[]
  for row in rows:
   request=json.loads(row['request']);scope=request.get('portfolio_ids',[])
   if row['status'] in ['CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED'] and request.get('asset_id')==asset_id and request.get('watch_mode','both')!='entry' and (not scope or portfolio_id in scope) and (not cycle or request.get('purpose')=='automatic holding watch'):fallback.append((row,request))
  if len(fallback)==1:session=fallback[0];asset_fallback=True
 auto=c.execute('SELECT status,watch_id,updated,next_attempt FROM hw_holding_autowatch WHERE user_id=? AND portfolio_id=? AND asset_id=?',(uid,portfolio_id,asset_id)).fetchone() if asset_id else None
 import hotwatch_engine
 current=None
 if session:
  try:current=hotwatch_engine.view(c,session[0])
  except (KeyError,TypeError,ValueError):current={'watch_id':session[0]['watch_id'],'status':session[0]['status'],'last_data_at':session[0]['last_data'],'signal':'NO_DATA','display_status':'DATA MANGLER'}
 warmup=None
 if current and 'WARMUP' in ((current.get('latest_calculation') or {}).get('reason_codes') or []) and 'DATA_UNVERIFIED' not in ((current.get('latest_calculation') or {}).get('reason_codes') or []):
  count=((current.get('latest_calculation') or {}).get('supporting_metrics') or {}).get('sample_count');required=current.get('minimum_required_samples')
  if type(count) is int and type(required) is int and 0<=count<required:
   warmup={'count':count,'required':required,'remaining':required-count}
   if current.get('display_status')!='WARMUP':warmup['historical']=True
   elif ((current.get('data_status') or {}).get('instrument_match_evidence') or {}).get('basis')=='user_authorized_btc_monitoring' and (current.get('data_status') or {}).get('market_status')=='UNKNOWN':warmup['market_status_unknown']=True
 if current:
  quality=current.get('data_status') or {};analysis=quality.get('analysis_warmup')
  if analysis and warmup is None:
   regular_closed=(quality.get('regular_session') or {}).get('status')=='CLOSED'
   warmup={'count':analysis['count'],'required':analysis['required'],'remaining':analysis['remaining'],'analysis_only':True,'complete':analysis['state']=='WARMUP COMPLETE','data_stale':analysis['freshness']=='DATA STALE' or bool(current.get('last_data_at') and current.get('data_stale')),'data_missing':not current.get('last_data_at'),'data_error':bool(current.get('last_error') and current['last_error']!='DATA_STALE'),'market_status_unknown':quality.get('market_status')=='UNKNOWN' and not regular_closed,'regular_closed':regular_closed}
 return {'auto_status':dict(auto) if auto else None,'candidate_id':candidate_id,'trade_cycle_id':cycle,'lifecycle':dict(lifecycle) if lifecycle else None,'session':({'watch_id':current['watch_id'],'status':current['status'],'last_data_at':current['last_data_at'],'signal':current['signal'],'display_status':current['display_status'],'last_calculation_at':current.get('last_calculation_at'),'last_action_signal':current.get('last_action_signal'),'warmup':warmup} if current else None),'link_basis':'unique_asset_and_portfolio_scope' if asset_fallback else 'candidate_id+asset_id+portfolio' if report_position and report_position.get('candidate_id') else 'asset_id+portfolio+trade_cycle_id' if candidate_id and cycle else 'unique_asset_and_portfolio_scope' if session else None}

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
    # A value-minus-cost estimate is useful if clearly distinguished from the
    # broker's reported P/L; it does not include undocumented transaction costs.
    estimated=row.get('unrealized_basis')=='calculated_value_cost' and pnl is raw_pnl
    if row.get('unrealized_basis') and pnl is raw_pnl and not estimated:pnl=None
    if pnl and policy.decimal(pnl.get('amount')) is None:pnl=None
    cost=row.get('cost_basis') or {};pnl_percent=None
    if pnl and pnl.get('currency')==cost.get('currency') and policy.decimal(cost.get('amount')) is not None and Decimal(cost['amount'])>0:pnl_percent=str(Decimal(pnl['amount'])/Decimal(cost['amount'])*100)
    # Percentage uses the original-currency broker P/L and cost when the displayed
    # DKK result has a different currency from the supplied cost basis.
    if pnl_percent is None and (not row.get('unrealized_basis') or estimated) and raw_pnl.get('currency')==cost.get('currency') and policy.decimal(raw_pnl.get('amount')) is not None and policy.decimal(cost.get('amount')) is not None and Decimal(cost['amount'])>0:
     pnl_percent=str(Decimal(raw_pnl['amount'])/Decimal(cost['amount'])*100)
    obs=observation(row,position_data.get('observed'));since=None
    if aid and obs.get('received_at') and not failed and data.get('positions_complete'):
     previous=c.execute('SELECT payload FROM display_price_observations WHERE user_id=? AND portfolio_id=? AND asset_id=? ORDER BY id DESC LIMIT 120',(uid,p['id'],aid)).fetchall()
     for old in previous:
      prior=json.loads(old['payload'])
      if policy.stamp(prior.get('received_at')) and policy.stamp(prior['received_at'])<policy.stamp(obs['received_at']):
       if obs.get('event_time') and prior.get('event_time'):
        since=policy.comparison(obs,prior)
       if since is None:since=snapshot_comparison(obs,prior)
       if since:break
    market=row.get('market_context') or {};market_state=market.get('session') if isinstance(market.get('session'),dict) else None
    daily=policy.daily_change(obs,row.get('official_close_reference'))
    reported=row.get('reported_daily')
    if daily is None and not failed and data.get('positions_complete') and isinstance(reported,dict) and reported.get('basis')=='pluto_reported_daily_change' and reported.get('source_id') in ('Pluto get_asset','Pluto positions') and reported.get('currency')==obs.get('currency') and obs.get('asset_id') and policy.decimal(reported.get('percent')) is not None and policy.decimal(obs.get('price')) is not None and policy.stamp(reported.get('to') or obs.get('received_at')):
     daily=dict(reported,to=reported.get('to') or obs['received_at'])
    price_age=policy.freshness('snapshot',row.get('price_time'),now,market_state,failed,obs.get('session_key'))
    analysis_age=policy.freshness('analysis',a.get('assessed_at'),now) if a else {'state':'unknown','reason':'NOT_PROVIDED'}
    if price_age.get('reason') in ['FUTURE_TIMESTAMP','SOURCE_ERROR']:daily=None;since=None
    action=a.get('action') if a else None
    hotwatch=position_hotwatch(c,uid,p['id'],aid,report) if aid else {'candidate_id':None,'trade_cycle_id':None,'lifecycle':None,'session':None,'link_basis':None}
    reasons={'daily':'PROVIDER_DAILY_CHANGE_NOT_PROVIDED' if daily is None else None,'since_last':'NO_COMPARABLE_PLUTO_SNAPSHOT' if since is None else None,'fx':'DKK_CONVERSION_NOT_PROVIDED' if shown.get('currency')!='DKK' else None,'assessment':'NO_EXACT_ASSET_AND_PORTFOLIO_ASSESSMENT' if not a else None,'candidate_link':'NO_VERIFIED_CANDIDATE_AND_TRADE_CYCLE_LINK' if not hotwatch['candidate_id'] else None}
    result.append({'key':identity,'portfolio_id':p['id'],'portfolio_name':p['name'],'portfolio_kind':p['kind'],'external_id':p['external_id'],'asset_id':aid,'ticker':row.get('ticker'),'name':row.get('name'),'quantity':row.get('quantity'),'price':row.get('price'),'price_time':row.get('price_time'),'value':shown,'original_value':raw_value,'cost_basis':cost,'average_entry':row.get('average_entry'),'unrealized':pnl,'unrealized_estimated':estimated and pnl is not None,'unrealized_percent':pnl_percent,'daily':daily,'since_last':since,'assessment':a,'assessment_report_id':matched[1] if matched else None,'reported_position':report,'hot_watch':hotwatch,'action':action,'critical':action in ['SÆLG','REDUCÉR'] or bool(conflicts),'price_freshness':price_age,'analysis_freshness':analysis_age,'snapshot_at':position_data.get('observed'),'verification':'last_known' if failed or not data.get('positions_complete') else 'broker_snapshot','conflicts':conflicts,'missing':reasons,'raw':row})
  try:
   sessions=[]
   for row in c.execute("SELECT watch_id,status,last_error,last_data,request FROM hw_sessions WHERE user_id=? AND is_test=0 AND status IN ('DEGRADED','ERROR')",(uid,)):
    item=dict(row);req=json.loads(item.pop('request'));item.update(ticker=req.get('ticker'),provider=req.get('provider'));sessions.append(item)
  except Exception:sessions=[]
  value_history=portfolio_value_history(c,uid,now)
 currencies={r['value'].get('currency') for r in result if r['value']}
 result.sort(key=lambda r:(not r['critical'],r['portfolio_name'].casefold(),r['value'].get('currency') or '',-(policy.decimal(r['value'].get('amount')) or Decimal(0)),r['ticker'] or ''))
 return {'policy':{'version':'1.0.0','limits':policy.LIMITS},'version':'design-1','positions':result,'count':len(result),'accounts':accounts,'totals':[{'currency':k,'amount':str(v)} for k,v in totals.items()],'portfolio_value_history':value_history,'daily_result':None,'daily_result_reason':'Pengestrømme og dokumenteret dagsreference er ikke tilgængelige','orders':orders,'warnings':warnings,'critical_sessions':sessions,'snapshot_at':max((a['snapshot_at'] for a in accounts if a['snapshot_at']),default=None),'mixed_value_currencies':len(currencies)>1}


def engine_session_view(connect,uid,mode,group,limit=100,before=None):
 """UI-only read projection; never calls claim/control or edits scheduling."""
 import hotwatch_engine as engine
 result=engine.sessions(connect,uid,mode,limit=1)
 where="status IN ('EXPIRED','COMPLETED')" if group=='history' else "status NOT IN ('EXPIRED','COMPLETED')"
 order="id DESC" if group=='history' else "CASE WHEN status='ERROR' THEN 1 ELSE 0 END,id DESC"
 with connect() as c:
  bound=' AND id<?' if before and group=='history' else '';args=[uid,int(mode)]+([before] if bound else [])+[limit+1]
  rows=c.execute('SELECT * FROM hw_sessions WHERE user_id=? AND is_test=? AND '+where+bound+' ORDER BY '+order+' LIMIT ?',args).fetchall()
  result['sessions']=[dict(engine.view(c,r),display_freshness=policy.freshness('live_quote',r['last_data'])) for r in rows[:limit]]
 result['next_cursor']=rows[limit-1]['id'] if group=='history' and len(rows)>limit else None;result['view']=group;result['truncated']=len(rows)>limit;result['shown_limit']=limit
 return result
