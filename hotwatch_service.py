"""Standalone read-only HOT WATCH service. Never scheduled by legacy worker.py."""
import json,signal,threading,logging,hashlib,time,os
from concurrent.futures import ThreadPoolExecutor
import app,hotwatch_engine as engine
from hotwatch_adapters import PlutoAdapter,EODHDAdapter,InboxAdapter,DataUnavailable
from hotwatch_contract import EngineError,stamp

HEARTBEAT_INTERVAL_S=5

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
   if isinstance(telemetry,dict):timings.update({k:telemetry[k] for k in ['eodhd_http_ms','pluto_context_ms','event_to_http_receive_ms'] if k in telemetry})
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
  try:
   while not self.stop.is_set():
    self.drain()
    self.stop.wait(interval)
  finally:
   self.stop.set();thread.join(timeout=6)
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

def main():
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');parser.add_argument('--diagnose',action='store_true',help='report configured data paths without network requests');parser.add_argument('--watch-id',help='limit --once to one explicitly selected session');parser.add_argument('--interval',type=int,default=2);parser.add_argument('--kill-switch',choices=['on','off']);parser.add_argument('--reason',default='Local server operator');args=parser.parse_args()
 if not 1<=args.interval<=30:parser.error('interval must be 1..30 seconds')
 if args.watch_id and not args.once:parser.error('--watch-id requires --once')
 logging.basicConfig(level=logging.INFO,format='%(message)s');app.init()
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
 else:runner.run(args.interval)
if __name__=='__main__':main()
