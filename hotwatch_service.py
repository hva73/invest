"""Standalone read-only HOT WATCH service. Never scheduled by legacy worker.py."""
from eodhd_capacity import Capacity
import json,signal,threading,logging,hashlib,time,os,re,secrets,sqlite3,sys
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from contextlib import contextmanager
import app,hotwatch_engine as engine
from hotwatch_adapters import PlutoAdapter,EODHDAdapter,InboxAdapter,DataUnavailable
from hotwatch_contract import EngineError,stamp
from cxe_reference import ReferenceUnavailable as CXEReferenceUnavailable
from eodhd_us_reference import ReferenceUnavailable as USReferenceUnavailable

HEARTBEAT_INTERVAL_S=5

def serialized_database(connect):
 """Serialize this worker's short DB scopes, not its provider/network calls.

 SQLite still arbitrates other processes. Sharing this wrapper with child
 runners keeps their reads from blocking another worker thread's commit.
 """
 if getattr(connect,'_hotwatch_serialized',False) is True:return connect
 gate=threading.RLock()
 metrics={'scope':'worker_process','completed_scopes':0,'max_wait_ms':0,'max_scope_ms':0,'slowest_module':None,'slowest_function':None}
 @contextmanager
 def scoped():
  requested=time.perf_counter()
  caller=sys._getframe(2).f_code
  module=os.path.basename(caller.co_filename).removesuffix('.py')
  known={'hotwatch_service','hotwatch_engine','hotwatch_adapters','hotwatch_warmup','oauth','mcp_client','portfolio_data','sector_intelligence','web_push'}
  location=(module,caller.co_name) if module in known and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,79}',caller.co_name) else ('other','other')
  with gate:
   acquired=time.perf_counter()
   metrics['max_wait_ms']=max(metrics['max_wait_ms'],round((acquired-requested)*1000,3))
   try:
    with connect() as connection:yield connection
   finally:
    elapsed=round((time.perf_counter()-acquired)*1000,3)
    metrics['completed_scopes']+=1
    if elapsed>=metrics['max_scope_ms']:
     metrics.update(max_scope_ms=elapsed,slowest_module=location[0],slowest_function=location[1])
 def database_metrics():
  with gate:return dict(metrics)
 scoped._hotwatch_serialized=True
 scoped.database_metrics=database_metrics
 return scoped

def reference_error_code(error):
 if isinstance(error,(CXEReferenceUnavailable,USReferenceUnavailable)):
  code=str(error)
 elif isinstance(error,EngineError):code=getattr(error,'code',None)
 elif isinstance(error,sqlite3.OperationalError):
  sqlcode=getattr(error,'sqlite_errorcode',None)
  code='REFERENCE_DATABASE_BUSY' if isinstance(sqlcode,int) and (sqlcode&255) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else 'REFERENCE_DATABASE_ERROR'
 elif isinstance(error,KeyError):code='REFERENCE_FIELD_MISSING'
 elif isinstance(error,TypeError):code='REFERENCE_TYPE_ERROR'
 elif isinstance(error,ValueError):code='REFERENCE_VALUE_ERROR'
 else:code=None
 return code if isinstance(code,str) and re.fullmatch('[A-Za-z0-9_]{1,80}',code) else 'VERIFICATION_FAILED'

def processing_error_code(error):
 """Safe per-session diagnosis; never persist exception messages or values."""
 if isinstance(error,sqlite3.OperationalError):
  code=getattr(error,'sqlite_errorcode',None)
  kind='DATABASE_BUSY' if isinstance(code,int) and (code&255) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else 'DATABASE_ERROR'
 elif isinstance(error,sqlite3.IntegrityError):kind='DATABASE_INTEGRITY'
 elif isinstance(error,KeyError):kind='FIELD_MISSING'
 elif isinstance(error,TypeError):kind='TYPE_ERROR'
 elif isinstance(error,ValueError):kind='VALUE_ERROR'
 elif isinstance(error,OSError):kind='IO_ERROR'
 else:kind='ERROR'
 names={'hotwatch_service.py':'SERVICE','hotwatch_engine.py':'ENGINE','hotwatch_adapters.py':'ADAPTER','eodhd_feeds.py':'EODHD','app.py':'APP'}
 location='OTHER';line=0;tb=error.__traceback__
 while tb:
  name=os.path.basename(tb.tb_frame.f_code.co_filename)
  wrapper=name=='app.py' and tb.tb_frame.f_code.co_name in ('execute','executemany','executescript','cursor','__exit__','close')
  wrapper=wrapper or name=='hotwatch_service.py' and tb.tb_frame.f_code.co_name=='scoped'
  if name in names and not wrapper:location=names[name];line=tb.tb_lineno
  tb=tb.tb_next
 return f'PROCESSING_{kind}_{location}_{line}'

def pluto_isin(*nodes):
 """Read only explicitly named ISIN fields; reject malformed or conflicting values."""
 values=[]
 def add(value):
  if isinstance(value,str) and value:values.append(value)
 for node in nodes:
  if not isinstance(node,dict):continue
  for key in ('isin','ISIN','isinCode'):add(node.get(key))
  nested=node.get('identifiers')
  if isinstance(nested,dict):
   for key in ('isin','ISIN','isinCode'):add(nested.get(key))
  elif isinstance(nested,list):
   for item in nested:
    if isinstance(item,dict) and str(item.get('type') or item.get('scheme') or '').upper()=='ISIN':add(item.get('value'))
 if not values:return None,False
 if any(not re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',value) for value in values) or len(set(values))!=1:return None,True
 return values[0],False

def verified_discovery_instrument(connect,uid,candidate,adapter=None):
 """Verify a reported stable asset with Pluto's read-only get_asset tool."""
 import trade_service
 adapter=adapter or PlutoAdapter(connect,uid,purpose='candidate_identity');client,tools=trade_service.client(connect,uid,adapter.factory)
 found=trade_service.call(client,tools,'search_assets',{'query':candidate['ticker'],'limit':10,'assetType':'ALL'})
 if isinstance(found,list):matches=found
 elif isinstance(found,dict):
  lists=[found[k] for k in ('assets','results','items') if isinstance(found.get(k),list)];matches=lists[0] if len(lists)==1 else []
 else:matches=[]
 exact=[x for x in matches if isinstance(x,dict) and (x.get('id') or x.get('assetId'))==candidate['asset_id'] and str(x.get('ticker','')).casefold()==candidate['ticker'].casefold()]
 if len(exact)!=1:return None
 match=exact[0]
 if any(x!=candidate['asset_id'] for x in (match.get('id'),match.get('assetId')) if x is not None):return None
 raw=trade_service.call(client,tools,'get_asset',{'assetId':candidate['asset_id']})
 if not isinstance(raw,dict):return None
 asset=raw['asset'] if isinstance(raw.get('asset'),dict) else raw
 ids=[x for x in (asset.get('id'),asset.get('assetId'),raw.get('assetId')) if x is not None]
 if not ids or any(x!=candidate['asset_id'] for x in ids):return None
 if asset.get('ticker') and str(asset['ticker']).casefold()!=candidate['ticker'].casefold():return None
 def consistent(key):
  values=[x for x in (asset.get(key),raw.get(key),match.get(key)) if isinstance(x,str) and x]
  return values[0] if values and all(x.casefold()==values[0].casefold() for x in values) else None
 currency=consistent('currency');isin,isin_conflict=pluto_isin(asset,raw,match);exchange=consistent('exchange')
 if isin_conflict:return None
 if candidate.get('exchange') and (not exchange or exchange.casefold()!=candidate['exchange'].casefold()):return None
 if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency) or not isinstance(exchange,str) or not exchange:return None
 if not isinstance(isin,str) or not re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',isin):isin=None
 name=asset.get('name') or raw.get('name') or match.get('name')
 instrument_type=consistent('type')
 return {'asset_id':candidate['asset_id'],'ticker':candidate['ticker'],'exchange':exchange,'currency':currency,'isin':isin,'name':name if isinstance(name,str) else None,'type':instrument_type}

def verify_requested_instruments(connect,uid,requests):
 """Require Pluto search and asset verification for each real activation."""
 verified={}
 for req in requests:
  if req.get('is_test') is not False:continue
  with connect() as c:existing=c.execute('SELECT digest FROM hw_sessions WHERE user_id=? AND watch_id=?',(uid,req.get('watch_id'))).fetchone()
  if existing and existing['digest']==engine.checksum(req):continue
  key=(req.get('asset_id'),req.get('ticker'),req.get('exchange'),req.get('quote_currency'))
  if key not in verified:
   try:instrument=verified_discovery_instrument(connect,uid,{'asset_id':key[0],'ticker':key[1],'exchange':key[2]})
   except Exception:instrument=None
   if not instrument or instrument.get('asset_id')!=key[0] or str(instrument.get('ticker','')).casefold()!=str(key[1]).casefold() or str(instrument.get('exchange','')).casefold()!=str(key[2]).casefold() or instrument.get('currency')!=key[3]:raise EngineError('pluto_identity_unverified',409)
   verified[key]=instrument

def start_manual_pluto(connect,uid,data):
 """Start an explicit watch for a selected Pluto asset, without a report."""
 import trade_service
 if set(data)!={'asset_id','ticker'} or not isinstance(data['asset_id'],str) or not isinstance(data['ticker'],str) or not data['asset_id'] or not data['ticker']:raise EngineError('invalid_input')
 try:
  adapter=PlutoAdapter(connect,uid);client,tools=trade_service.client(connect,uid,adapter.factory)
  found=trade_service.call(client,tools,'search_assets',{'query':data['ticker'],'limit':10,'assetType':'ALL'})
  if isinstance(found,list):rows=found
  elif isinstance(found,dict):
   lists=[found[k] for k in ('assets','results','items') if isinstance(found.get(k),list)];rows=lists[0] if len(lists)==1 else []
  else:rows=[]
  if not any(isinstance(x,dict) and (x.get('id') or x.get('assetId'))==data['asset_id'] and str(x.get('ticker','')).casefold()==data['ticker'].casefold() for x in rows):raise EngineError('pluto_identity_unverified',409)
  raw=trade_service.call(client,tools,'get_asset',{'assetId':data['asset_id']});asset=raw.get('asset') if isinstance(raw,dict) else None
  if not isinstance(asset,dict) or asset.get('id')!=data['asset_id'] or str(asset.get('ticker','')).casefold()!=data['ticker'].casefold() or not isinstance(asset.get('exchange'),str) or not asset['exchange'] or not isinstance(asset.get('currency'),str) or not re.fullmatch('[A-Z]{3}',asset['currency']):raise EngineError('pluto_identity_unverified',409)
 except EngineError:raise
 except Exception:raise EngineError('pluto_identity_unverified',409) from None
 provider='pluto';symbol=None
 if asset.get('isin') and os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')=='1' and os.environ.get('ESCAPE_EODHD_API_KEY'):
  try:
   from hotwatch_adapters import search_eodhd_symbols
   options=search_eodhd_symbols(connect,uid,{'quote_currency':asset['currency']},candidate_override={'ticker':asset['ticker'],'company_name':asset.get('name')})
   matches=[x for x in options.get('choices',[]) if x.get('isin')==asset['isin'] and x.get('currency')==asset['currency']]
   if len(matches)==1:provider='eodhd';symbol=matches[0]['symbol']
  except Exception:pass
 cid='manual-'+hashlib.sha256((str(uid)+'|'+data['asset_id']).encode()).hexdigest()[:28]
 risk={'max_notional_dkk':'1000','max_loss_dkk':'100','max_spread_pct':'1','max_quote_age_s':120,'max_position_fraction_pct':'20','proposed_quantity':None,'stop_price':None,'exit_deadline':None}
 req={'watch_id':'hw-manual-'+secrets.token_hex(12),'report_id':'manual-pluto','candidate_id':cid,'is_test':False,'purpose':'manual pluto','ticker':asset['ticker'],'exchange':asset['exchange'],'asset_id':asset['id'],'quote_currency':asset['currency'],'portfolio_ids':[],'priority':'NORMAL','profile':'NORMAL','provider':provider,'provider_symbol':symbol,'end_at':None,'activation_reason':'Manuelt valgt Pluto-instrument','reactivation_reason':'Manuelt genvalgt Pluto-instrument','strategy_id':'escape_momentum','strategy_version':'1.0.0','risk':risk,'watch_mode':'entry'}
 import strategy_center
 selected=strategy_center.resolve(connect,uid);req.update(strategy_id=selected['strategy_id'],strategy_version=selected['version'],activation_reason=req['activation_reason']+' · '+selected['reason'])
 return engine.create_manual(connect,uid,req)

def pending_holding_slots(c,uid,now):
 """Count fresh known holdings still waiting for a protected session slot."""
 from decimal import Decimal,InvalidOperation
 rows=c.execute("SELECT p.id,s.payload FROM portfolios p JOIN portfolio_snapshots s ON s.portfolio_id=p.id AND s.user_id=p.user_id WHERE p.user_id=? AND p.active=1 AND p.source='pluto' AND s.last_error IS NULL",(uid,)).fetchall()
 pending=set()
 for snapshot in rows:
  try:
   payload=json.loads(snapshot['payload']);age=(now-stamp(payload['observed'])).total_seconds()
   if not payload.get('positions_complete') or not 0<=age<=300:continue
  except (ValueError,TypeError,KeyError,AttributeError):continue
  for holding in payload.get('positions',[]):
   try:
    asset=holding.get('asset_id')
    if holding.get('kind')!='holding' or not isinstance(asset,str) or not asset or Decimal(str(holding.get('quantity')))<=0:continue
   except (InvalidOperation,TypeError,ValueError,AttributeError):continue
   sessions=c.execute("SELECT request FROM hw_sessions WHERE user_id=? AND is_test=0 AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') AND json_extract(request,'$.asset_id')=?",(uid,asset)).fetchall()
   covered=False
   for session in sessions:
    req=json.loads(session['request']);scope=req.get('portfolio_ids') or []
    if req.get('watch_mode','both')!='entry' and (not scope or snapshot['id'] in scope):covered=True;break
   if covered:continue
   prior=c.execute('SELECT status FROM hw_holding_autowatch WHERE user_id=? AND portfolio_id=? AND asset_id=?',(uid,snapshot['id'],asset)).fetchone()
   if not prior or prior['status'] in ('VERIFYING','CAPACITY_LIMIT','PROVIDER_RATE_BUDGET'):pending.add((snapshot['id'],asset))
 return len(pending)

