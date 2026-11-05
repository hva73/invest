"""Standalone read-only HOT WATCH service. Never scheduled by legacy worker.py."""
import json,signal,threading,logging,hashlib,time,os,re
from concurrent.futures import ThreadPoolExecutor
import app,hotwatch_engine as engine
from hotwatch_adapters import PlutoAdapter,EODHDAdapter,InboxAdapter,DataUnavailable
from hotwatch_contract import EngineError,stamp

HEARTBEAT_INTERVAL_S=5

def verified_discovery_instrument(connect,uid,candidate):
 """Verify a reported stable asset with Pluto's read-only get_asset tool."""
 import trade_service
 adapter=PlutoAdapter(connect,uid);client,tools=trade_service.client(connect,uid,adapter.factory)
 raw=trade_service.call(client,tools,'get_asset',{'assetId':candidate['asset_id']})
 asset=raw.get('asset') if isinstance(raw,dict) else None;buy=raw.get('buyBy') if isinstance(raw,dict) else None
 if not isinstance(asset,dict) or asset.get('id')!=candidate['asset_id'] or str(asset.get('ticker','')).casefold()!=candidate['ticker'].casefold():return None
 if candidate.get('exchange') and str(asset.get('exchange','')).casefold()!=candidate['exchange'].casefold():return None
 if not isinstance(buy,dict) or not (buy.get('shares') is True or buy.get('amount') is True):return None
 with connect() as c:portfolios=[dict(p) for p in c.execute("SELECT * FROM portfolios WHERE user_id=? AND active=1 AND source='pluto' AND kind='portfolio'",(uid,))]
 permitted=False
 for portfolio in portfolios:
  try:trade_service.fresh_permission(client,tools,connect,uid,portfolio);permitted=True;break
  except Exception:continue
 if not permitted:return None
 currency=asset.get('currency');isin=asset.get('isin');exchange=asset.get('exchange')
 if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency) or not isinstance(exchange,str) or not exchange or not isinstance(isin,str) or not re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',isin):return None
 return {'asset_id':asset['id'],'ticker':asset['ticker'],'exchange':exchange,'currency':currency,'isin':isin}

def auto_activate_candidate(connect,uid,mode,report,candidate,verify=None,lookup=None):
 """Start only a new, uniquely matched candidate; no order or purchase plan."""
 import candidate_lifecycle
 cid=candidate.get('candidate_id');asset=candidate.get('asset_id')
 if not cid or not asset or (candidate.get('decision') or {}).get('status')=='FRAVÆLG':return {'status':'IDENTITY_OR_DECISION_UNAVAILABLE'}
 with connect() as c:
  if c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0]:return {'status':'operator_kill_switch'}
  killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
  if killed and killed['killed']:return {'status':'kill_switch_active'}
  latest=candidate_lifecycle.latest(c,uid,mode,cid)
  if latest and latest['status'] not in ('DISCOVERED','ANALYZING','WAITING_TRIGGER'):return {'status':'NOT_NEW'}
  existing_cycle=latest['cycle_id'] if latest else None
  if c.execute('SELECT count(DISTINCT report_row_id) FROM report_candidate_links WHERE user_id=? AND is_test=? AND candidate_id=?',(uid,int(mode),cid)).fetchone()[0]!=1:return {'status':'NOT_NEW'}
  if c.execute("SELECT 1 FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=? AND status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')",(uid,int(mode),cid)).fetchone():return {'status':'ALREADY_ACTIVE'}
  if c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]>=engine.capacity():return {'status':'global_capacity_limit'}
  prior={row['asset'] for row in c.execute("SELECT json_extract(request,'$.asset_id') AS asset FROM hw_sessions WHERE user_id=? AND is_test=? AND candidate_id=?",(uid,int(mode),cid)) if row['asset']}
  link=c.execute('SELECT asset_id FROM market_asset_links WHERE user_id=? AND candidate_id=?',(uid,cid)).fetchone()
  if link:prior.add(link['asset_id'])
  if prior and prior!={asset}:return {'status':'IDENTITY_CONFLICT'}
 try:
  instrument=(verify or verified_discovery_instrument)(connect,uid,candidate)
  if not instrument or instrument.get('asset_id')!=asset or str(instrument.get('ticker','')).casefold()!=candidate.get('ticker','').casefold():return {'status':'PLUTO_VERIFICATION_REQUIRED'}
  from hotwatch_adapters import search_eodhd_symbols
  options=(lookup or search_eodhd_symbols)(connect,uid,{'report_id':report['report_id'],'candidate_id':cid,'is_test':mode,'quote_currency':instrument['currency']})
  matches=[x for x in options.get('choices',[]) if x.get('isin')==instrument['isin'] and x.get('currency')==instrument['currency']]
  if len(matches)!=1:return {'status':'EODHD_IDENTITY_UNCERTAIN'}
  watch='hw-auto-'+hashlib.sha256((str(uid)+'|'+str(int(mode))+'|'+cid).encode()).hexdigest()[:28]
  risk={'max_notional_dkk':'1000','max_loss_dkk':'100','max_spread_pct':'1','max_quote_age_s':120,'max_position_fraction_pct':'20','proposed_quantity':None,'stop_price':None,'exit_deadline':None}
  with connect() as c:portfolios=[dict(p) for p in c.execute("SELECT id,external_id,parent_external_id FROM portfolios WHERE user_id=? AND active=1 AND source='pluto' ORDER BY id",(uid,))]
  overlapping=any(a['external_id']==b.get('parent_external_id') for a in portfolios for b in portfolios)
  portfolio_ids=[p['id'] for p in portfolios] if len(portfolios)<=30 and not overlapping else []
  req={'watch_id':watch,'report_id':report['report_id'],'candidate_id':cid,'is_test':mode,'purpose':'automatic discovery','ticker':candidate['ticker'],'exchange':instrument['exchange'],'asset_id':asset,'quote_currency':instrument['currency'],'portfolio_ids':portfolio_ids,'priority':'NORMAL','profile':'NORMAL','provider':'eodhd','provider_symbol':matches[0]['symbol'],'end_at':None,'activation_reason':'Automatisk overvågning efter verificeret Pluto-aktiv og handelsbarhed','strategy_id':'escape_momentum','strategy_version':'1.0.0','risk':risk,'watch_mode':'entry'}
  if existing_cycle:req['trade_cycle_id']=existing_cycle
  result=engine.create(connect,uid,req);return {'status':'ACTIVE' if not result['duplicate'] else 'ALREADY_ACTIVE','watch_id':watch}
 except EngineError as error:return {'status':error.code}
 except Exception:return {'status':'DISCOVERY_VERIFICATION_FAILED'}