def auto_activate_candidate(connect,uid,mode,report,candidate,verify=None,lookup=None):
 """Start only a new, uniquely matched candidate; no order or purchase plan."""
 import candidate_lifecycle
 cid=candidate.get('candidate_id');asset=candidate.get('asset_id')
 if not cid:return {'status':'IDENTITY_OR_DECISION_UNAVAILABLE'}
 proposal=candidate.get('strategy_proposal')
 if proposal:
  import strategy_center
  with connect() as c:qualified=strategy_center.qualification(c,uid,proposal)
  if qualified not in ('QUALIFIED','PILOT'):return {'status':'STRATEGY_'+qualified}
 if (candidate.get('decision') or {}).get('status')=='FRAVÆLG':return {'status':'REJECTED'}
 with connect() as c:
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return {'status':'operator_kill_switch'}
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
  if killed and killed['killed']:return {'status':'kill_switch_active'}
  latest=candidate_lifecycle.latest(c,uid,mode,cid)
  if latest and latest['status'] in ('CLOSED','ARCHIVED'):return {'status':'NOT_NEW'}
  existing_cycle=latest['cycle_id'] if latest else None
  if c.execute("SELECT 1 FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') AND COALESCE(json_extract(request,'$.watch_mode'),'both')!='exit'",(uid,int(mode),cid)).fetchone():return {'status':'ALREADY_ACTIVE'}
  reset=c.execute('SELECT reset_at,generation FROM hw_discovery_resets WHERE user_id=?',(uid,)).fetchone() if not mode else None
  radar_reset=c.execute('SELECT report_cutoff,reset_at FROM radar_resets WHERE user_id=?',(uid,)).fetchone() if not mode else None
  if radar_reset and c.execute('SELECT 1 FROM report_candidate_links WHERE user_id=? AND is_test=0 AND candidate_id=? AND report_row_id<=? LIMIT 1',(uid,cid,radar_reset['report_cutoff'])).fetchone():
   from intel_workflows import radar_reassessed_after_reset
   if not radar_reassessed_after_reset(c,uid,cid,radar_reset):return {'status':'NOT_NEW'}
  terminal=c.execute("SELECT s.id,EXISTS(SELECT 1 FROM hw_events e WHERE e.watch_row_id=s.id AND e.event_type='WATCH_RESET') AS reset_event FROM hw_sessions s WHERE s.user_id=? AND s.is_test=? AND s.candidate_id=? AND s.status IN ('COMPLETED','EXPIRED','ERROR') AND COALESCE(json_extract(s.request,'$.watch_mode'),'both')!='exit'",(uid,int(mode),cid)).fetchall()
  from intel_workflows import candidate_currentness
  current=candidate_currentness(c,uid,mode,cid,report_fallback=True)
  if current['status'] not in ('CURRENT','REPORT_ONLY'):return {'status':'NOT_NEW'}
  # A fresh, explicit assessment may start a new entry watch after automatic
  # candidate expiry. Never revive manual stops or report-only observations.
  reassessed=[];released=[]
  for ended in terminal:
   last=c.execute('SELECT event_type,created FROM hw_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(ended['id'],)).fetchone()
   if not last:return {'status':'NOT_NEW'}
   if last['event_type']=='CAPACITY_RELEASED':released.append(ended['id']);continue
   if reset and ended['reset_event']:continue
   if last['event_type']!='CANDIDATE_WATCH_EXPIRED' or current['status']!='CURRENT' or not current.get('assessed_at') or stamp(current['assessed_at'])<=stamp(last['created']):return {'status':'NOT_NEW'}
   reassessed.append(ended['id'])
  reassess_generation=max(reassessed,default=0)
  latest_release=max(released,default=0)
  release_generation=latest_release if latest_release>reassess_generation else 0
  if current['status']=='REPORT_ONLY' and (engine.utc()-stamp(current['report_seen_at'])).total_seconds()>86400:return {'status':'NOT_NEW'}
  if reset and (not current.get('assessed_at') or stamp(current['assessed_at'])<=stamp(reset['reset_at']) or stamp(report['generated_at'])<=stamp(reset['reset_at'])):return {'status':'NOT_NEW'}
  if reset:
   pending=pending_holding_slots(c,uid,engine.utc())
   opened=c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]
   if pending and opened>=max(0,engine.capacity()-pending):return {'status':'HOLDINGS_PRIORITY'}
  if c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]>=engine.capacity():return {'status':'global_capacity_limit'}
  prior={row['asset'] for row in c.execute("SELECT json_extract(request,'$.asset_id') AS asset FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=?",(uid,int(mode),cid)) if row['asset']}
  link=c.execute('SELECT asset_id FROM market_asset_links WHERE user_id=? AND candidate_id=?',(uid,cid)).fetchone()
  if link:prior.add(link['asset_id'])
  if asset and prior and prior!={asset}:return {'status':'IDENTITY_CONFLICT'}
 # Reopen the actual released session, not a new one: its samples, strategy,
 # trade cycle and journal remain attached. Recheck everything under the lock.
 if release_generation:
  with connect() as c:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute("SELECT * FROM hw_sessions WHERE id=? AND user_id=? AND is_test=? AND candidate_id=? AND status='EXPIRED'",(release_generation,uid,int(mode),cid)).fetchone()
   if not row:return {'status':'CAPACITY_SESSION_CHANGED'}
   latest_event=c.execute('SELECT event_type FROM hw_events WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
   if not latest_event or latest_event['event_type']!='CAPACITY_RELEASED':return {'status':'NOT_NEW'}
   current_reset=c.execute('SELECT reset_at,generation FROM hw_discovery_resets WHERE user_id=?',(uid,)).fetchone() if not mode else None
   current_radar=c.execute('SELECT report_cutoff,reset_at FROM radar_resets WHERE user_id=?',(uid,)).fetchone() if not mode else None
   if (dict(current_reset) if current_reset else None)!=(dict(reset) if reset else None) or (dict(current_radar) if current_radar else None)!=(dict(radar_reset) if radar_reset else None):return {'status':'NOT_NEW'}
   if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0] or c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone() and c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()[0]:return {'status':'kill_switch_active'}
   opened=c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]
   if opened>=engine.capacity():return {'status':'global_capacity_limit'}
   pending=pending_holding_slots(c,uid,engine.utc()) if not mode else 0
   if pending and opened>=max(0,engine.capacity()-pending):return {'status':'HOLDINGS_PRIORITY'}
   from intel_workflows import candidate_currentness
   current=candidate_currentness(c,uid,mode,cid,report_fallback=True)
   if current['status'] not in ('CURRENT','REPORT_ONLY') or current['status']=='REPORT_ONLY' and (engine.utc()-stamp(current['report_seen_at'])).total_seconds()>86400:return {'status':'NOT_NEW'}
   req=json.loads(row['request'])
   expected=asset or (next(iter(prior)) if len(prior)==1 else None)
   if not expected or req.get('watch_mode')!='entry' or req.get('purpose')!='automatic discovery' or req.get('asset_id')!=expected:return {'status':'IDENTITY_CONFLICT'}
   state=json.loads(row['state']);state.update(signal='NO_DATA',pending=None,confirmations=0)
   now=engine.utc();c.execute("UPDATE hw_sessions SET status='VALIDATING',state=?,updated=?,next_due=?,lease_owner=NULL,lease_until=0,revision=revision+1 WHERE id=?",(json.dumps(state),now.isoformat(),now.timestamp(),row['id']))
   engine.event(c,row,'CAPACITY_RESTORED',now,'Kandidatovervågning genoptaget med bevaret historik og strategi')
   return {'status':'VALIDATING','watch_id':row['watch_id']}
 try:
  adapter=PlutoAdapter(connect,uid,purpose='candidate_identity') if verify is None else None
  if not asset:
   import trade_service
   options=trade_service.search(connect,uid,candidate.get('ticker',''),factory=adapter.factory if adapter else None).get('assets',[])
   exact=[x for x in options if str(x.get('ticker','')).casefold()==str(candidate.get('ticker','')).casefold()]
   if len(exact)!=1:return {'status':'PLUTO_IDENTITY_UNCERTAIN'}
   asset=exact[0]['asset_id'];candidate=dict(candidate,asset_id=asset)
   if prior and prior!={asset}:return {'status':'IDENTITY_CONFLICT'}
  with connect() as c:
   other=c.execute("SELECT watch_id,request FROM hw_sessions WHERE user_id=? AND is_test=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED') AND json_extract(request,'$.asset_id')=?",(uid,int(mode),asset)).fetchall()
   existing=next((r for r in other if json.loads(r['request']).get('watch_mode','both')!='exit'),None)
   if existing:return {'status':'ALREADY_ACTIVE','watch_id':existing['watch_id']}
   stopped=c.execute("SELECT s.request FROM hw_sessions s JOIN hw_events e ON e.watch_row_id=s.id AND e.event_type='WATCH_COMPLETED' WHERE s.user_id=? AND s.is_test=? AND json_extract(s.request,'$.asset_id')=?",(uid,int(mode),asset)).fetchall()
   if any(json.loads(r['request']).get('watch_mode','both')!='exit' for r in stopped):return {'status':'NOT_NEW'}
  instrument=verify(connect,uid,candidate) if verify else verified_discovery_instrument(connect,uid,candidate,adapter=adapter)
  if not instrument or instrument.get('asset_id')!=asset or str(instrument.get('ticker','')).casefold()!=candidate.get('ticker','').casefold():return {'status':'PLUTO_VERIFICATION_REQUIRED'}
  # Session creation must not wait for market-data search or its rate budget.
  # Reuse only a still-valid verified identity; background feed recovery will
  # perform independent matching after creation when no proof is cached.
  cached=verified_existing_feed(connect,uid,instrument) if not mode else None
  provider='eodhd' if cached else 'pluto';symbol=cached['provider_symbol'] if cached else None
  watch='hw-auto-'+hashlib.sha256((str(uid)+'|'+str(int(mode))+'|'+cid+('|'+reset['generation'] if reset else '')+('|capacity:'+str(release_generation) if release_generation else '')+('|reassessment:'+str(reassess_generation) if reassess_generation else '')).encode()).hexdigest()[:28]
  risk={'max_notional_dkk':'1000','max_loss_dkk':'100','max_spread_pct':'1','max_quote_age_s':120,'max_position_fraction_pct':'20','proposed_quantity':None,'stop_price':None,'exit_deadline':None}
  with connect() as c:portfolios=[dict(p) for p in c.execute("SELECT id,external_id,parent_external_id FROM portfolios WHERE user_id=? AND active=1 AND source='pluto' ORDER BY id",(uid,))]
  overlapping=any(a['external_id']==b.get('parent_external_id') for a in portfolios for b in portfolios)
  portfolio_ids=[p['id'] for p in portfolios] if len(portfolios)<=30 and not overlapping else []
  req={'watch_id':watch,'report_id':report['report_id'],'candidate_id':cid,'is_test':mode,'purpose':'automatic discovery','ticker':candidate['ticker'],'exchange':instrument['exchange'],'asset_id':asset,'quote_currency':instrument['currency'],'portfolio_ids':portfolio_ids,'priority':'NORMAL','profile':'NORMAL','provider':provider,'provider_symbol':symbol,'end_at':None,'activation_reason':'Automatisk overvågning efter verificeret Pluto-aktiv og handelsbarhed','strategy_id':'escape_momentum','strategy_version':'1.0.0','risk':risk,'watch_mode':'entry'}
  import strategy_center
  selected={'strategy_id':proposal['strategy_id'],'version':proposal['version'],'reason':'Strategiforslag fra rapport: '+proposal['reason']} if proposal else strategy_center.resolve(connect,uid)
  req.update(strategy_id=selected['strategy_id'],strategy_version=selected['version'],activation_reason=(req['activation_reason']+' · '+selected['reason'])[:4000])
  if existing_cycle:req['trade_cycle_id']=existing_cycle
  result=engine.create(connect,uid,req);return {'status':result['session']['status'] if not result['duplicate'] else 'ALREADY_ACTIVE','watch_id':watch}
 except EngineError as error:return {'status':error.code}
 except Exception:return {'status':'DISCOVERY_VERIFICATION_FAILED'}

# Select the latest eligible link once per distinct candidate. The former
# anti-join repeated the history search for every historical link, holding a
# read scope for seconds as report history grew.
DISCOVERY_CANDIDATES_SQL = """WITH candidate_ids AS (SELECT DISTINCT candidate_id FROM report_candidate_links WHERE user_id=? AND is_test=0)
SELECT l.candidate_id,l.generated,r.id,r.received,r.payload
FROM candidate_ids ids
JOIN report_candidate_links l ON l.rowid=(
 SELECT newer.rowid FROM report_candidate_links newer JOIN ingested_reports nr ON nr.id=newer.report_row_id
 WHERE newer.user_id=? AND newer.is_test=0 AND newer.candidate_id=ids.candidate_id AND nr.report_type!='deep_analysis' AND newer.generated<=?
 ORDER BY newer.generated DESC,newer.report_row_id DESC LIMIT 1)
JOIN ingested_reports r ON r.id=l.report_row_id
ORDER BY l.generated DESC,r.id DESC"""

def discovery_candidate_order(rows, report_cache=None):
 """Sort candidates within each report after releasing the database read scope."""
 if report_cache is None:report_cache={}
 cache={}
 def position(row):
  if row['id'] not in cache:
   if row['id'] not in report_cache:report_cache[row['id']]=json.loads(row['payload'])
   candidates=report_cache[row['id']].get('candidates',[])
   positions={}
   for i,item in enumerate(candidates):
    if isinstance(item,dict):positions.setdefault(item.get('candidate_id'),i)
   cache[row['id']]=positions
  index=cache[row['id']].get(row['candidate_id'])
  return (index is not None,index if index is not None else 0)
 # SQL already ordered the report groups; sorting within each group preserves
 # its NULL-first candidate order without repeatedly parsing JSON in SQLite.
 from itertools import groupby
 return [row for _,group in groupby(rows,key=lambda r:(r['generated'],r['id'])) for row in sorted(group,key=position)]

def auto_discover(connect,cursor=0):
 """Optional worker path, bounded by existing capacity and provider budgets."""
 if os.environ.get('ESCAPE_HW_AUTOSTART_ENABLED','1')!='1':return cursor
 configured=os.environ.get('ESCAPE_HW_AUTOSTART_AFTER')
 try:
  if configured:after=stamp(configured)
  else:after=None
 except (ValueError,TypeError):return cursor
 with connect() as c:users=[row['id'] for row in c.execute('SELECT id FROM users WHERE active=1')]
 for uid in users:
  now=engine.utc()
  with connect() as c:
   started=c.execute('SELECT started_at FROM hw_discovery_control WHERE id=1').fetchone()
   latest_report=c.execute("SELECT id FROM ingested_reports WHERE user_id=? AND is_test=0 AND report_type!='deep_analysis' ORDER BY generated_epoch DESC,id DESC LIMIT 1",(uid,)).fetchone()
   radar_reset=c.execute('SELECT report_cutoff,reset_at FROM radar_resets WHERE user_id=?',(uid,)).fetchone()
   cleared={r[0] for r in c.execute('SELECT DISTINCT candidate_id FROM report_candidate_links WHERE user_id=? AND is_test=0 AND report_row_id<=?',(uid,radar_reset['report_cutoff']))} if radar_reset else set()
   rows=c.execute(DISCOVERY_CANDIDATES_SQL,(uid,uid,now.timestamp())).fetchall()
  if rows:
   report_cache={};rows=discovery_candidate_order(rows,report_cache)
   candidate=None;report=None
   with connect() as c:
    for offset in range(len(rows)):
     row=rows[(cursor+offset)%len(rows)]
     if after and stamp(row['received'])<=after:continue
     current=report_cache[row['id']];cid=row['candidate_id']
     if cid in cleared:
      from intel_workflows import radar_reassessed_after_reset
      if not radar_reassessed_after_reset(c,uid,cid,radar_reset):continue
     item=next((v for v in current.get('candidates',[]) if v.get('candidate_id')==cid),None)
     if not item:continue
     old=c.execute('SELECT report_id,next_attempt FROM hw_discovery_attempts WHERE user_id=? AND is_test=0 AND candidate_id=?',(uid,cid)).fetchone()
     if not after and started and stamp(row['received'])<stamp(started['started_at']) and (not latest_report or row['id']!=latest_report['id']) and not old:continue
     if not old or old['report_id']!=current['report_id'] or old['next_attempt']<=now.timestamp():candidate=item;report=current;cursor+=offset;break
   if candidate is None:continue
   result=auto_activate_candidate(connect,uid,False,report,candidate)
   with connect() as c:c.execute('INSERT INTO hw_discovery_attempts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,is_test,candidate_id) DO UPDATE SET report_id=excluded.report_id,status=excluded.status,updated=excluded.updated,next_attempt=excluded.next_attempt,watch_id=excluded.watch_id',(uid,0,candidate['candidate_id'],report['report_id'],result['status'],engine.utc().isoformat(),engine.utc().timestamp()+(300 if result['status'] in ('ALREADY_ACTIVE','NOT_NEW','CREATED') else 60),result.get('watch_id')))
   if result['status'] not in ('NOT_NEW','ALREADY_ACTIVE'):
    logging.getLogger('escape.hotwatch').info(json.dumps({'service':'hotwatch','event':'discovery','candidate_ref':hashlib.sha256(str(candidate.get('candidate_id','')).encode()).hexdigest()[:16],'status':result['status']}))
 return cursor+1