def auto_discover(connect,cursor=0):
 """Optional worker path, bounded by existing capacity and provider budgets."""
 if os.environ.get('ESCAPE_HW_AUTOSTART_ENABLED')!='1':return cursor
 try:after=stamp(os.environ.get('ESCAPE_HW_AUTOSTART_AFTER',''))
 except (ValueError,TypeError):return cursor
 with connect() as c:users=[row['id'] for row in c.execute('SELECT id FROM users WHERE active=1')]
 for uid in users:
  with connect() as c:row=c.execute("SELECT payload,received FROM ingested_reports WHERE user_id=? AND is_test=0 AND report_type!='deep_analysis' ORDER BY generated_epoch DESC,id DESC LIMIT 1",(uid,)).fetchone()
  if not row or stamp(row['received'])<=after:continue
  report=json.loads(row['payload'])
  candidates=report.get('candidates',[])
  if candidates:
   candidate=candidates[cursor%len(candidates)];result=auto_activate_candidate(connect,uid,False,report,candidate)
   if result['status'] not in ('NOT_NEW','ALREADY_ACTIVE'):
    logging.getLogger('escape.hotwatch').info(json.dumps({'service':'hotwatch','event':'discovery','candidate_ref':hashlib.sha256(str(candidate.get('candidate_id','')).encode()).hexdigest()[:16],'status':result['status']}))
 return cursor+1

def holding_instrument(connect,uid,holding):
 """Resolve the actual owned asset using Pluto's read-only identity endpoint."""
 import trade_service
 adapter=PlutoAdapter(connect,uid);client,tools=trade_service.client(connect,uid,adapter.factory)
 raw=trade_service.call(client,tools,'get_asset',{'assetId':holding['asset_id']})
 asset=raw.get('asset') if isinstance(raw,dict) else None
 if not isinstance(asset,dict) or asset.get('id')!=holding['asset_id']:return None
 currency=asset.get('currency');isin=asset.get('isin');exchange=asset.get('exchange');ticker=asset.get('ticker')
 if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency) or not isinstance(isin,str) or not re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',isin) or not isinstance(exchange,str) or not exchange or not isinstance(ticker,str) or not ticker:return None
 return {'asset_id':asset['id'],'ticker':ticker,'exchange':exchange,'currency':currency,'isin':isin}

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
   watch='hw-holding-'+hashlib.sha256((str(uid)+'|'+str(pid)+'|'+aid).encode()).hexdigest()[:28]
   prior=c.execute('SELECT status,watch_id,next_attempt FROM hw_holding_autowatch WHERE user_id=? AND portfolio_id=? AND asset_id=?',(uid,pid,aid)).fetchone()
   if len(active)==1:status='LINKED';linked=active[0]['watch_id']
   elif len(active)>1:status='AMBIGUOUS';linked=None
   elif prior and prior['status']=='STOPPED':status='STOPPED';linked=prior['watch_id']
   elif prior and prior['watch_id'] and any(row['watch_id']==prior['watch_id'] and row['status'] in ('COMPLETED','EXPIRED','ERROR') for row in matches):status='STOPPED';linked=prior['watch_id']
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
  with connect() as c:count=c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','PAUSED','DEGRADED')").fetchone()[0]
  if count>=engine.capacity():status='CAPACITY_LIMIT'
  elif os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1':status='EODHD_FEED_NOT_ENABLED'
  elif not os.environ.get('ESCAPE_EODHD_API_KEY','').strip():status='EODHD_KEY_NOT_CONFIGURED'
  else:
   instrument=(verify or holding_instrument)(connect,uid,holding)
   if instrument and instrument.get('asset_id')==aid:
    opts=(lookup or search_eodhd_symbols)(connect,uid,{'holding_portfolio_id':pid,'holding_asset_id':aid,'quote_currency':instrument['currency']})
    matches=[item for item in opts.get('choices',[]) if item.get('isin')==instrument.get('isin') and item.get('currency')==instrument.get('currency')]
    if len(matches)!=1:status='EODHD_IDENTITY_UNCERTAIN'
    else:
     cid='holding-'+hashlib.sha256((str(uid)+'|'+str(pid)+'|'+aid).encode()).hexdigest()[:28]
     risk={'max_notional_dkk':'1000','max_loss_dkk':'100','max_spread_pct':'1','max_quote_age_s':120,'max_position_fraction_pct':'20','proposed_quantity':None,'stop_price':None,'exit_deadline':None}
     req={'watch_id':watch,'report_id':'automatic-holdings','candidate_id':cid,'is_test':False,'purpose':'automatic holding watch','ticker':instrument['ticker'],'exchange':instrument['exchange'],'asset_id':aid,'quote_currency':instrument['currency'],'portfolio_ids':[pid],'priority':'NORMAL','profile':'NORMAL','provider':'eodhd','provider_symbol':matches[0]['symbol'],'end_at':None,'activation_reason':'Automatisk overvågning af verificeret Pluto-beholdning','strategy_id':'escape_momentum','strategy_version':'1.0.0','risk':risk,'watch_mode':'exit'}
     result=engine.create_holding(connect,uid,req,now);status='LINKED';linked=result['session']['watch_id']
 except EngineError as error:status=error.code
 except Exception:status='VERIFICATION_FAILED'
 with connect() as c:c.execute("UPDATE hw_holding_autowatch SET status=?,watch_id=?,next_attempt=?,updated=? WHERE user_id=? AND portfolio_id=? AND asset_id=?",(status,linked,epoch+300,engine.utc().isoformat(),uid,pid,aid))
 return status