def holding_instrument(connect,uid,holding,diagnostic=None):
 """Resolve the actual owned asset using Pluto's read-only identity endpoint."""
 import trade_service
 def invalid(code):
  if diagnostic is not None:diagnostic['code']=code
  return None
 adapter=PlutoAdapter(connect,uid,purpose='holding_identity');client,tools=trade_service.client(connect,uid,adapter.factory)
 raw=trade_service.call(client,tools,'get_asset',{'assetId':holding['asset_id']})
 if not isinstance(raw,dict):return invalid('PLUTO_ASSET_METADATA_MISSING')
 asset=raw.get('asset') if isinstance(raw.get('asset'),dict) else raw
 ids=[x for x in (asset.get('id'),asset.get('assetId'),raw.get('assetId')) if x is not None]
 if not ids or any(x!=holding['asset_id'] for x in ids):return invalid('PLUTO_ASSET_ID_MISMATCH')
 asset_currency=asset.get('currency');outer_currency=raw.get('currency')
 if asset_currency and outer_currency and asset_currency!=outer_currency:return invalid('PLUTO_CURRENCY_MISMATCH')
 for field in ('ticker','exchange'):
  inner=asset.get(field);outer=raw.get(field)
  if inner and outer and str(inner).casefold()!=str(outer).casefold():return invalid('PLUTO_ASSET_METADATA_MISSING')
 isin,isin_conflict=pluto_isin(asset,raw)
 if isin_conflict:return invalid('PLUTO_ASSET_METADATA_MISSING')
 currency=asset_currency or outer_currency or holding.get('currency');exchange=asset.get('exchange') or raw.get('exchange');ticker=asset.get('ticker') or raw.get('ticker') or holding.get('ticker');name=asset.get('name') or raw.get('name')
 # A complete broker identity can be checked against the independent listing
 # reference without a second Pluto search just to look for a missing ISIN.
 # Keep searching when other identity fields are missing or the reference
 # resolver cannot handle this venue/type.
 kind=asset.get('type') if isinstance(asset.get('type'),str) else ''
 reference_capable=(str(exchange).upper()=='CHIX' and kind.upper()=='CS' or str(exchange).upper() in ('NYSE','NASDAQ') and kind.upper() in ('CS','ADRC'))
 if (not exchange or not ticker or not currency or not isin and not (name and reference_capable)) and holding.get('ticker'):
  try:
   from market_data import choices
   found=trade_service.call(client,tools,'search_assets',{'query':holding['ticker'],'limit':10,'assetType':'ALL'});options=choices(found)
   exact=[x for x in options if x.get('asset_id')==holding['asset_id']]
   if len(exact)==1:
    match=exact[0]
    raw_options=found if isinstance(found,list) else next((found[k] for k in ('assets','results','items') if isinstance(found,dict) and isinstance(found.get(k),list)),[])
    raw_exact=[item for item in raw_options if isinstance(item,dict) and (item.get('id') or item.get('assetId'))==holding['asset_id']]
    if len(raw_exact)!=1:return invalid('PLUTO_ASSET_METADATA_MISSING')
    search_isin,conflict=pluto_isin(raw_exact[0])
    if conflict or isin and search_isin and isin!=search_isin:return invalid('PLUTO_ASSET_METADATA_MISSING')
    if ticker and match.get('ticker') and ticker.casefold()!=match['ticker'].casefold():return invalid('PLUTO_TICKER_MISMATCH')
    if currency and match.get('currency') and currency!=match['currency']:return invalid('PLUTO_CURRENCY_MISMATCH')
    if isin and match.get('isin') and isin!=match['isin']:return invalid('PLUTO_ASSET_ID_MISMATCH')
    ticker=ticker or match.get('ticker');currency=currency or match.get('currency');exchange=exchange or match.get('exchange');isin=isin or search_isin;name=name or (match.get('name') if match.get('name')!=holding['asset_id'] else None)
  except Exception:pass
 if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):return invalid('PLUTO_CURRENCY_MISSING')
 if not isinstance(ticker,str) or not ticker:return invalid('PLUTO_TICKER_MISSING')
 if holding.get('currency') and holding['currency']!=currency:return invalid('PLUTO_CURRENCY_MISMATCH')
 if holding.get('ticker') and str(holding['ticker']).casefold()!=ticker.casefold():return invalid('PLUTO_TICKER_MISMATCH')
 if not isinstance(isin,str) or not re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',isin):isin=None
 instrument_type=asset.get('type') if isinstance(asset.get('type'),str) else None
 return {'asset_id':holding['asset_id'],'ticker':ticker,'exchange':exchange if isinstance(exchange,str) and exchange else 'UKENDT','currency':currency,'isin':isin,'name':name if isinstance(name,str) else None,'type':instrument_type}

def verified_existing_feed(connect,uid,holding,now=None):
 """Reuse only a prior explicit ISIN-and-currency identity check."""
 aid=holding['asset_id'];now=now or engine.utc()
 with connect() as c:
  row=c.execute('SELECT * FROM hw_verified_feed_links WHERE user_id=? AND asset_id=? AND verified_epoch BETWEEN ? AND ?',(uid,aid,now.timestamp()-7*86400,now.timestamp())).fetchone()
  cxe=c.execute('SELECT * FROM hw_cxe_feed_evidence WHERE user_id=? AND asset_id=?',(uid,aid)).fetchone()
 if cxe:
  try:
   evidence=json.loads(cxe['payload'])['pluto']
   if not row or not holding.get('ticker') or not holding.get('currency') or any(holding.get(key) and str(holding[key]).casefold()!=str(evidence.get(key,'')).casefold() for key in ('ticker','name','exchange','currency','type')):return None
   request={'asset_id':aid,'ticker':holding['ticker'],'exchange':holding.get('exchange') or row['exchange'],'quote_currency':holding['currency'],'provider_symbol':row['symbol'],'watch_mode':'exit','purpose':'automatic holding watch'}
   with connect() as c:
    if not engine.valid_cxe_evidence(c,uid,request,now):return None
  except (KeyError,TypeError,ValueError):return None
 if row and (not holding.get('ticker') or str(holding['ticker']).casefold()==row['ticker'].casefold()) and (not holding.get('currency') or holding['currency']==row['currency']) and (not holding.get('exchange') or str(holding['exchange']).casefold()==str(row['exchange']).casefold()) and (not holding.get('isin') or holding['isin']==row['isin']):
  return {'asset_id':aid,'ticker':row['ticker'],'currency':row['currency'],'exchange':row['exchange'],'provider_symbol':row['symbol']}
 return None

def remember_verified_feed(connect,uid,instrument,symbol,now=None,cxe_evidence=None):
 now=now or engine.utc()
 with connect() as c:
  c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,asset_id) DO UPDATE SET ticker=excluded.ticker,currency=excluded.currency,exchange=excluded.exchange,symbol=excluded.symbol,isin=excluded.isin,verified_epoch=excluded.verified_epoch',(uid,instrument['asset_id'],instrument['ticker'],instrument['currency'],instrument['exchange'],symbol,instrument['isin'],now.timestamp()))
  if cxe_evidence:
   c.execute("INSERT INTO hw_cxe_feed_evidence VALUES(?,?,?,?,?,?,'MATCHED') ON CONFLICT(user_id,asset_id) DO UPDATE SET symbol=excluded.symbol,payload=excluded.payload,verified_epoch=excluded.verified_epoch,next_attempt=excluded.next_attempt,status=excluded.status",(uid,instrument['asset_id'],symbol,json.dumps(cxe_evidence),now.timestamp(),now.timestamp()+43200))
  else:c.execute('DELETE FROM hw_cxe_feed_evidence WHERE user_id=? AND asset_id=?',(uid,instrument['asset_id']))

def cxe_verified_match(instrument,choices,now=None,connect=None,uid=None):
 """Match against current public reference evidence and a unique EODHD listing."""
 from cxe_reference import get_reference
 from instrument_resolver import resolve_cxe,resolve_us,crypto_reference
 crypto=crypto_reference(instrument)
 if crypto and crypto['approved']:
  if connect is None or uid is None:return None
  from eodhd_feeds import EODHDFeeds
  from hotwatch_adapters import reserve
  feed=EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),capacity=Capacity(connect))
  quote=feed.snapshot(crypto['symbol'])
  if quote['status']=='LOCAL_BUDGET_EXHAUSTED':raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
  if quote['status']=='RATE_LIMIT':raise DataUnavailable('EODHD_RATE_LIMIT',429)
  if quote['status']!='OK':raise DataUnavailable('EODHD_CRYPTO_QUOTE_UNAVAILABLE')
  return {'status':'VERIFIED','basis':'user_authorized_btc_monitoring','symbol':crypto['symbol'],'isin':'','currency':crypto['currency'],'currency_basis':'explicit_BTC_USD_pair','type_note':'Brugerbekræftet BTC-kursmapping; uafhængig dokumentation for netværk mangler.','pluto':{k:instrument.get(k) for k in ('asset_id','ticker','name','exchange','currency','type')}}
 exchange=str(instrument.get('exchange','')).upper();kind=str(instrument.get('type','')).upper()
 if not (exchange=='CHIX' and kind=='CS' or exchange in ('NYSE','NASDAQ') and kind in ('CS','ADRC')):return None
 if exchange=='CHIX':
  reference=get_reference(now,connect=connect);match=resolve_cxe(instrument,choices,reference['rows']);extra={'reference_created_at':reference['created_at'],'reference_source':'https://accounteu.cboe.com/cxe/market_data/symbol_listing/csv/'}
 else:
  if connect is None or uid is None:return None
  from eodhd_us_reference import get_reference as get_us_reference
  us=get_us_reference(connect,uid);match=resolve_us(instrument,choices,us['rows']);extra={'catalog_received_at':us['received_at'],'catalog_source':'https://eodhd.com/api/exchange-symbol-list/US'}
 if match.get('status')!='VERIFIED':return None
 return {**match,**extra,'pluto':{k:instrument.get(k) for k in ('asset_id','ticker','name','exchange','currency','type')}}

def provisional_feed_match(instrument,choices):
 """Choose a unique, clearly unverified quote candidate from multiple independent fields."""
 import unicodedata
 def issuer(value):
  if not isinstance(value,str):return None
  words=re.findall(r'[a-z0-9]+',unicodedata.normalize('NFKD',value).casefold())
  while words and words[-1] in ('ltd','limited','company','inc','incorporated','corporation','corp','plc'):words.pop()
  return tuple(words) if len(words)>=2 and sum(map(len,words))>=8 else None
 def ticker(value):
  return re.sub(r'[.\-]','',value).upper() if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9.\-]{1,32}',value) else None
 name=issuer(instrument.get('name'));symbol=ticker(instrument.get('ticker'));currency=instrument.get('currency');venue=re.sub(r'[^A-Z0-9]','',str(instrument.get('exchange') or '').upper())
 markets={
  'USD':{'US':{'NYSE','NASDAQ','XNYS','XNAS','NYSEARCA','ARCX'}},
  'DKK':{'CO':{'CHIX','XCSE','CSE','COPENHAGEN','NASDAQCOPENHAGEN'}},
  'EUR':{'AS':{'CHIX','XAMS','AMS','EURONEXTAMSTERDAM'},'F':{'CHIX','XFRA','FRA','FRANKFURT'},'XETRA':{'CHIX','XETR','XETRA'},'PA':{'CHIX','XPAR','PARIS','EURONEXTPARIS'},'MI':{'CHIX','XMIL','MILAN'}},
 }
 if not name or not symbol or currency not in markets:return None
 selected=[]
 for item in choices:
  if not isinstance(item,dict):continue
  full=item.get('symbol');exchange=item.get('exchange')
  if not isinstance(full,str) or not isinstance(exchange,str) or '.' not in full:continue
  base,suffix=full.rsplit('.',1);market=exchange.upper()
  if suffix.upper()!=market or venue not in markets[currency].get(market,set()):continue
  if item.get('currency')==currency and ticker(base)==symbol and issuer(item.get('name'))==name:selected.append(item)
 return selected[0] if len(selected)==1 else None

def recover_automatic_feeds(connect,now=None):
 """Recover empty automatic sessions, labeling field-only matches as unverified."""
 from instrument_resolver import crypto_reference,CRYPTO_REFERENCES
 if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1' or not os.environ.get('ESCAPE_EODHD_API_KEY','').strip():return 0
 now=now or engine.utc();changed=0;lookup_attempted=False
 with connect() as c:
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return 0
  rows=c.execute("SELECT s.* FROM hw_sessions s LEFT JOIN hw_control k ON k.user_id=s.user_id LEFT JOIN hw_feed_recovery f ON f.watch_row_id=s.id WHERE s.is_test=0 AND COALESCE(k.killed,0)=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND s.lease_until<=? AND json_extract(s.request,'$.provider')='pluto' AND s.purpose IN ('automatic discovery','automatic holding watch') AND (NOT EXISTS (SELECT 1 FROM hw_samples p WHERE p.watch_row_id=s.id) OR (s.purpose='automatic holding watch' AND json_extract(s.request,'$.asset_id') IN (?,?))) ORDER BY COALESCE(f.next_attempt,0), CASE WHEN s.purpose='automatic holding watch' THEN 0 ELSE 1 END, s.id LIMIT ?",(now.timestamp(),*CRYPTO_REFERENCES,engine.capacity())).fetchall()
 for row in rows:
  try:
   req=json.loads(row['request']);holding={'asset_id':req['asset_id'],'ticker':req['ticker'],'currency':req['quote_currency']}
   known=verified_existing_feed(connect,row['user_id'],holding,now);reason='EODHD-match genbrugt fra en nylig kontrol af ISIN og valuta'
   if known and holding['asset_id']=='54368e0b-2d53-401e-bf68-1033a5b84b08':reason='Brugerbekræftet BTC-kursmapping genbrugt for denne beholdning'
   if not known and not lookup_attempted:
    with connect() as c:retry=c.execute('SELECT next_attempt FROM hw_feed_recovery WHERE watch_row_id=?',(row['id'],)).fetchone()
    if retry and retry['next_attempt']>now.timestamp():continue
    lookup_attempted=True;status='IDENTITY_UNVERIFIED'
    try:
     if row['purpose']=='automatic holding watch':instrument=holding_instrument(connect,row['user_id'],holding)
     else:instrument=verified_discovery_instrument(connect,row['user_id'],holding)
     if instrument and instrument.get('asset_id')==holding['asset_id'] and str(instrument.get('ticker','')).casefold()==holding['ticker'].casefold() and instrument.get('currency')==holding['currency']:
      crypto=crypto_reference(instrument) if row['purpose']=='automatic holding watch' else None
      if crypto and crypto['approved']:
       evidence=cxe_verified_match(instrument,[],now,connect,row['user_id'])
       if evidence:
        known={'provider_symbol':evidence['symbol']};status='MATCHED';reason='BTC-kurskilde godkendt af brugeren; kildetid kontrolleres for hver observation'
        remember_verified_feed(connect,row['user_id'],dict(instrument,isin=''),evidence['symbol'],now,cxe_evidence=evidence)
      elif crypto:
       evidence={'basis':'user_supplied_provisional_crypto','asset_id':instrument['asset_id'],'symbol':crypto['symbol'],'currency':crypto['currency'],'note':'Foreløbig reference; tokenidentitet er ikke verificeret og anvendes ikke til signaler.'}
       with connect() as c:
        added=c.execute('INSERT OR IGNORE INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],crypto['symbol'],json.dumps(evidence),now.isoformat()))
        if added.rowcount:engine.event(c,row,'REFERENCE_CANDIDATE_REGISTERED',now,evidence['note'])
       status='CRYPTO_IDENTITY_UNVERIFIED'
      elif not instrument.get('isin'):
       status='PLUTO_ISIN_MISSING'
       if instrument.get('name'):
        from hotwatch_adapters import search_eodhd_symbols
        options=search_eodhd_symbols(connect,row['user_id'],{'quote_currency':holding['currency']},candidate_override={'ticker':holding['ticker'],'company_name':instrument['name'],'asset_type':instrument.get('type')},purpose='holding_identity')
        evidence=cxe_verified_match(instrument,options.get('choices',[]),now,connect,row['user_id'])
        if evidence:
         known={'provider_symbol':evidence['symbol']};status='MATCHED';reason='Pluto-instrumentet er matchet til den verificerede EODHD-notering'
         remember_verified_feed(connect,row['user_id'],dict(instrument,isin=evidence['isin']),evidence['symbol'],now,cxe_evidence=evidence)
        else:status='EODHD_IDENTITY_UNCERTAIN'
      else:
       from hotwatch_adapters import search_eodhd_symbols
       options=search_eodhd_symbols(connect,row['user_id'],{'quote_currency':holding['currency']},candidate_override={'ticker':holding['ticker']},purpose='holding_identity')
       matches=[x for x in options.get('choices',[]) if x.get('isin')==instrument['isin'] and x.get('currency')==holding['currency']]
       if len(matches)==1:
        known={'provider_symbol':matches[0]['symbol']};status='MATCHED';reason='EODHD-identitet kontrolleret med samme ISIN og valuta'
        remember_verified_feed(connect,row['user_id'],instrument,matches[0]['symbol'],now)
       else:status='EODHD_IDENTITY_UNCERTAIN'
     else:status='PLUTO_IDENTITY_UNVERIFIED'
    except Exception as error:status=reference_error_code(error)
    delay=60 if status=='PROVIDER_RATE_BUDGET' else 43200 if status=='CRYPTO_IDENTITY_UNVERIFIED' else 300
    with connect() as c:c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?) ON CONFLICT(watch_row_id) DO UPDATE SET next_attempt=excluded.next_attempt,status=excluded.status,updated=excluded.updated',(row['id'],now.timestamp()+delay,status,now.isoformat()))
   if not known:continue
   updated=dict(req,provider='eodhd',provider_symbol=known['provider_symbol'])
   with connect() as c:
    c.execute('BEGIN IMMEDIATE')
    result=c.execute("UPDATE hw_sessions SET request=?,next_due=? WHERE id=? AND request=? AND lease_until<=? AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND (NOT EXISTS (SELECT 1 FROM hw_samples p WHERE p.watch_row_id=hw_sessions.id) OR (purpose='automatic holding watch' AND json_extract(request,'$.asset_id')=?)) AND NOT EXISTS (SELECT 1 FROM hw_system_control g WHERE g.id=1 AND g.killed=1) AND NOT EXISTS (SELECT 1 FROM hw_control k WHERE k.user_id=hw_sessions.user_id AND k.killed=1)",(json.dumps(updated),now.timestamp(),row['id'],row['request'],now.timestamp(),'54368e0b-2d53-401e-bf68-1033a5b84b08'))
    if result.rowcount:
     if known.get('provisional'):c.execute('INSERT INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],known['provider_symbol'],json.dumps(known['provisional']),now.isoformat()))
     engine.event(c,row,'PROVIDER_CHANGED',now,reason);changed+=1
  except (KeyError,TypeError,ValueError):continue
 return changed

def queue_unverified_automatic_feeds(connect,now=None):
 """Schedule proof for legacy EODHD sessions without deleting observations."""
 now=now or engine.utc();queued=0
 with connect() as c:
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return 0
  rows=c.execute("SELECT s.* FROM hw_sessions s LEFT JOIN hw_control k ON k.user_id=s.user_id LEFT JOIN hw_provisional_feed_links p ON p.watch_row_id=s.id WHERE s.is_test=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND s.purpose IN ('automatic discovery','automatic holding watch') AND json_extract(s.request,'$.provider')='eodhd' AND COALESCE(k.killed,0)=0 AND p.watch_row_id IS NULL ORDER BY s.id LIMIT ?",(engine.capacity(),)).fetchall()
  pending=[]
  for row in rows:
   req=json.loads(row['request']);symbol=req.get('provider_symbol')
   if not isinstance(symbol,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',symbol) or engine.verified_automatic_feed(c,row['user_id'],req,now):continue
   pending.append((row,req,symbol))
 if not pending:return 0
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return 0
  for row,req,symbol in pending:
   current=c.execute("SELECT s.* FROM hw_sessions s LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.id=? AND s.request=? AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND COALESCE(k.killed,0)=0",(row['id'],row['request'])).fetchone()
   if not current or engine.verified_automatic_feed(c,row['user_id'],req,now):continue
   evidence={'basis':'legacy_unverified_feed','asset_id':req.get('asset_id'),'symbol':symbol,'note':'Kilden afventer uafhængig instrumentkontrol; gamle observationer bevares uden handelssignal.'}
   inserted=c.execute('INSERT OR IGNORE INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],symbol,json.dumps(evidence),now.isoformat()))
   if inserted.rowcount:
    c.execute("INSERT INTO hw_feed_recovery VALUES(?,?,?,?) ON CONFLICT(watch_row_id) DO UPDATE SET next_attempt=excluded.next_attempt,status=excluded.status,updated=excluded.updated",(row['id'],now.timestamp(),'REFERENCE_RECHECK_REQUIRED',now.isoformat()))
    engine.event(c,current,'REFERENCE_CANDIDATE_REGISTERED',now,evidence['note']);queued+=1
 return queued

def verify_provisional_feeds(connect,now=None):
 """Upgrade a provisional link only after a later independent ISIN match."""
 if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1' or not os.environ.get('ESCAPE_EODHD_API_KEY','').strip():return 0
 now=now or engine.utc()
 with connect() as c:
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return 0
  row=c.execute("SELECT s.*,p.symbol AS provisional_symbol FROM hw_sessions s JOIN hw_provisional_feed_links p ON p.watch_row_id=s.id LEFT JOIN hw_feed_recovery f ON f.watch_row_id=s.id LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.is_test=0 AND COALESCE(k.killed,0)=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND s.lease_until<=? AND json_extract(s.request,'$.provider')='eodhd' AND json_extract(s.request,'$.provider_symbol')=p.symbol AND (COALESCE(f.next_attempt,0)<=? OR (f.status='PLUTO_ISIN_MISSING' AND json_extract(s.request,'$.exchange') IN ('CHIX','NYSE','NASDAQ')) OR (f.status IN ('REFERENCE_EVIDENCE_INCOMPLETE','EODHD_IDENTITY_UNCERTAIN','VERIFICATION_FAILED','CXE_REFERENCE_INVALID','CXE_REFERENCE_NOT_READY') AND f.updated<=?)) ORDER BY COALESCE(f.next_attempt,0),s.id LIMIT 1",(now.timestamp(),now.timestamp(),(now-timedelta(minutes=5)).isoformat())).fetchone()
 if not row:return 0
 req=json.loads(row['request']);holding={'asset_id':req['asset_id'],'ticker':req['ticker'],'currency':req['quote_currency']};status='PLUTO_IDENTITY_UNVERIFIED';instrument=None;evidence=None
 try:
  instrument=holding_instrument(connect,row['user_id'],holding) if row['purpose']=='automatic holding watch' else verified_discovery_instrument(connect,row['user_id'],holding)
  if instrument and instrument.get('asset_id')==holding['asset_id'] and str(instrument.get('ticker','')).casefold()==holding['ticker'].casefold() and instrument.get('currency')==holding['currency']:
   if not instrument.get('isin'):
    status='REFERENCE_EVIDENCE_INCOMPLETE' if instrument.get('exchange') in ('CHIX','NYSE','NASDAQ') else 'PLUTO_ISIN_MISSING'
    if instrument.get('name'):
     from hotwatch_adapters import search_eodhd_symbols
     options=search_eodhd_symbols(connect,row['user_id'],{'quote_currency':holding['currency']},candidate_override={'ticker':holding['ticker'],'company_name':instrument['name'],'asset_type':instrument.get('type')},purpose='holding_identity')
     evidence=cxe_verified_match(instrument,options.get('choices',[]),now,connect,row['user_id'])
     if evidence and evidence['symbol']==row['provisional_symbol']:
      instrument=dict(instrument,isin=evidence['isin']);status='MATCHED'
   else:
    from hotwatch_adapters import search_eodhd_symbols
    options=search_eodhd_symbols(connect,row['user_id'],{'quote_currency':holding['currency']},candidate_override={'ticker':holding['ticker'],'company_name':instrument.get('name')},purpose='holding_identity')
    matches=[x for x in options.get('choices',[]) if x.get('isin')==instrument['isin'] and x.get('currency')==holding['currency']]
    status='MATCHED' if len(matches)==1 and matches[0].get('symbol')==row['provisional_symbol'] else 'EODHD_IDENTITY_UNCERTAIN'
 except Exception as error:status=reference_error_code(error)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  current=c.execute("SELECT s.* FROM hw_sessions s WHERE s.id=? AND s.request=? AND s.lease_until<=? AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND NOT EXISTS (SELECT 1 FROM hw_system_control g WHERE g.id=1 AND g.killed=1) AND NOT EXISTS (SELECT 1 FROM hw_control k WHERE k.user_id=s.user_id AND k.killed=1)",(row['id'],row['request'],now.timestamp())).fetchone()
  if not current:
   # A scan may have claimed the session while the read-only identity calls
   # were running. Avoid repeatedly selecting this same due row and starving
   # other provisional instruments; never change a stopped or changed watch.
   c.execute("UPDATE hw_feed_recovery SET next_attempt=?,status='CONCURRENT_SESSION_BUSY',updated=? WHERE watch_row_id=? AND EXISTS (SELECT 1 FROM hw_sessions s WHERE s.id=? AND s.request=? AND s.lease_until>? AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED'))",(now.timestamp()+60,now.isoformat(),row['id'],row['id'],row['request'],now.timestamp()))
   return 0
  if status=='MATCHED':
   removed=c.execute('DELETE FROM hw_provisional_feed_links WHERE watch_row_id=? AND symbol=?',(row['id'],row['provisional_symbol']))
   if removed.rowcount:
    c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,asset_id) DO UPDATE SET ticker=excluded.ticker,currency=excluded.currency,exchange=excluded.exchange,symbol=excluded.symbol,isin=excluded.isin,verified_epoch=excluded.verified_epoch',(row['user_id'],instrument['asset_id'],instrument['ticker'],instrument['currency'],instrument['exchange'],row['provisional_symbol'],instrument['isin'],now.timestamp()))
    if evidence:c.execute("INSERT INTO hw_cxe_feed_evidence VALUES(?,?,?,?,?,?,'MATCHED') ON CONFLICT(user_id,asset_id) DO UPDATE SET symbol=excluded.symbol,payload=excluded.payload,verified_epoch=excluded.verified_epoch,next_attempt=excluded.next_attempt,status=excluded.status",(row['user_id'],instrument['asset_id'],row['provisional_symbol'],json.dumps(evidence),now.timestamp(),now.timestamp()+43200))
    c.execute('UPDATE hw_sessions SET next_due=? WHERE id=?',(now.timestamp(),row['id']))
    engine.event(c,current,'INSTRUMENT_VERIFIED',now,('Pluto-instrumentet er matchet til den verificerede EODHD-notering' if evidence else 'EODHD-identitet bekræftet med samme ISIN og valuta')+'; ny signalhistorik starter fra verificerede data')
   else:return 0
  delay=60 if status=='PROVIDER_RATE_BUDGET' else 300
  c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?) ON CONFLICT(watch_row_id) DO UPDATE SET next_attempt=excluded.next_attempt,status=excluded.status,updated=excluded.updated',(row['id'],now.timestamp()+delay,status,now.isoformat()))
 return 1 if status=='MATCHED' else 0

def verify_cxe_feeds(connect,now=None):
 """Recheck one cached cross-venue match without touching session history."""
 now=now or engine.utc()
 # Do not reserve a SQLite write lock on every idle verification tick.
 with connect() as preflight:
  if not preflight.execute('SELECT 1 FROM hw_cxe_feed_evidence WHERE next_attempt<=? LIMIT 1',(now.timestamp(),)).fetchone():return 0
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return 0
  row=c.execute("SELECT e.user_id,e.asset_id,e.symbol,s.purpose,s.request FROM hw_cxe_feed_evidence e JOIN hw_sessions s ON s.user_id=e.user_id AND json_extract(s.request,'$.asset_id')=e.asset_id AND json_extract(s.request,'$.provider')='eodhd' AND json_extract(s.request,'$.provider_symbol')=e.symbol LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.is_test=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND COALESCE(k.killed,0)=0 AND e.next_attempt<=? ORDER BY e.next_attempt,CASE WHEN s.purpose='automatic holding watch' THEN 0 ELSE 1 END,s.id LIMIT 1",(now.timestamp(),)).fetchone()
  if not row:return 0
  c.execute('UPDATE hw_cxe_feed_evidence SET next_attempt=? WHERE user_id=? AND asset_id=?',(now.timestamp()+300,row['user_id'],row['asset_id']))
 request=json.loads(row['request']);holding={'asset_id':row['asset_id'],'ticker':request['ticker'],'currency':request['quote_currency']};status=None;retry_code=None
 try:
  instrument=holding_instrument(connect,row['user_id'],holding) if row['purpose']=='automatic holding watch' else verified_discovery_instrument(connect,row['user_id'],holding)
  if not instrument:status='CONFLICT'
  else:
   from instrument_resolver import crypto_reference
   crypto=crypto_reference(instrument)
   if crypto and crypto['approved']:evidence=cxe_verified_match(instrument,[],now,connect,row['user_id'])
   else:
    from hotwatch_adapters import search_eodhd_symbols
    options=search_eodhd_symbols(connect,row['user_id'],{'quote_currency':holding['currency']},candidate_override={'ticker':holding['ticker'],'company_name':instrument.get('name')},purpose='holding_identity')
    evidence=cxe_verified_match(instrument,options.get('choices',[]),now,connect,row['user_id'])
   if not evidence or evidence['symbol']!=row['symbol']:status='CONFLICT'
 except Exception as error:status='RETRY';retry_code=reference_error_code(error)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return 0
  control=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(row['user_id'],)).fetchone()
  if control and control['killed']:return 0
  if status is None:
   c.execute("UPDATE hw_cxe_feed_evidence SET payload=?,verified_epoch=?,next_attempt=?,status='MATCHED' WHERE user_id=? AND asset_id=? AND symbol=?",(json.dumps(evidence),now.timestamp(),now.timestamp()+43200,row['user_id'],row['asset_id'],row['symbol']))
   c.execute('UPDATE hw_verified_feed_links SET ticker=?,currency=?,exchange=?,isin=?,verified_epoch=? WHERE user_id=? AND asset_id=? AND symbol=?',(instrument['ticker'],instrument['currency'],instrument['exchange'],evidence['isin'],now.timestamp(),row['user_id'],row['asset_id'],row['symbol']))
  elif status=='CONFLICT':c.execute("UPDATE hw_cxe_feed_evidence SET status='CONFLICT',next_attempt=?,payload=json_set(payload,'$.last_revalidation_error','IDENTITY_CONFLICT') WHERE user_id=? AND asset_id=? AND symbol=?",(now.timestamp()+900,row['user_id'],row['asset_id'],row['symbol']))
  else:c.execute("UPDATE hw_cxe_feed_evidence SET payload=json_set(payload,'$.last_revalidation_error',?) WHERE user_id=? AND asset_id=? AND symbol=?",(retry_code,row['user_id'],row['asset_id'],row['symbol']))
 return 1 if status is None else 0

def holding_origin(c,uid,pid,asset_id):
 """No inferred acquisition origin from an accepted proposal.

 The currently verified Pluto intent contract proves acceptance, not the
 order/fill-to-intent relationship. A pre-existing holding or another purchase
 could match the same portfolio and asset. Keep the origin unknown until
 that broker relationship is available; asset+portfolio exit monitoring is
 independently verified and continues without this optional attribution.
 """
 return None

def refresh_holding_origin(connect,uid,pid,asset_id):
 """Refresh at most one matching proposal, read-only at Pluto; never infer a fill."""
 import trade_service
 with connect() as c:
  rows=c.execute("SELECT id,intent_id,payload,response FROM broker_proposals WHERE user_id=? AND portfolio_id=? AND report_id='@hotwatch' AND status='sent' AND intent_id IS NOT NULL ORDER BY id DESC LIMIT 50",(uid,pid)).fetchall()
 matches=[]
 for row in rows:
  try:
   orders=(json.loads(row['payload']).get('orders') or []);response=json.loads(row['response'] or '{}')
   if len(orders)!=1 or orders[0].get('assetId')!=asset_id or orders[0].get('side')!='BUY':continue
   if str(response.get('status') or '').upper() in ('ACCEPTED','CONFIRMED','CANCELLED','CANCELED','DECLINED','EXPIRED'):continue
   matches.append(row['id'])
  except (ValueError,TypeError,AttributeError):continue
 if len(matches)!=1:return
 try:trade_service.check(connect,uid,matches[0])
 except Exception:pass  # No proof remains no link; the ordinary holding monitor still runs.