class Runner:
 def __init__(self,connect):self.connect=connect;self.adapters={};self.stop=threading.Event();self._workers=[]
 def once(self,now=None,watch_id=None):
  now=now or engine.utc();job=engine.claim(self.connect,now,watch_id)
  if not job:return False
  uid=job['user_id'];r=job['request_data'];wid=job['watch_id'];mode=bool(job['is_test']);lease=job['lease_owner']
  try:
   poll_started=time.perf_counter()
   if r['end_at'] and stamp(r['end_at'])<=now:
    engine.fault(self.connect,uid,wid,mode,'WATCH_EXPIRED',now,lease);return True
   if r['provider']=='synthetic':
    if not job['last_data'] or (now-stamp(job['last_data'])).total_seconds()>r['risk']['max_quote_age_s']:raise DataUnavailable('DATA_STALE')
    engine.release(self.connect,job,now);return True
   key=(uid,r['provider']);adapter=self.adapters.get(key)
   if not adapter:
    adapter={'pluto':PlutoAdapter,'eodhd':EODHDAdapter,'report_inbox':InboxAdapter}[r['provider']](self.connect,uid);self.adapters[key]=adapter
   sample=adapter.poll(job);adapter_received=engine.utc();provider_done=time.perf_counter()
   adapter_latency_ms=(adapter_received-stamp(sample['event_time'])).total_seconds()*1000 if sample.get('event_time') else None
   result=engine.ingest(self.connect,uid,wid,mode,sample,now=engine.utc(),lease=lease)
   journaled_at=engine.utc();ingest_done=time.perf_counter()
   timings={'provider_ms':round((provider_done-poll_started)*1000,3),'adapter_to_journal_ms':round((journaled_at-adapter_received).total_seconds()*1000,3),'ingest_compute_ms':round((ingest_done-provider_done)*1000,3),'event_to_adapter_receive_ms':round(adapter_latency_ms,3) if adapter_latency_ms is not None else None,'market_time_known':bool(sample.get('event_time')),'signal':result.get('calculation',{}).get('signal')}
   telemetry=getattr(adapter,'last_telemetry',None)
   if isinstance(telemetry,dict):timings.update({k:telemetry[k] for k in ['eodhd_http_ms','pluto_context_ms','event_to_http_receive_ms','websocket_capture_ms','event_to_websocket_receive_ms'] if k in telemetry})
   diagnostics=getattr(adapter,'last_feed_diagnostics',None)
   if isinstance(diagnostics,dict):timings.update({k:diagnostics[k] for k in ('websocket_trade_status','websocket_quote_status','websocket_status_status','exchange_status','minute_bars_status','bar_history_status','intraday_status') if k in diagnostics})
   self.health(job,sample,None,timings)
   self.log(job,'processed',result.get('calculation',{}).get('signal'),{**timings,'duplicate':bool(result.get('duplicate'))})
   if result.get('duplicate'):
    if (now-stamp(sample['event_time'])).total_seconds()>r['risk']['max_quote_age_s']:engine.fault(self.connect,uid,wid,mode,'DATA_STALE',lease=lease)
    else:engine.release(self.connect,job,now)
  except EngineError as error:
   if error.code in ['lease_lost','watch_not_running','kill_switch_active','operator_kill_switch']:
    self.log(job,'cancelled',error.code);return True
   if getattr(error,'position_context',None) is not None:
    try:engine.observe_context(self.connect,uid,wid,mode,error.position_context,lease=lease)
    except EngineError as context_error:
     if context_error.code in ['lease_lost','watch_not_running','kill_switch_active','operator_kill_switch']:return True
     self.log(job,'context_rejected',context_error.code)
   engine.fault(self.connect,uid,wid,mode,error.code,lease=lease,retry_after_s=getattr(error,'retry_after_s',None));self.health(job,None,error.code);self.log(job,'degraded',error.code)
  except Exception:
   engine.fault(self.connect,uid,wid,mode,'PROVIDER_OR_PROCESSING_ERROR',lease=lease);self.health(job,None,'PROVIDER_OR_PROCESSING_ERROR');self.log(job,'degraded','PROVIDER_OR_PROCESSING_ERROR')
  return True
 def health(self,job,sample,code,measurement=None):
  caps={'endpoint_access':True,'price_time':bool(sample.get('event_time')),'bid_ask':sample['bid'] is not None and sample['ask'] is not None,'interval_volume':sample['volume_type']=='interval','market_status':sample['market_status']!='UNKNOWN'} if sample else {}
  if measurement:caps.update(measurement)
  now=engine.utc().isoformat()
  with self.connect() as c:c.execute('INSERT INTO hw_provider_health VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,is_test,source) DO UPDATE SET attempted=excluded.attempted,succeeded=COALESCE(excluded.succeeded,hw_provider_health.succeeded),code=excluded.code,payload=CASE WHEN excluded.succeeded IS NOT NULL THEN excluded.payload ELSE hw_provider_health.payload END',(job['user_id'],job['is_test'],job['request_data']['provider'],now,now if sample else None,code,json.dumps(caps)))
 def log(self,job,status,code,metrics=None):
  logging.getLogger('escape.hotwatch').info(json.dumps({'service':'hotwatch','utc':engine.utc().isoformat(),'watch_ref':hashlib.sha256(job['watch_id'].encode()).hexdigest()[:16],'source':job['request_data']['provider'],'status':status,'code':code,'metrics':metrics or {}}))
 def drain(self,watch_id=None):
  """Drain due work in bounded batches, opt-in for concurrent provider calls."""
  if watch_id:return int(self.once(watch_id=watch_id))
  try:
   requested=int(os.environ.get('ESCAPE_HW_PARALLEL_SCANS','1'))
   lease_limit=int(os.environ.get('ESCAPE_HW_CONCURRENCY','2'))
  except (TypeError,ValueError):requested=1;lease_limit=1
  workers=max(1,min(10,engine.capacity(),requested,lease_limit))
  while len(self._workers)<workers-1:
   child=Runner(self.connect);child.stop=self.stop;self._workers.append(child)
  runners=[self]+self._workers[:workers-1];count=0
  with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='hotwatch') as pool:
   while count<engine.capacity() and not self.stop.is_set():
    slots=min(workers,engine.capacity()-count)
    results=[f.result() for f in [pool.submit(runners[i].once) for i in range(slots)]]
    completed=sum(bool(x) for x in results);count+=completed
    if not completed:break
  return count
 def heartbeat(self,status):
  with self.connect() as c:c.execute("INSERT INTO hw_heartbeat VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status",(engine.utc().isoformat(),status))
 def run(self,interval=2):
  def beat():
   while not self.stop.is_set():
    try:self.heartbeat('running')
    except Exception:logging.getLogger('escape.hotwatch').error(json.dumps({'service':'hotwatch','event':'heartbeat_error'}))
    self.stop.wait(HEARTBEAT_INTERVAL_S)
  thread=threading.Thread(target=beat,name='hotwatch-heartbeat',daemon=True);thread.start()
  def holdings_loop():
   while not self.stop.is_set():
    try:auto_holdings_tick(self.connect)
    except Exception:logging.getLogger('escape.hotwatch').error(json.dumps({'service':'hotwatch','event':'holdings_autowatch_error'}))
    self.stop.wait(15)
  holding_thread=threading.Thread(target=holdings_loop,name='hotwatch-holdings',daemon=True);holding_thread.start()
  next_discovery=0;discovery_cursor=0
  try:
   while not self.stop.is_set():
    self.drain()
    if os.environ.get('ESCAPE_HW_AUTOSTART_ENABLED')=='1' and time.monotonic()>=next_discovery:
     try:discovery_cursor=auto_discover(self.connect,discovery_cursor)
     except Exception:logging.getLogger('escape.hotwatch').error(json.dumps({'service':'hotwatch','event':'discovery_error'}))
     next_discovery=time.monotonic()+15
    self.stop.wait(interval)
  finally:
   self.stop.set();thread.join(timeout=6);holding_thread.join(timeout=2)
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
 client=EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),reserve=lambda:reserve(connect,0,'eodhd'))
 if market not in ('us','eu') or '.' not in symbol or (market=='us' and not symbol.endswith('.US')):return {'status':'INVALID_INPUT'}
 exchange=symbol.rsplit('.',1)[1];stream_symbol=symbol[:-3] if market=='us' else symbol
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
 parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');parser.add_argument('--diagnose',action='store_true',help='report configured data paths without network requests');parser.add_argument('--probe-eodhd',metavar='SYMBOL',help='explicitly test EODHD feeds using read-only requests');parser.add_argument('--market',choices=['us','eu']);parser.add_argument('--capture-seconds',type=int,default=2);parser.add_argument('--watch-id',help='limit --once to one explicitly selected session');parser.add_argument('--interval',type=int,default=2);parser.add_argument('--kill-switch',choices=['on','off']);parser.add_argument('--reason',default='Local server operator');args=parser.parse_args()
 if not 1<=args.interval<=30:parser.error('interval must be 1..30 seconds')
 if args.probe_eodhd and (not args.market or not 1<=args.capture_seconds<=5):parser.error('--probe-eodhd requires --market and capture duration 1..5')
 if args.probe_eodhd and (args.once or args.diagnose or args.kill_switch or args.watch_id):parser.error('--probe-eodhd cannot be combined with actions')
 if args.watch_id and not args.once:parser.error('--watch-id requires --once')
 logging.basicConfig(level=logging.INFO,format='%(message)s');app.init()
 if args.probe_eodhd:
  print(json.dumps(probe_eodhd(app.connect,args.probe_eodhd,args.market,args.capture_seconds)));return
 if args.kill_switch:
  print(json.dumps(engine.system_kill(app.connect,args.kill_switch=='on',args.reason)));return
 if args.diagnose:
  print(json.dumps(startup_diagnostics(app.connect),sort_keys=True));return
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
if __name__=='__main__':main()