def auto_holdings_tick(connect,verify=None,lookup=None,now=None):
 """Activate at most one owned position per tick, with persistent bounded retries."""
 from decimal import Decimal,InvalidOperation
 from hotwatch_adapters import search_eodhd_symbols
 now=now or engine.utc();epoch=now.timestamp();at=now.isoformat()
 if os.environ.get('ESCAPE_HW_HOLDINGS_AUTOWATCH','1')=='0':return None
 with connect() as c:
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return None
  snapshots=c.execute("SELECT p.user_id,p.id,s.payload FROM portfolios p JOIN users u ON u.id=p.user_id JOIN portfolio_snapshots s ON s.portfolio_id=p.id AND s.user_id=p.user_id WHERE p.active=1 AND p.source='pluto' AND u.active=1 AND s.last_error IS NULL ORDER BY p.user_id,p.id").fetchall()
  choices=[]
  for snap in snapshots:
   try:payload=json.loads(snap['payload'])
   except (ValueError,TypeError):continue
   if not isinstance(payload,dict) or not payload.get('positions_complete'):continue
   try:fresh=0<=(now-stamp(payload['observed'])).total_seconds()<=300
   except (KeyError,TypeError,ValueError):fresh=False
   if not fresh:continue
   for holding in payload.get('positions',[]):
    aid=holding.get('asset_id')
    try:valid=holding.get('kind')=='holding' and isinstance(aid,str) and bool(aid) and Decimal(str(holding.get('quantity')))>0
    except (InvalidOperation,ValueError,TypeError):valid=False
    if valid:choices.append((snap['user_id'],snap['id'],holding))
  for uid,pid,holding in choices:
   aid=holding['asset_id']
   control=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
   if control and control['killed']:continue
   existing=c.execute("SELECT watch_id,status,request FROM hw_sessions WHERE user_id=? AND is_test=0 AND json_extract(request,'$.asset_id')=? ORDER BY id DESC",(uid,aid)).fetchall()
   matches=[row for row in existing if json.loads(row['request']).get('watch_mode','both')!='entry' and (not json.loads(row['request']).get('portfolio_ids') or pid in json.loads(row['request'])['portfolio_ids'])]
   active=[row for row in matches if row['status'] in ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')]
   prior=c.execute('SELECT status,watch_id,next_attempt FROM hw_holding_autowatch WHERE user_id=? AND portfolio_id=? AND asset_id=?',(uid,pid,aid)).fetchone()
   generation=c.execute('SELECT updated FROM hw_holding_autowatch WHERE user_id=? AND portfolio_id=? AND asset_id=?',(uid,pid,aid)).fetchone() if prior and prior['status']=='POSITION_CLOSED' else None
   identity=str(uid)+'|'+str(pid)+'|'+aid+('|'+generation['updated'] if generation else '')
   watch='hw-holding-'+hashlib.sha256(identity.encode()).hexdigest()[:28]
   if len(active)==1:status='LINKED';linked=active[0]['watch_id']
   elif len(active)>1:status='AMBIGUOUS';linked=None
   elif prior and prior['status']=='STOPPED':status='STOPPED';linked=prior['watch_id']
   elif prior and prior['status']!='POSITION_CLOSED' and prior['watch_id'] and any(row['watch_id']==prior['watch_id'] and row['status'] in ('COMPLETED','EXPIRED','ERROR') for row in matches):status='STOPPED';linked=prior['watch_id']
   elif any(row['watch_id']==watch for row in matches):status='STOPPED';linked=watch
   else:
    if prior and prior['next_attempt']>epoch:continue
    status='VERIFYING';linked=None
   if status!='VERIFYING' and prior and prior['status']==status and prior['watch_id']==linked:continue
   c.execute("INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,portfolio_id,asset_id) DO UPDATE SET status=excluded.status,watch_id=excluded.watch_id,next_attempt=excluded.next_attempt,updated=excluded.updated",(uid,pid,aid,status,linked,epoch+300,at))
   if status=='VERIFYING':selected=(uid,pid,holding,watch);break
  else:return None
 uid,pid,holding,watch=selected;aid=holding['asset_id'];status='IDENTITY_UNVERIFIED';linked=None
 try:
  with connect() as c:
   count=c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]
   if count>=engine.capacity() and not engine.entry_for_holding(c,uid,now):raise EngineError('global_capacity_limit',409)
  known=verified_existing_feed(connect,uid,holding) if verify is None else None;diagnostic={}
  instrument=known or (verify(connect,uid,holding) if verify else holding_instrument(connect,uid,holding,diagnostic))
  if not known and verify is None and instrument:
   known=verified_existing_feed(connect,uid,instrument)
  if not instrument:status=diagnostic.get('code','IDENTITY_UNVERIFIED')
  if instrument and instrument.get('asset_id')==aid:
   provider='eodhd' if known else 'pluto';symbol=known.get('provider_symbol') if known else None
   if not known and instrument.get('isin') and os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')=='1' and os.environ.get('ESCAPE_EODHD_API_KEY','').strip():
    try:
     opts=(lookup or search_eodhd_symbols)(connect,uid,{'holding_portfolio_id':pid,'holding_asset_id':aid,'quote_currency':instrument['currency']})
     matches=[item for item in opts.get('choices',[]) if item.get('isin')==instrument['isin'] and item.get('currency')==instrument['currency']]
     if len(matches)==1:
      provider='eodhd';symbol=matches[0]['symbol'];remember_verified_feed(connect,uid,instrument,symbol,now)
    except DataUnavailable as error:
     if error.code in ('PROVIDER_RATE_BUDGET','EODHD_RATE_LIMIT'):raise
   cid='holding-'+hashlib.sha256((str(uid)+'|'+str(pid)+'|'+aid).encode()).hexdigest()[:28]
   risk={'max_notional_dkk':'1000','max_loss_dkk':'100','max_spread_pct':'1','max_quote_age_s':120,'max_position_fraction_pct':'20','proposed_quantity':None,'stop_price':None,'exit_deadline':None}
   req={'watch_id':watch,'report_id':'automatic-holdings','candidate_id':cid,'is_test':False,'purpose':'automatic holding watch','ticker':instrument['ticker'],'exchange':instrument['exchange'],'asset_id':aid,'quote_currency':instrument['currency'],'portfolio_ids':[pid],'priority':'NORMAL','profile':'NORMAL','provider':provider,'provider_symbol':symbol,'end_at':None,'activation_reason':'Automatisk overvågning af verificeret Pluto-beholdning','strategy_id':'escape_momentum','strategy_version':'1.0.0','risk':risk,'watch_mode':'exit'}
   refresh_holding_origin(connect,uid,pid,aid)
   with connect() as c:origin=holding_origin(c,uid,pid,aid)
   if origin:req.update(origin)
   import strategy_center
   selected=strategy_center.resolve(connect,uid,scope='exit');req.update(strategy_id=selected['strategy_id'],strategy_version=selected['version'],activation_reason=req['activation_reason']+' · '+selected['reason'])
   result=engine.create_holding(connect,uid,req,now);status='LINKED';linked=result['session']['watch_id']
 except EngineError as error:status='CAPACITY_LIMIT' if error.code in ('global_capacity_limit','capacity_limit') else error.code
 except Exception:status='VERIFICATION_FAILED'
 retry_at=(int(epoch//60)+1)*60+1 if status=='PROVIDER_RATE_BUDGET' else epoch+120 if status=='EODHD_RATE_LIMIT' else epoch+60 if status=='CAPACITY_LIMIT' else epoch+300
 with connect() as c:c.execute("UPDATE hw_holding_autowatch SET status=?,watch_id=?,next_attempt=?,updated=? WHERE user_id=? AND portfolio_id=? AND asset_id=?",(status,linked,retry_at,engine.utc().isoformat(),uid,pid,aid))
 return status

def reconcile_closed_holdings(connect,now=None):
 """Close only automatic position watches on fresh complete Pluto evidence."""
 from decimal import Decimal,InvalidOperation
 now=now or engine.utc();closed=0
 def absent(c,row):
  req=json.loads(row['request']);pids=req.get('portfolio_ids',[]);aid=req.get('asset_id')
  if len(pids)!=1 or not aid:return None
  snap=c.execute("SELECT s.payload,s.last_error FROM portfolios p JOIN portfolio_snapshots s ON s.portfolio_id=p.id AND s.user_id=p.user_id WHERE p.id=? AND p.user_id=? AND p.active=1 AND p.source='pluto'",(pids[0],row['user_id'])).fetchone()
  if not snap or snap['last_error']:return None
  try:
   payload=json.loads(snap['payload']);observed=stamp(payload['observed']);positions=payload['positions']
   if not payload.get('positions_complete') or not isinstance(positions,list) or not 0<=(now-observed).total_seconds()<=300 or observed<stamp(row['created']):return None
   if any(not isinstance(p,dict) or not p.get('kind') for p in positions):return None
   holdings=[p for p in positions if p.get('kind')=='holding']
   if any(not p.get('asset_id') or p.get('quantity') is None for p in holdings):return None
   if any(p['asset_id']==aid and Decimal(str(p['quantity']))!=0 for p in holdings):return None
   return pids[0],aid,observed
  except (AttributeError,KeyError,TypeError,ValueError,InvalidOperation):return None
 with connect() as preflight:
  rows=preflight.execute("SELECT * FROM hw_sessions WHERE is_test=0 AND purpose='automatic holding watch' AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchall()
  pending=[row['id'] for row in rows if absent(preflight,row)]
 if not pending:return 0
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  for watch_row_id in pending:
   row=c.execute("SELECT * FROM hw_sessions WHERE id=? AND is_test=0 AND purpose='automatic holding watch' AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(watch_row_id,)).fetchone()
   proof=absent(c,row) if row else None
   if not proof:continue
   pid,aid,observed=proof
   c.execute("UPDATE hw_sessions SET status='COMPLETED',updated=?,revision=revision+1,lease_owner=NULL,lease_until=0 WHERE id=?",(now.isoformat(),row['id']))
   engine.event(c,row,'HOLDING_NOT_PRESENT',now,'Frisk komplet depotobservation viser ingen beholdning',data_time=observed.isoformat())
   c.execute("UPDATE hw_holding_autowatch SET status='POSITION_CLOSED',next_attempt=0,updated=? WHERE user_id=? AND portfolio_id=? AND asset_id=? AND watch_id=?",(now.isoformat(),row['user_id'],pid,aid,row['watch_id']))
   closed+=1
 return closed

def exchange_status_tick(connect,client_factory=None,now=None):
 """Refresh one EODHD exchange status; this is not instrument tradability."""
 now=now or engine.utc();epoch=now.timestamp()
 if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1' or not os.environ.get('ESCAPE_EODHD_API_KEY','').strip():return None
 def candidates(c):
  rows=c.execute("SELECT s.request FROM hw_sessions s JOIN users u ON u.id=s.user_id AND u.active=1 LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.is_test=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND COALESCE(k.killed,0)=0 AND json_extract(s.request,'$.provider')='eodhd'").fetchall()
  return sorted({v.rsplit('.',1)[-1].upper() for row in rows if isinstance((v:=json.loads(row['request']).get('provider_symbol')),str) and '.' in v and re.fullmatch(r'[A-Za-z0-9_-]{1,16}',v.rsplit('.',1)[-1])})
 # Avoid a writer lock on the frequent idle path; every condition is checked
 # again under the existing transaction before reserving an exchange.
 with connect() as c:
  due=False
  for item in candidates(c):
   prior=c.execute('SELECT next_attempt FROM hw_exchange_status WHERE exchange=?',(item,)).fetchone()
   if not prior or prior['next_attempt']<=epoch:due=True;break
 if not due:return None
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return None
  exchanges=candidates(c)
  # A slow maintenance loop can leave every exchange due on every pass.
  # Choose the most overdue (including never checked), not alphabetically.
  pending=[]
  for item in exchanges:
   prior=c.execute('SELECT next_attempt FROM hw_exchange_status WHERE exchange=?',(item,)).fetchone()
   due=prior['next_attempt'] if prior else 0
   if due<=epoch:pending.append((due,item))
  exchange=min(pending)[1] if pending else None
  if exchange:c.execute('INSERT INTO hw_exchange_status(exchange,next_attempt) VALUES(?,?) ON CONFLICT(exchange) DO UPDATE SET next_attempt=excluded.next_attempt',(exchange,epoch+60))
 if not exchange:return None
 try:
  from eodhd_feeds import EODHDFeeds
  from hotwatch_adapters import reserve
  client=(client_factory or (lambda:EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),capacity=Capacity(connect,'essential'))))()
  result=client.market_status(exchange)
  received=stamp(result['received_at']) if result.get('received_at') else None
  if result.get('status')!='OK' or result.get('exchange')!=exchange or type(result.get('exchange_open')) is not bool or not received or not 0<=(engine.utc()-received).total_seconds()<=30:return result.get('status','INVALID_RESPONSE')
  with connect() as c:
   c.execute('UPDATE hw_exchange_status SET received=?,is_open=?,next_attempt=? WHERE exchange=?',(received.isoformat(),int(result['exchange_open']),epoch+60,exchange))
   if result.get('calendar') and result.get('timezone'):
    c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?) ON CONFLICT(exchange) DO UPDATE SET received=excluded.received,timezone=excluded.timezone,calendar=excluded.calendar',(exchange,received.isoformat(),result['timezone'],json.dumps(result['calendar'])))
  return 'OK'
 except Exception:return 'UNAVAILABLE'

def configure_scan_log():
 """Keep the existing sanitised worker records when stdout is discarded."""
 from pathlib import Path
 from logging.handlers import RotatingFileHandler
 path=Path(app.DB).resolve().parent/'hotwatch-scans.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600);os.close(fd)
 logger=logging.getLogger('escape.hotwatch')
 if any(isinstance(h,RotatingFileHandler) and h.baseFilename==str(path) for h in logger.handlers):return
 class PrivateScanHandler(RotatingFileHandler):
  def _open(self):
   fd=os.open(self.baseFilename,os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
   os.fchmod(fd,0o600)
   return os.fdopen(fd,'a',encoding='utf-8')
 handler=PrivateScanHandler(path,maxBytes=1024*1024,backupCount=2,encoding='utf-8');handler.setFormatter(logging.Formatter('%(message)s'))
 logger.addHandler(handler);logger.setLevel(logging.INFO)

def recent_scan_log(uid,mode,watch_ids):
 """Read only this user's requested sessions; never expose other users' logs."""
 from pathlib import Path
 allowed={hashlib.sha256(w.encode()).hexdigest()[:16] for w in watch_ids};rows=[]
 path=Path(app.DB).resolve().parent/'hotwatch-scans.jsonl'
 try:
  with path.open('rb') as f:
   f.seek(0,2);size=f.tell();f.seek(max(0,size-1024*1024));lines=f.read().decode('utf-8',errors='replace').splitlines()
  for line in reversed(lines):
   try:r=json.loads(line)
   except ValueError:continue
   if not isinstance(r,dict) or r.get('service')!='hotwatch' or r.get('user_id')!=uid or r.get('is_test') is not mode or r.get('watch_ref') not in allowed:continue
   rows.append({k:r[k] for k in ('utc','watch_ref','source','status','code','metrics') if k in r})
   if len(rows)>=30:break
  return {'status':'AVAILABLE','records':rows,'retention':'rotating 3 x 1 MiB; records may be incomplete'}
 except OSError:return {'status':'UNAVAILABLE','records':[]}

def entry_funnel(rows,now):
 """Bounded historical readout, no strategy/risk changes or backtest claims."""
 from collections import Counter,defaultdict
 from decimal import Decimal,InvalidOperation
 from hotwatch_strategy import rule_state
 latest={};series=defaultdict(list);truncated=len(rows)>5000
 for row in rows[:5000]:
  try:
   req=json.loads(row['request']);strategy=json.loads(row['strategy']);calc=json.loads(row['calculation']);sample=json.loads(row['sample']) if row['sample'] else None
   if req.get('watch_mode')=='exit' or req.get('purpose')=='automatic holding watch':continue
   candidate=req.get('candidate_id') or row['watch_id'];at=stamp(row['calculated'])
   if at>now or (now-at).total_seconds()>86400:continue
   # Count the most recent calculation per candidate, even if data missing.
   if candidate not in latest:latest[candidate]=(req,strategy,calc,sample,at,row['strategy_checksum'])
   if sample and sample.get('verification')=='verified' and sample.get('source') in ('eodhd','pluto') and calc.get('data_timestamp')==sample.get('event_time') and 0<=(at-stamp(sample['event_time'])).total_seconds()<=req['risk']['max_quote_age_s']:
    series[row['watch_id']].append((at,calc,sample))
  except (TypeError,ValueError,KeyError,ArithmeticError):continue
 groups={};missing=0
 for req,strategy,calc,sample,at,stored_checksum in latest.values():
  try:
   if not sample or sample.get('verification')!='verified' or sample.get('source') not in ('eodhd','pluto') or calc.get('data_timestamp')!=sample.get('event_time') or 'DATA_STALE' in calc.get('reason_codes',[]) or 'DATA_UNVERIFIED' in calc.get('reason_codes',[]) or not 0<=(at-stamp(sample['event_time'])).total_seconds()<=min(req['risk']['max_quote_age_s'],120) or engine.checksum(strategy)!=stored_checksum:missing+=1;continue
   rules=strategy['entry_rules'].get('all',[strategy['entry_rules']]);params=strategy['parameters'];metrics=calc.get('supporting_metrics') or {}
   key=strategy['strategy_id']+' v'+strategy['version'];group=groups.setdefault(key,{'eligible':0,'rules':[],'all_passed':0,'signals':Counter()})
   if not group['rules']:
    for i,r in enumerate(rules):
     label=r.get('metric') if isinstance(r,dict) else None
     group['rules'].append({'rule':label if isinstance(label,str) else 'rule_group_'+str(i+1),'passed':0,'failed':0,'unknown':0,'cumulative_passed':0})
   if len(group['rules'])!=len(rules):continue
   group['eligible']+=1;group['signals'][calc.get('signal','UNKNOWN')]+=1;chain=True
   for index,rule in enumerate(rules):
    outcome=rule_state(rule,metrics,params);item=group['rules'][index];item['passed' if outcome is True else 'failed' if outcome is False else 'unknown']+=1
    chain=chain and outcome is True
    if chain:item['cumulative_passed']+=1
   if chain:group['all_passed']+=1
  except (KeyError,ValueError,TypeError,ArithmeticError):missing+=1
 before=[];after=[];confirmations=0
 def identity(sample):return tuple(sample.get(k) for k in ('source','asset_id','currency','venue','session_key','market_status','feed_type','price_time_kind'))
 for items in series.values():
  items.sort(key=lambda x:x[0]);pending=None
  for index,(at,calc,sample) in enumerate(items):
   try:
    codes=calc.get('reason_codes',[]);price=Decimal(str(sample.get('price')))
    if not price.is_finite() or price<=0:continue
    if 'CONFIRMATION_PENDING' in codes:
     if pending is None:pending=(at,price,identity(sample))
    elif calc.get('signal')=='BUY':
     if pending and pending[2]==identity(sample) and 0<=(at-pending[0]).total_seconds()<=600:
      confirmations+=1;before.append(float((price/pending[1]-1)*100))
      for future_at,_,future_sample in items[index+1:]:
       delta=(future_at-at).total_seconds()
       if delta>600:break
       if delta>=300 and identity(future_sample)==identity(sample):
        future=Decimal(str(future_sample.get('price')))
        if future.is_finite() and future>0:after.append(float((future/price-1)*100))
        break
     pending=None
    else:pending=None
   except (TypeError,ValueError,ArithmeticError,InvalidOperation):pending=None
 def movement(values):
  ordered=sorted(values);n=len(ordered)
  median=(ordered[(n-1)//2]+ordered[n//2])/2 if n else None
  return {'count':n,'average_pct':round(sum(ordered)/n,4) if n else None,'median_pct':round(median,4) if n else None}

 for group in groups.values():group['signals']=dict(group['signals'])
 return {'window_hours':24,'candidate_count':len(latest),'missing_or_unverified':missing,'strategies':groups,'confirmation_movement':{'confirmed_sequences':confirmations,'before_confirmation':movement(before),'five_to_ten_minutes_after':movement(after)},'history_truncated':truncated,'note':'Seneste beregning pr. kandidat blandt de nyeste højst 100000 beregninger og 5000 match. Historiske observationer er ikke en profitabilitetsmåling; manglende målinger er ikke nul.'}

def admin_diagnostics(connect,uid,now=None):
 """Read bounded existing operational evidence; do not initiate work or trade."""
 from pathlib import Path
 import math,shutil
 from collections import Counter
 from datetime import datetime,timezone
 from eodhd_capacity import snapshot
 now=now or engine.utc();epoch=now.timestamp();base=Path(app.DB).resolve();path=base.parent/'hotwatch-scans.jsonl'
 with connect() as c:
  sessions=c.execute("SELECT * FROM hw_sessions WHERE user_id=? AND is_test=0 AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED','PAUSED')",(uid,)).fetchall()
  history_sessions=c.execute('SELECT watch_id,request FROM hw_sessions WHERE user_id=? AND is_test=0 ORDER BY id DESC LIMIT 10001',(uid,)).fetchall()
  beat=c.execute('SELECT updated,status FROM hw_heartbeat WHERE id=1').fetchone()
  supervisor=c.execute('SELECT updated,status,attempts FROM hw_supervisor_status WHERE id=1').fetchone()
  events=[dict(x) for x in c.execute('SELECT created,event,code FROM hw_supervisor_events ORDER BY id DESC LIMIT 50')]
  health=c.execute('SELECT source,attempted,succeeded,code,payload FROM hw_provider_health WHERE user_id=? AND is_test=0',(uid,)).fetchall()
  push={x['status']:x['n'] for x in c.execute('SELECT j.status,count(*) AS n FROM push_jobs j JOIN push_devices d ON d.id=j.device_id WHERE d.user_id=? AND j.created>=? GROUP BY j.status',(uid,epoch-86400))}
  push_pending=c.execute("SELECT min(j.created) FROM push_jobs j JOIN push_devices d ON d.id=j.device_id WHERE d.user_id=? AND j.status='pending'",(uid,)).fetchone()[0]
  jobs={x['status']:x['n'] for x in c.execute('SELECT status,count(*) AS n FROM jobs WHERE user_id=? AND created>=? GROUP BY status',(uid,epoch-86400))}
  cron=c.execute('SELECT heartbeat FROM worker_state WHERE id=1').fetchone()
  provider=snapshot(c,epoch);journal=c.execute('PRAGMA journal_mode').fetchone()[0];pages=c.execute('PRAGMA page_count').fetchone()[0];page_size=c.execute('PRAGMA page_size').fetchone()[0]
  busy=c.execute("SELECT count(*) FROM hw_sessions WHERE lease_owner IS NOT NULL AND lease_until>?",(epoch,)).fetchone()[0]
  funnel_rows=c.execute("SELECT s.watch_id,s.request,s.strategy,h.calculated,h.payload AS calculation,h.strategy_checksum,m.payload AS sample FROM hw_calculations h JOIN hw_sessions s ON s.id=h.watch_row_id LEFT JOIN hw_samples m ON m.id=h.sample_row_id WHERE h.id>COALESCE((SELECT max(id)-100000 FROM hw_calculations),0) AND s.user_id=? AND s.is_test=0 AND h.calculated>=? AND h.calculated<=? ORDER BY h.id DESC LIMIT 5001",(uid,(now-timedelta(days=1)).isoformat(),now.isoformat())).fetchall()
  push_rows=c.execute("SELECT s.request,j.status,e.event_type,e.payload FROM push_jobs j JOIN push_devices d ON d.id=j.device_id JOIN hw_sessions s ON s.id=j.watch_row_id LEFT JOIN hw_events e ON e.event_id=j.event_key AND e.watch_row_id=s.id WHERE d.user_id=? AND j.created>=? LIMIT 20000",(uid,epoch-86400)).fetchall()
  readiness=[]
  for row in sessions:
   try:
    req=json.loads(row['request']);symbol=req.get('provider_symbol') or '';market=symbol.rsplit('.',1)[-1].upper() if '.' in symbol else str(req.get('exchange') or 'UNKNOWN').upper()
    if not re.fullmatch(r'[A-Z0-9_-]{1,16}',market):market='UNKNOWN'
    view=engine.view(c,row,now);signals=view.get('signal');reasons=view.get('display_reason_codes') or []
    readiness.append({'market':market,'signal':signals if signals in ('BUY','SELL','REDUCE','WAIT','NO_DATA','PAUSE') else 'UNKNOWN','blocking':[x for x in reasons if isinstance(x,str) and re.fullmatch(r'[A-Za-z0-9_]{1,80}',x)][:12]})
   except (ValueError,TypeError,KeyError,AttributeError):readiness.append({'market':'UNKNOWN','signal':'UNKNOWN','blocking':['STATUS_UNAVAILABLE']})
 watches={};states=Counter();errors=Counter();overdue=[];reduced=[]
 for row in history_sessions[:10000]:
  try:req=json.loads(row['request']);ticker=req.get('ticker','?')
  except (ValueError,TypeError):ticker='?'
  ref=hashlib.sha256(row['watch_id'].encode()).hexdigest()[:16];watches[ref]=ticker if isinstance(ticker,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,40}',ticker) else '?'
 for row in sessions:
  try:req=json.loads(row['request']);ticker=req.get('ticker','?')
  except (ValueError,TypeError):ticker='?'
  ref=hashlib.sha256(row['watch_id'].encode()).hexdigest()[:16];watches[ref]=ticker if isinstance(ticker,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,40}',ticker) else '?'
  states[row['status']]+=1
  try:
   status_state=json.loads(row['state'])
   if row['status']!='PAUSED' and status_state.get('quiet_market_poll') is True and row['next_due']>epoch:reduced.append({'ticker':watches[ref],'next_check':datetime.fromtimestamp(row['next_due'],timezone.utc).isoformat()})
  except (ValueError,TypeError,AttributeError):pass
  if row['last_error'] and re.fullmatch(r'[A-Za-z0-9_]{1,100}',row['last_error']):errors[row['last_error']]+=1
  if row['status']!='PAUSED' and row['next_due']<=epoch and row['lease_until']<=epoch:overdue.append({'ticker':watches[ref],'late_s':round(epoch-row['next_due'],1)})
 records=[];files_read=0
 numeric=('queue_ms','claim_ms','provider_ms','ingest_compute_ms','adapter_to_journal_ms','warmup_ms','worker_busy_ms','pluto_context_ms','eodhd_http_ms','websocket_capture_ms','begin_wait_ms','scope_entry_wait_ms','sqlite_begin_ms','occupied_workers','due_sessions','quiet_avoided_estimate')
 for item in (path,Path(str(path)+'.1'),Path(str(path)+'.2'),Path(str(path)+'.3')):
  try:
   with item.open('rb') as f:f.seek(0,2);f.seek(max(0,f.tell()-1048576));lines=f.read().decode('utf-8',errors='replace').splitlines()
   files_read+=1
  except OSError:continue
  for line in lines:
   try:
    rec=json.loads(line);ref=rec.get('watch_ref');at=stamp(rec['utc']);age=epoch-at.timestamp()
    if rec.get('service')!='hotwatch' or rec.get('user_id')!=uid or rec.get('is_test') is not False or ref not in watches or not 0<=age<=86400:continue
    metrics=rec.get('metrics') or {};clean={k:round(metrics[k],3) for k in numeric if isinstance(metrics.get(k),(int,float)) and not isinstance(metrics.get(k),bool) and math.isfinite(metrics[k]) and 0<=metrics[k]<=86400000}
    clean['warmup_deferred']=metrics.get('warmup_deferred') is True
    clean['intraday_cache_hit']=metrics.get('intraday_cache_hit') is True
    for key in ('websocket_trade_status','websocket_quote_status','websocket_status_status','minute_bars_status','bar_history_status','intraday_status'):
     value=metrics.get(key)
     if isinstance(value,str) and re.fullmatch(r'[A-Z0-9_]{1,80}',value):clean[key]=value
    ws=metrics.get('websocket') or []
    if not isinstance(ws,list):ws=[]
    clean['websocket_ms']=round(sum(x.get('wait_ms',0) for x in ws if isinstance(x,dict) and isinstance(x.get('wait_ms'),(int,float)) and not isinstance(x.get('wait_ms'),bool) and math.isfinite(x['wait_ms']) and 0<=x['wait_ms']<=60000),3)
    clean['websocket']=[{**{k:x[k] for k in ('feed','status','wait_ms','source_age_s','received_age_s','connections_opened','subscriptions_sent','cache_hit') if k in x and (isinstance(x[k],bool) or isinstance(x[k],(int,float)) and math.isfinite(x[k]) and abs(x[k])<=86400000 or isinstance(x[k],str) and re.fullmatch(r'[A-Za-z0-9_]{1,40}',x[k]))},**{k:x[k] for k in ('batch_valid_count','batch_partial_count') if type(x.get(k)) is int and 0<=x[k]<=250},**({'batch_limit_reached':x['batch_limit_reached']} if type(x.get('batch_limit_reached')) is bool else {})} for x in ws[:10] if isinstance(x,dict)]
    conflict=metrics.get('market_conflict')
    if isinstance(conflict,dict):
     fields=[x for x in (conflict.get('fields') or []) if isinstance(x,str) and x in ('price','bid','ask','volume','open','high','low','close')]
     if fields:
      clean['market_conflict']={'fields':fields,'previous':{},'incoming':{}}
      for side in ('previous','incoming'):
       values=conflict.get(side) if isinstance(conflict.get(side),dict) else {}
       for field in fields:
        value=values.get(field)
        if isinstance(value,str) and re.fullmatch(r'\d{1,31}(?:\.\d{1,12})?',value):clean['market_conflict'][side][field]=value
      observations=conflict.get('observations')
      if isinstance(observations,dict):
       clean['market_conflict']['observations']={}
       for side in ('previous','incoming'):
        item=observations.get(side) if isinstance(observations.get(side),dict) else {};safe={}
        if item.get('source') in ('eodhd','pluto','synthetic','report_inbox'):safe['source']=item['source']
        if item.get('price_time_kind') in ('trade','bar_open'):safe['price_time_kind']=item['price_time_kind']
        if item.get('feed_kind') in ('US_WS_TRADE','EU_WS_TRADE','REALTIME_BAR','INTRADAY_BAR','REST_SNAPSHOT'):safe['feed_kind']=item['feed_kind']
        if isinstance(item.get('sample_ref'),str) and re.fullmatch(r'[0-9a-f]{16}',item['sample_ref']):safe['sample_ref']=item['sample_ref']
        for key in ('event_time','bid_at','ask_at','status_at'):
         try:
          if item.get(key):safe[key]=stamp(item[key]).isoformat()
         except (ValueError,TypeError,AttributeError):pass
        clean['market_conflict']['observations'][side]=safe
      for key in ('previous_journal_received_at','ingest_attempt_at'):
       try:
        if conflict.get(key):clean['market_conflict'][key]=stamp(conflict[key]).isoformat()
       except (ValueError,TypeError,AttributeError):pass
    status=rec.get('status');code=rec.get('code');source=rec.get('source')
    records.append({'at':at.isoformat(),'ticker':watches[ref],'status':status if status in ('processed','degraded','deferred','cancelled','context_rejected') else 'unknown','code':code if isinstance(code,str) and re.fullmatch(r'[A-Za-z0-9_]{1,100}',code) else None,'source':source if source in ('eodhd','pluto','report_inbox','synthetic') else 'unknown','metrics':clean,'_epoch':at.timestamp()})
   except (ValueError,TypeError,KeyError,AttributeError,OverflowError):continue
 records.sort(key=lambda x:x['_epoch'],reverse=True)
 def summary(seconds):
  subset=[x for x in records if x['_epoch']>=epoch-seconds];done=[x for x in subset if x['status'] in ('processed','degraded')];deferred=sum(x['status']=='deferred' for x in subset)
  def stat(name):
   vals=sorted(x['metrics'][name] for x in done if name in x['metrics'])
   if not vals:return None
   return {'count':len(vals),'p50_ms':vals[(len(vals)-1)//2],'p90_ms':vals[math.ceil(.9*len(vals))-1],'max_ms':vals[-1]}
  return {'completed':len(done),'deferred':deferred,'queue':stat('queue_ms'),'worker':stat('worker_busy_ms'),'provider':stat('provider_ms'),'database':stat('ingest_compute_ms'),'warmup':stat('warmup_ms'),'websocket':stat('websocket_ms')}
 windows={name:summary(seconds) for name,seconds in (('5m',300),('1h',3600),('24h',86400))}
 timeline=[]
 for i in range(11,-1,-1):
  end=epoch-i*300;start=end-300;group=sorted(x['metrics']['queue_ms'] for x in records if x['status'] in ('processed','degraded') and start<=x['_epoch']<end and 'queue_ms' in x['metrics'])
  slice_records=[x for x in records if start<=x['_epoch']<end]
  observed_workers=[x['metrics']['occupied_workers'] for x in slice_records if 'occupied_workers' in x['metrics']]
  observed_due=[x['metrics']['due_sessions'] for x in slice_records if 'due_sessions' in x['metrics']]
  timeline.append({'from':datetime.fromtimestamp(start,timezone.utc).isoformat(),'to':datetime.fromtimestamp(end,timezone.utc).isoformat(),'count':len(group),'p50_ms':group[(len(group)-1)//2] if group else None,'p90_ms':group[math.ceil(.9*len(group))-1] if group else None,'max_ms':group[-1] if group else None,'occupied_workers_observed_max':max(observed_workers) if observed_workers else None,'due_sessions_observed_max':max(observed_due) if observed_due else None})
 # Counts are observations, not attribution: elapsed components overlap.
 queue_factors={}
 for label,seconds in (('5m',300),('1h',3600),('24h',86400)):
  subset=[x for x in records if x['_epoch']>=epoch-seconds]
  by_busy={};retry=Counter(x['code'] or 'UNKNOWN' for x in subset if x['status']=='deferred')
  for item in subset:
   m=item['metrics'];occ=m.get('occupied_workers');q=m.get('queue_ms')
   if occ is not None and q is not None:by_busy.setdefault(str(int(occ)),[]).append(q)
  def phase_stat(key):
   vals=sorted(x['metrics'][key] for x in subset if key in x['metrics'])
   return {'count':len(vals),'p50_ms':vals[(len(vals)-1)//2],'p90_ms':vals[math.ceil(.9*len(vals))-1],'max_ms':vals[-1]} if vals else None
  queue_factors[label]={'queue_by_occupied_workers':{k:{'count':len(v),'average_ms':round(sum(v)/len(v),2),'max_ms':max(v)} for k,v in by_busy.items()},'deferred_by_reason':dict(retry),'worker_busy':phase_stat('worker_busy_ms'),'websocket_wait':phase_stat('websocket_ms'),'database_begin_wait':phase_stat('begin_wait_ms'),'note':'Besættelse er målt ved claim; komponenter kan overlappe og summeres ikke til køtiden.'}
 ready={}
 for item in readiness:
  key=item['market'];entry=ready.setdefault(key,{'signals':Counter(),'blockers':Counter()});entry['signals'][item['signal']]+=1
  for reason in item['blocking']:entry['blockers'][reason]+=1
 push_detail=Counter()
 for item in push_rows:
  try:
   ticker=json.loads(item['request']).get('ticker','?');ticker=ticker if isinstance(ticker,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,40}',ticker) else '?'
   kind=item['event_type'] if isinstance(item['event_type'],str) and re.fullmatch(r'[A-Z0-9_]{1,50}',item['event_type']) else 'UNKNOWN'
   payload=json.loads(item['payload']) if item['payload'] else {};reason=payload.get('reason','UNKNOWN');reason=reason if isinstance(reason,str) and re.fullmatch(r'[A-Z0-9_]{1,80}',reason) else 'SEE_EVENT_TYPE'
   push_detail[(ticker,kind,reason,item['status'])]+=1
  except (ValueError,TypeError,AttributeError):continue
 recent=[{k:v for k,v in x.items() if k!='_epoch'} for x in records[:500]]
 providers=[]
 for row in health:
  try:
   payload=json.loads(row['payload']);timing=payload.get('worker_database_timing') or {}
   safe={k:timing.get(k) for k in ('scope','completed_scopes','max_wait_ms','max_scope_ms','slowest_module','slowest_function') if isinstance(timing.get(k),(str,int,float))}
   settings=payload.get('worker_settings') or {};configured={k:settings.get(k) for k in ('ESCAPE_HW_PARALLEL_SCANS','ESCAPE_HW_CONCURRENCY') if settings.get(k) is None or isinstance(settings.get(k),str) and re.fullmatch(r'[0-9]{1,4}',settings[k])}
   feeds={k:payload[k] for k in ('websocket_trade_status','websocket_quote_status','websocket_status_status','minute_bars_status','intraday_status','bar_history_status') if isinstance(payload.get(k),str) and re.fullmatch(r'[A-Z0-9_]{1,80}',payload[k])}
   defaults={k:payload[k] for k in ('parallel_scans_default','concurrency_default','session_capacity') if type(payload.get(k)) is int and 0<payload[k]<=10000}
  except (ValueError,TypeError,AttributeError):safe={};configured={};feeds={};defaults={}
  providers.append({'source':row['source'],'attempted':row['attempted'],'succeeded':row['succeeded'],'code':row['code'],'worker_database_timing':safe,'worker_settings':configured,'worker_defaults':defaults,'last_successful_feeds':feeds})
 def size(p):
  try:return p.stat().st_size
  except OSError:return None
 try:disk=shutil.disk_usage(base.parent);storage={'free_bytes':disk.free,'total_bytes':disk.total}
 except OSError:storage={'free_bytes':None,'total_bytes':None}
 storage.update(database_bytes=size(base),wal_bytes=size(Path(str(base)+'-wal')),journal_mode=journal,page_count=pages,page_size=page_size)
 import hotwatch_supervisor
 app_errors=hotwatch_supervisor.application_error_fallback()
 # Only report explicitly recorded events. Missing crash intervals cannot be reconstructed.
 gaps=[];stopped=None
 for ev in reversed(events):
  if ev['event'] in ('supervisor_stopped','worker_stopped'):stopped=ev
  elif ev['event']=='worker_started' and stopped:
   try:gaps.append({'stopped_at':stopped['created'],'started_at':ev['created'],'duration_s':max(0,round((stamp(ev['created'])-stamp(stopped['created'])).total_seconds(),1)),'reason':'not recorded'})
   except (TypeError,ValueError):pass
   stopped=None
 revision_info=engine.installed_revision();revision=revision_info['commit'];revision_source=revision_info['source']
 return {'installation':{'declared_commit':revision,'commit_source':revision_source,'observed_restart_gaps':gaps,'note':'Genstartshuller bygger kun på registrerede stop og starter; uregistrerede nedbrud er ukendte.'},'application_errors':app_errors,'as_of':now.isoformat(),'scope':'own_sessions_and_shared_process','worker':dict(beat) if beat else None,'supervisor':dict(supervisor) if supervisor else None,'supervisor_events':events,'session_count':len(sessions),'states':dict(states),'errors':dict(errors),'due_count':len(overdue),'overdue':sorted(overdue,key=lambda x:x['late_s'],reverse=True)[:20],'provider_capacity':provider,'provider_forecast':{'minute_remaining':max(0,provider['http_effective_limit_per_minute']-provider['http_used_this_minute']),'daily_remaining_reported':max(0,provider['account']['dailyRateLimit']-provider['account']['apiRequests']) if provider.get('account') and provider['account'].get('apiRequestsDate')==now.date().isoformat() else None,'estimated_daily_usage_at_current_average':round(provider['account']['apiRequests']*86400/max(1,epoch%86400)) if provider.get('account') and provider['account'].get('apiRequestsDate')==now.date().isoformat() and epoch%86400>=3600 else None,'note':'Dagligt restbudget er seneste kontosnapshot, ikke en garanti; ukendte omkostninger og andre klienter kan forekomme.'},'providers':providers,'storage':storage,'push':{'last_24h':push,'oldest_pending_age_s':round(max(0,epoch-push_pending),1) if push_pending is not None else None},'scheduled_jobs':{'last_24h':jobs,'worker_last_seen':datetime.fromtimestamp(cron['heartbeat'],timezone.utc).isoformat() if cron else None},'windows':windows,'queue_factors':queue_factors,'worker_utilization':{'occupied_now':busy,'capacity':max(1,min(10,int(os.environ.get('ESCAPE_HW_CONCURRENCY','2')))) if os.environ.get('ESCAPE_HW_CONCURRENCY','2').isdigit() else None,'note':'Leases viser optagne workers; tidligere målinger findes kun, hvor de er registreret.'},'entry_funnel':entry_funnel(funnel_rows,now),'readiness_by_market':{k:{'signals':dict(v['signals']),'blockers':dict(v['blockers'])} for k,v in ready.items()},'market_sleep':{'sleeping_sessions':0,'next_wake':None,'reduced_polling_sessions':len(reduced),'next_checks':reduced[:60],'estimated_avoided_scans':sum(x['metrics'].get('quiet_avoided_estimate',0) for x in records if x['status'] in ('processed','degraded')) if records else None,'avoided_intraday_http_requests':sum(x['metrics'].get('intraday_cache_hit',False) for x in records),'estimated_saved_api_units':5*sum(x['metrics'].get('intraday_cache_hit',False) for x in records),'late_wakes_after_open':None,'note':'Intet instrument sættes helt i dvale uden verificeret Pluto-handelsadgang. Undgåede intradag-kald er registrerede cachetræf; API-besparelsen er estimeret til 5 enheder pr. kald. Undgåede scanninger er estimeret, og forsinkede opvågninger er ikke målt.'},'push_detail':{'items':[{'ticker':k[0],'event_type':k[1],'reason':k[2],'status':k[3],'count':v} for k,v in push_detail.items()],'limited':len(push_rows)>=20000,'note':'Skipped omfatter flere årsager og er ikke et særskilt deduplikeringstal.'},'timeline':timeline,'recent':recent,'log_files_read':files_read,'log_earliest':records[-1]['at'] if records else None,'history_scope_truncated':len(history_sessions)>10000,'log_retention':'Roterende filer; perioderne kan være ufuldstændige. Udskudte indsamlinger tælles separat.','unavailable':'Eksterne processers CPU, hukommelse og fuld versionsidentitet er ikke registreret.'}

def worker_settings():
 keys=('ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE','ESCAPE_HW_REQUESTS_PER_MINUTE','ESCAPE_HW_EODHD_FAST_POLL_ENABLED','ESCAPE_HW_EODHD_MIN_POLL_S','ESCAPE_HW_EODHD_WS_TRADES_ENABLED','ESCAPE_HW_EODHD_FUSE_ENABLED','ESCAPE_HW_EODHD_BARS_ENABLED','ESCAPE_HW_EODHD_WS_EU_EXCHANGES','ESCAPE_HW_PARALLEL_SCANS','ESCAPE_HW_CONCURRENCY','ESCAPE_HW_CAPACITY')
 return {k:(v if v is None or re.fullmatch(r'[A-Za-z0-9_,.-]{0,100}',v) else 'INVALID') for k in keys for v in [os.environ.get(k)]}

class Runner:
 def __init__(self,connect):self.connect=serialized_database(connect);self.adapters={};self.brokers={};self.broker_lock=threading.Lock();self.stop=threading.Event();self._workers=[];self.pending_feeds={};self.pending_lock=threading.Lock()
 def once(self,now=None,watch_id=None):
  now=now or engine.utc();claim_started=time.perf_counter()
  with self.pending_lock:
   for ident,event in list(self.pending_feeds.items()):
    if event.is_set():self.pending_feeds.pop(ident,None)
   excluded=tuple(self.pending_feeds)
   job=engine.claim(self.connect,now,watch_id,exclude_ids=excluded)
  claimed=engine.utc()
  if not job:return False
  job['scan_timing']={'next_due_at':engine.datetime.fromtimestamp(job['next_due'],engine.timezone.utc).isoformat(),'claimed_at':claimed.isoformat(),'claim_ms':round((time.perf_counter()-claim_started)*1000,3),'queue_ms':max(0,round((claimed.timestamp()-job['next_due'])*1000,3)),'occupied_workers':job.get('diagnostic_occupied_workers'),'due_sessions':job.get('diagnostic_due_sessions')}
  try:
   prior_state=json.loads(job['state']);baseline=prior_state.get('quiet_baseline_s');scheduled=prior_state.get('scheduled_interval_s')
   if prior_state.get('quiet_market_poll') is True and type(baseline) in (int,float) and baseline>0 and type(scheduled) in (int,float):job['scan_timing']['quiet_avoided_estimate']=max(0,int(scheduled//baseline)-1)
  except (ValueError,TypeError,AttributeError):pass
  uid=job['user_id'];r=job['request_data'];wid=job['watch_id'];mode=bool(job['is_test']);lease=job['lease_owner'];adapter=None;sample=None;uses_realtime_history=False;pending_feed=False;scan_log=None;warmup_ms=0;warmup_deferred=False;stale_duplicate=False
  try:
   poll_started=time.perf_counter();job['scan_timing']['poll_started_at']=engine.utc().isoformat()
   if r['end_at'] and stamp(r['end_at'])<=now:
    engine.fault(self.connect,uid,wid,mode,'WATCH_EXPIRED',now,lease);return True
   if r['provider']=='synthetic':
    if not job['last_data'] or (now-stamp(job['last_data'])).total_seconds()>r['risk']['max_quote_age_s']:raise DataUnavailable('DATA_STALE')
    engine.release(self.connect,job,now);return True
   key=(uid,r['provider']);adapter=self.adapters.get(key)
   if not adapter:
    adapter={'pluto':PlutoAdapter,'eodhd':EODHDAdapter,'report_inbox':InboxAdapter}[r['provider']](self.connect,uid)
    if r['provider'] in ('pluto','eodhd'):
     with self.broker_lock:
      broker=self.brokers.setdefault(uid,adapter if r['provider']=='pluto' else adapter.pluto)
     if r['provider']=='pluto':adapter=broker
     else:adapter.pluto=broker
    self.adapters[key]=adapter
   sample=adapter.poll(job);adapter_received=engine.utc();provider_done=time.perf_counter()
   job['scan_timing']['poll_finished_at']=adapter_received.isoformat()
   self.partials(job,adapter)
   adapter_latency_ms=(adapter_received-stamp(sample['event_time'])).total_seconds()*1000 if sample.get('event_time') else None
   # The worker consumes the calculation only. Building a complete dashboard
   # view here would hold the SQLite writer lock during additional reads.
   job['scan_timing']['ingest_started_at']=engine.utc().isoformat()
   result=engine.ingest(self.connect,uid,wid,mode,sample,now=engine.utc(),lease=lease,include_session=False)
   uses_realtime_history=bool((result.get('calculation') or {}).get('analysis_uses_bars'))
   journaled_at=engine.utc();ingest_done=time.perf_counter()
   job['scan_timing']['ingest_finished_at']=journaled_at.isoformat()
   timings={**job['scan_timing'],'websocket':getattr(adapter,'capture_metrics',[]),'provider_ms':round((provider_done-poll_started)*1000,3),'adapter_to_journal_ms':round((journaled_at-adapter_received).total_seconds()*1000,3),'ingest_compute_ms':round((ingest_done-provider_done)*1000,3),'event_to_adapter_receive_ms':round(adapter_latency_ms,3) if adapter_latency_ms is not None else None,'market_time_known':bool(sample.get('event_time')),'signal':result.get('calculation',{}).get('signal')}
   timings.update({k:v for k,v in (result.get('sqlite_timing') or {}).items() if k in ('begin_wait_ms','scope_entry_wait_ms','sqlite_begin_ms','work_before_commit_ms') and isinstance(v,(int,float))})
   telemetry=getattr(adapter,'last_telemetry',None)
   if isinstance(telemetry,dict):timings.update({k:telemetry[k] for k in ['eodhd_http_ms','pluto_context_ms','event_to_http_receive_ms','websocket_capture_ms','event_to_websocket_receive_ms'] if k in telemetry})
   diagnostics=getattr(adapter,'last_feed_diagnostics',None)
   if isinstance(diagnostics,dict):timings.update({k:diagnostics[k] for k in ('websocket_trade_status','websocket_quote_status','websocket_status_status','exchange_status','minute_bars_status','bar_history_status','intraday_status','intraday_cache_hit') if k in diagnostics})
   self.health(job,sample,None,timings)
   scan_log=('processed',result.get('calculation',{}).get('signal'),{**timings,'duplicate':bool(result.get('duplicate'))})
   if result.get('duplicate'):
    if (journaled_at-stamp(sample['event_time'])).total_seconds()>r['risk']['max_quote_age_s']:
     stale_duplicate=True;engine.fault(self.connect,uid,wid,mode,'DATA_STALE',lease=lease)
    else:engine.release(self.connect,job,journaled_at,sample=sample)
  except EngineError as error:
   if error.code=='FEED_COLLECTING' and getattr(error,'feed_ready',None) is not None:
    pending_feed=True
    with self.pending_lock:
     self.pending_feeds[job['id']]=error.feed_ready
     engine.release(self.connect,job,engine.utc(),pending_feed=True)
    scan_log=('deferred',error.code,{'websocket':getattr(adapter,'capture_metrics',[]),'provider_ms':round((time.perf_counter()-poll_started)*1000,3)})
    return 'deferred'
   if error.code in ['lease_lost','watch_not_running','kill_switch_active','operator_kill_switch']:
    scan_log=('cancelled',error.code,{});return True
   # A trade's phase can expire while its separately timestamped quote is
   # collected. Keep the verified quote as observation only; never ingest the
   # rejected trade or advance signal confirmation with it.
   if error.code=='market_status_evidence_stale' and isinstance(sample,dict) and sample.get('source')=='eodhd' and sample.get('verification')=='verified' and sample.get('asset_id')==r.get('asset_id') and str(sample.get('ticker','')).casefold()==str(r.get('ticker','')).casefold() and sample.get('currency')==r.get('quote_currency') and sample.get('quote_feed') in ('us_quotes','eu_quotes') and sample.get('bid') is not None and sample.get('ask') is not None and sample.get('bid_at') and sample.get('ask_at'):
    try:
     quote_time=min((sample['bid_at'],sample['ask_at']),key=stamp)
     self.partial(job,{'source':'eodhd','price':None,'currency':sample['currency'],'source_time':quote_time,'received_at':engine.utc().isoformat(),'quality':'QUOTE_ONLY','bid':sample['bid'],'ask':sample['ask']})
    except (ValueError,TypeError,KeyError):pass
   self.partials(job,adapter,getattr(error,'partial_observation',None))
   # Market-feed availability is independent of current broker ownership.
   # Only the read-only, budgeted Pluto adapter can provide this evidence;
   # unknown context is never promoted to verified or used as a market signal.
   feed_errors={'EODHD_DAILY_BUDGET','DATA_STALE','PROVIDER_RATE_BUDGET','EODHD_RATE_LIMIT','EODHD_READ_ERROR','EODHD_READ_OR_CONTRACT_ERROR','EODHD_ENTITLEMENT_REJECTED','EODHD_FEED_NOT_ENABLED','EODHD_KEY_NOT_CONFIGURED'}
   if error.code in feed_errors and getattr(error,'position_context',None) is None and r['provider']=='eodhd' and r.get('watch_mode')=='exit' and adapter is not None:
    try:context=adapter.pluto.safe_context(r,r.get('quote_currency'))
    except Exception:context=None
    if isinstance(context,dict) and context.get('status')=='verified' and context.get('as_of'):error.position_context=context
   if getattr(error,'position_context',None) is not None:
    try:engine.observe_context(self.connect,uid,wid,mode,error.position_context,lease=lease,broker_source='pluto' if r['provider']=='eodhd' else None)
    except EngineError as context_error:
     if context_error.code in ['lease_lost','watch_not_running','kill_switch_active','operator_kill_switch']:return True
     self.log(job,'context_rejected',context_error.code)
   captures=getattr(adapter,'capture_metrics',[])
   diagnostics={'websocket':captures if isinstance(captures,list) else [],'provider_ms':round((time.perf_counter()-poll_started)*1000,3)}
   feed_diagnostics=getattr(adapter,'last_feed_diagnostics',None)
   if isinstance(feed_diagnostics,dict):diagnostics.update({k:feed_diagnostics[k] for k in ('websocket_trade_status','websocket_quote_status','minute_bars_status','intraday_status','intraday_cache_hit') if k in feed_diagnostics})
   if error.code=='sample_id_conflict' and getattr(error,'market_conflict',None):diagnostics['market_conflict']=error.market_conflict
   engine.fault(self.connect,uid,wid,mode,error.code,lease=lease,retry_after_s=getattr(error,'retry_after_s',None));self.health(job,None,error.code);scan_log=('degraded',error.code,diagnostics)
  except Exception as error:
   code=processing_error_code(error)
   locks=None
   if code.startswith('PROCESSING_DATABASE_BUSY_'):
    from hotwatch_supervisor import database_locks
    locks=database_locks()
   try:
    engine.fault(self.connect,uid,wid,mode,code,lease=lease);self.health(job,None,code);scan_log=('degraded',code,{})
   finally:
    if locks is not None:
     from hotwatch_supervisor import record_database_locks
     record_database_locks(locks)
  finally:
   # The live scan and its risk decision finish first. Historical analysis
   # cannot create signals, and its failure cannot fault the live scan.
   if r['provider']=='eodhd' and not mode and not uses_realtime_history and not pending_feed:
    try:
     # A stale quote cannot produce an actionable signal. When other live
     # scans are already substantially overdue, defer this auxiliary history
     # fetch to a later scan so it does not occupy a worker ahead of them.
     if stale_duplicate or scan_log and scan_log[0]=='degraded' and scan_log[1]=='DATA_STALE':
      now_due=engine.utc().timestamp()
      with self.connect() as c:
       warmup_deferred=bool(c.execute("SELECT 1 FROM hw_sessions s JOIN users u ON u.id=s.user_id AND u.active=1 LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND s.id!=? AND s.next_due<=? AND s.lease_until<=? AND COALESCE(k.killed,0)=0 LIMIT 1",(job['id'],now_due-15,now_due)).fetchone())
     if not warmup_deferred:
      warmup_started=time.perf_counter()
      try:
       import hotwatch_warmup
       hotwatch_warmup.refresh(self.connect,job,engine.utc())
      finally:warmup_ms=round((time.perf_counter()-warmup_started)*1000,3)
    except Exception:logging.getLogger('escape.hotwatch').warning('historical warmup unavailable')
   if scan_log:
    status,code,metrics=scan_log
    self.log(job,status,code,{**metrics,'warmup_ms':warmup_ms,'warmup_deferred':warmup_deferred,'worker_busy_ms':round((time.perf_counter()-claim_started)*1000,3)})
  return True
 def partial(self,job,observation):
  if not isinstance(observation,dict):return
  try:engine.record_partial_observation(self.connect,job['user_id'],job['watch_id'],bool(job['is_test']),observation,lease=job['lease_owner'])
  except Exception:logging.getLogger('escape.hotwatch').warning('partial_observation_unavailable')
 def partials(self,job,adapter,observation=None):
  self.partial(job,observation)
  items=getattr(adapter,'last_partial_observations',None) if adapter is not None else None
  if isinstance(items,list):
   for item in items[:5]:self.partial(job,item)
 def health(self,job,sample,code,measurement=None):
  caps={'endpoint_access':True,'price_time':bool(sample.get('event_time')),'bid_ask':sample['bid'] is not None and sample['ask'] is not None,'interval_volume':sample['volume_type']=='interval','market_status':sample['market_status']!='UNKNOWN'} if sample else {}
  if measurement:caps.update(measurement)
  caps['worker_database_timing']=self.connect.database_metrics()
  caps['worker_settings']=worker_settings();caps['session_capacity']=engine.capacity()
  caps['parallel_scans_default']=2;caps['concurrency_default']=2
  now=engine.utc().isoformat()
  with self.connect() as c:c.execute('INSERT INTO hw_provider_health VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,is_test,source) DO UPDATE SET attempted=excluded.attempted,succeeded=COALESCE(excluded.succeeded,hw_provider_health.succeeded),code=excluded.code,payload=CASE WHEN excluded.succeeded IS NOT NULL THEN excluded.payload ELSE hw_provider_health.payload END',(job['user_id'],job['is_test'],job['request_data']['provider'],now,now if sample else None,code,json.dumps(caps)))
 def log(self,job,status,code,metrics=None):
  logging.getLogger('escape.hotwatch').info(json.dumps({'service':'hotwatch','user_id':job['user_id'],'is_test':bool(job['is_test']),'utc':engine.utc().isoformat(),'watch_ref':hashlib.sha256(job['watch_id'].encode()).hexdigest()[:16],'source':job['request_data']['provider'],'status':status,'code':code,'metrics':{**job.get('scan_timing',{}),**(metrics or {})}}))
 def drain(self,watch_id=None):
  """Keep each available worker busy without waiting for slower provider calls."""
  if watch_id:return int(self.once(watch_id=watch_id) is True)
  try:
   requested=int(os.environ.get('ESCAPE_HW_PARALLEL_SCANS','2'))
   lease_limit=int(os.environ.get('ESCAPE_HW_CONCURRENCY','2'))
  except (TypeError,ValueError):requested=1;lease_limit=1
  workers=max(1,min(10,engine.capacity(),requested,lease_limit))
  while len(self._workers)<workers-1:
   child=Runner(self.connect);child.stop=self.stop;child.brokers=self.brokers;child.broker_lock=self.broker_lock;child.pending_feeds=self.pending_feeds;child.pending_lock=self.pending_lock;self._workers.append(child)
  runners=[self]+self._workers[:workers-1];count=0;limit=engine.capacity()
  with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='hotwatch') as pool:
   pending={pool.submit(r.once):r for r in runners if not self.stop.is_set()};idle=[]
   while pending:
    # An empty claim is transient while another scan is running. Keep that
    # worker available for the next due job instead of retiring it until the
    # whole capacity-sized drain has finished. Use the existing 2s loop pace
    # when all remaining provider calls are slow; never busy-poll SQLite.
    finished,_=wait(pending,timeout=2,return_when=FIRST_COMPLETED)
    ready=[]
    for future in finished:
     runner=pending.pop(future);outcome=future.result()
     # A yielded feed claim has done no scan and consumes no round budget.
     # Its completion event excludes it from claims until data is available;
     # this worker can immediately try the next eligible deadline instead.
     count+=outcome is True
     (ready if outcome else idle).append(runner)
    if ready or not finished:
     ready.extend(idle);idle=[]
    for runner in ready:
     if count+len(pending)<limit and not self.stop.is_set():
      pending[pool.submit(runner.once)]=runner
  return count
 def heartbeat(self,status):
  with self.connect() as c:c.execute("INSERT INTO hw_heartbeat VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status",(engine.utc().isoformat(),status))
 def drain_safely(self):
  try:return self.drain()
  except sqlite3.OperationalError as error:
   code=getattr(error,'sqlite_errorcode',None)
   if not isinstance(code,int) or (code & 255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise
   from hotwatch_supervisor import diagnostic,database_locks,record_database_locks
   locks=database_locks()
   diagnostic('worker_database_busy',code)
   record_database_locks(locks)
   return 0
 def run(self,interval=2):
  if os.environ.get('ESCAPE_HW_AUTOSTART_ENABLED','1')=='1':
   with self.connect() as c:c.execute('INSERT OR IGNORE INTO hw_discovery_control VALUES(1,?)',(engine.utc().isoformat(),))
  def beat():
   while not self.stop.is_set():
    try:self.heartbeat('running')
    except Exception:logging.getLogger('escape.hotwatch').error(json.dumps({'service':'hotwatch','event':'heartbeat_error'}))
    self.stop.wait(HEARTBEAT_INTERVAL_S)
  thread=threading.Thread(target=beat,name='hotwatch-heartbeat',daemon=True);thread.start()
  def candidate_loop():
   while not self.stop.is_set():
    try:
     engine.reconcile_candidates(self.connect)
     reconcile_closed_holdings(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').exception('candidate_reconciliation_error')
    self.stop.wait(15)
  candidate_thread=threading.Thread(target=candidate_loop,name='hotwatch-candidates',daemon=True);candidate_thread.start()
  def holdings_loop():
   while not self.stop.is_set():
    try:
     from eodhd_capacity import refresh_account
     refresh_account(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').warning('eodhd_account_usage_unavailable')
    try:exchange_status_tick(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').error(json.dumps({'service':'hotwatch','event':'exchange_status_error'}))
    if self.stop.is_set():break
    try:auto_holdings_tick(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').error(json.dumps({'service':'hotwatch','event':'holdings_autowatch_error'}))
    try:recover_automatic_feeds(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').exception('automatic_feed_recovery_error')
    try:queue_unverified_automatic_feeds(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').exception('automatic_feed_recheck_queue_error')
    try:verify_provisional_feeds(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').exception('provisional_feed_verification_error')
    try:verify_cxe_feeds(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').exception('cxe_feed_verification_error')
    self.stop.wait(15)
  holding_thread=threading.Thread(target=holdings_loop,name='hotwatch-holdings',daemon=True);holding_thread.start()
  def sector_loop():
   while not self.stop.is_set():
    try:
     import sector_intelligence
     sector_intelligence.refresh_tick(self.connect)
    except Exception as error:logging.getLogger('escape.hotwatch').error('sector_refresh_error: %s',type(error).__name__)
    self.stop.wait(5)
  sector_thread=threading.Thread(target=sector_loop,name='sector-data',daemon=True);sector_thread.start()
  def discovery_loop():
   cursor=0
   while not self.stop.is_set():
    try:cursor=auto_discover(self.connect,cursor)
    except Exception:logging.getLogger('escape.hotwatch').exception('discovery_error')
    self.stop.wait(2)
  discovery_thread=threading.Thread(target=discovery_loop,name='hotwatch-discovery',daemon=True);discovery_thread.start()
  def push_loop():
   next_reconcile=0
   while not self.stop.is_set():
    try:
     import web_push
     if time.monotonic()>=next_reconcile:
      web_push.reconcile_stale(self.connect);next_reconcile=time.monotonic()+20
     if not web_push.dispatch_one(self.connect):self.stop.wait(3)
    except Exception:
     logging.getLogger('escape.hotwatch').error('push_dispatch_unavailable')
     self.stop.wait(10)
  push_thread=threading.Thread(target=push_loop,name='signal-notifications',daemon=True);push_thread.start()
  try:
   while not self.stop.is_set():
    self.drain_safely()
    self.stop.wait(interval)
  finally:
   self.stop.set();thread.join(timeout=6);holding_thread.join(timeout=2);candidate_thread.join(timeout=2);discovery_thread.join(timeout=2);sector_thread.join(timeout=2);push_thread.join(timeout=10)
   if thread.is_alive():logging.getLogger('escape.hotwatch').error(json.dumps({'service':'hotwatch','event':'heartbeat_shutdown_timeout'}))
   else:self.heartbeat('stopped')

def startup_diagnostics(connect):
 """Report configured paths without making an unbudgeted provider request."""
 from hotwatch_adapters import providers
 info=providers()
 info['startup_probe']={'network_requests_made':False,'note':'Provider entitlement is established only by a scheduled read; startup checks configuration, not account rights.'}
 eodhd=info['eodhd']
 eodhd['startup_status']='blocked_feed_disabled' if not eodhd['enabled'] else 'blocked_key_missing' if not eodhd['key_configured'] else 'configured_entitlement_unverified'
 info['pluto']['startup_status']='adapter_available_unprobed'
 info['report_inbox']['startup_status']='local_read_only'
 info['synthetic']['startup_status']='test_only'
 with connect() as c:
  sources=[row['provider'] for row in c.execute("SELECT DISTINCT json_extract(request,'$.provider') AS provider FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED')")]
 info['active_session_sources']=sources
 for source in sources:
  if source=='eodhd':
   p=info['eodhd']
   p['startup_status']='ready_to_probe_entitlement_unverified' if p['key_configured'] and p['enabled'] else 'blocked_configuration'
  elif source=='pluto':info['pluto']['startup_status']='probe_on_scheduled_read'
  elif source=='report_inbox':info['report_inbox']['startup_status']='local_read_only'
  elif source=='synthetic':info['synthetic']['startup_status']='test_only'
 logging.getLogger('escape.hotwatch').info(json.dumps({'service':'hotwatch','event':'startup_diagnostics','providers':info},sort_keys=True))
 return info

def probe_eodhd(connect,symbol,market,duration=2):
 """Explicit operator probe: bounded read-only requests and sanitized output."""
 from eodhd_feeds import EODHDFeeds
 from hotwatch_adapters import reserve
 client=EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),capacity=Capacity(connect))
 if market not in ('us','eu') or '.' not in symbol or (market=='us' and not symbol.endswith('.US')):return {'status':'INVALID_INPUT'}
 from hotwatch_adapters import realtime_symbol
 exchange=symbol.rsplit('.',1)[1];stream_symbol=realtime_symbol(symbol)
 end=int(time.time());actions=[('rest_snapshot',lambda:client.snapshot(symbol)),('minute_bars',lambda:client.minute_bars(market,stream_symbol)),('intraday',lambda:client.intraday(symbol,start=end-86400,end=end)),('market_status',lambda:client.market_status(exchange))]
 if market=='us':actions.append(('delayed_quotes',lambda:client.us_quotes(symbol)))
 for suffix in ('trades','quotes','status'):actions.append(('ws_'+suffix,lambda suffix=suffix:client.capture(market+'_'+suffix,stream_symbol,duration=duration)))
 checks={};limited=False
 for name,action in actions:
  checks[name]={'status':'NOT_TESTED_RATE_LIMIT'} if limited else action()
  if checks[name]['status'] in ('RATE_LIMIT','LOCAL_BUDGET_EXHAUSTED'):limited=True
 for value in checks.values():
  if value.get('event_time') and value.get('received_at'):value['event_to_receive_ms']=round((stamp(value['received_at'])-stamp(value['event_time'])).total_seconds()*1000,3)
  if 'bars' in value:
   bars=value.pop('bars');value['count']=len(bars);value['first_bar_at']=bars[0]['bar_open_at'] if bars else None;value['last_bar_at']=bars[-1]['bar_open_at'] if bars else None
  if 'messages' in value:
   messages=value.pop('messages');value['last_message']=messages[-1] if messages else None
 result={'symbol':symbol,'market':market,'checks':checks,'trading_enabled':False};secret=os.environ.get('ESCAPE_EODHD_API_KEY','').strip()
 def redact(value):
  if isinstance(value,str):return value.replace(secret,'[REDACTED]') if secret else value
  if isinstance(value,list):return [redact(x) for x in value]
  if isinstance(value,dict):return {k:redact(v) for k,v in value.items()}
  return value
 return redact(result)

def main():
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');parser.add_argument('--diagnose',action='store_true',help='report configured data paths without network requests');parser.add_argument('--probe-eodhd',metavar='SYMBOL',help='explicitly test EODHD feeds using read-only requests');parser.add_argument('--reset-candidates-for-user',type=int,metavar='USER_ID',help='explicitly reset running automatic entry-only candidate watches');parser.add_argument('--market',choices=['us','eu']);parser.add_argument('--capture-seconds',type=int,default=2);parser.add_argument('--watch-id',help='limit --once to one explicitly selected session');parser.add_argument('--interval',type=int,default=2);parser.add_argument('--kill-switch',choices=['on','off']);parser.add_argument('--reason',default='Local server operator');args=parser.parse_args()
 if not 1<=args.interval<=30:parser.error('interval must be 1..30 seconds')
 if args.probe_eodhd and (not args.market or not 1<=args.capture_seconds<=5):parser.error('--probe-eodhd requires --market and capture duration 1..5')
 if args.probe_eodhd and (args.once or args.diagnose or args.kill_switch or args.watch_id):parser.error('--probe-eodhd cannot be combined with actions')
 if args.reset_candidates_for_user is not None and (args.reset_candidates_for_user<1 or args.once or args.diagnose or args.probe_eodhd or args.kill_switch or args.watch_id):parser.error('--reset-candidates-for-user requires a positive user ID and no other action')
 if args.watch_id and not args.once:parser.error('--watch-id requires --once')
 logging.basicConfig(level=logging.INFO,format='%(message)s');app.init()
 if args.reset_candidates_for_user is not None:
  print(json.dumps(engine.reset_automatic_candidates(app.connect,args.reset_candidates_for_user),ensure_ascii=False));return
 if args.probe_eodhd:
  print(json.dumps(probe_eodhd(app.connect,args.probe_eodhd,args.market,args.capture_seconds)));return
 if args.kill_switch:
  print(json.dumps(engine.system_kill(app.connect,args.kill_switch=='on',args.reason)));return
 if args.diagnose:
  print(json.dumps(startup_diagnostics(app.connect),sort_keys=True));return
 try:configure_scan_log()
 except OSError:logging.getLogger('escape.hotwatch').warning('scan_log_unavailable')
 runner=Runner(app.connect)
 startup_diagnostics(app.connect)
 for name in [signal.SIGINT,signal.SIGTERM]:signal.signal(name,lambda *_:runner.stop.set())
 if args.once:
  with app.connect() as c:c.execute("INSERT INTO hw_heartbeat VALUES(1,?,'run_once') ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status",(engine.utc().isoformat(),))
  count=runner.drain(watch_id=args.watch_id)
  print(json.dumps({'service':'hotwatch','processed':count,'trading_enabled':False}))
 else:
  from hotwatch_supervisor import lock
  fd=lock("worker")
  if fd is None:
   print(json.dumps({"service":"hotwatch","error":"worker_already_running"}));return
  try:runner.run(args.interval)
  finally:os.close(fd)
def record_worker_exception(error):
 """Record class and local source location only, never exception text or values."""
 from hotwatch_supervisor import diagnostic
 classes=(sqlite3.OperationalError,sqlite3.IntegrityError,KeyError,ValueError,TypeError,AttributeError,RuntimeError,OSError)
 diagnostic('worker_exception',next((i for i,cls in enumerate(classes,1) if isinstance(error,cls)),0))
 if isinstance(error,sqlite3.Error):
  code=getattr(error,'sqlite_errorcode',None)
  diagnostic('worker_sqlite_error',code if isinstance(code,int) else None)
 frames=[];tb=error.__traceback__
 while tb:
  filename=os.path.basename(tb.tb_frame.f_code.co_filename)
  if filename in ('hotwatch_service.py','hotwatch_engine.py','app.py','hotwatch_adapters.py'):
   frames.append((filename,tb.tb_lineno))
  tb=tb.tb_next
 if frames:
  filename,line=frames[-1]
  names={'hotwatch_service.py':'service','hotwatch_engine.py':'engine','app.py':'app','hotwatch_adapters.py':'adapters'}
  diagnostic('worker_frame_'+names[filename],line)
 else:diagnostic('worker_frame_other')

if __name__=='__main__':
 try:main()
 except Exception as error:
  record_worker_exception(error)
  raise
