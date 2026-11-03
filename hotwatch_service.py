"""Standalone read-only HOT WATCH service. Never scheduled by legacy worker.py."""
import json,signal,threading,logging,hashlib
import app,hotwatch_engine as engine
from hotwatch_adapters import PlutoAdapter,EODHDAdapter,InboxAdapter,DataUnavailable
from hotwatch_contract import EngineError,stamp

class Runner:
 def __init__(self,connect):self.connect=connect;self.adapters={};self.stop=threading.Event()
 def once(self,now=None):
  now=now or engine.utc();job=engine.claim(self.connect,now)
  if not job:return False
  uid=job['user_id'];r=job['request_data'];wid=job['watch_id'];mode=bool(job['is_test']);lease=job['lease_owner']
  try:
   if r['end_at'] and stamp(r['end_at'])<=now:
    engine.fault(self.connect,uid,wid,mode,'WATCH_EXPIRED',now,lease);return True
   if r['provider']=='synthetic':
    if not job['last_data'] or (now-stamp(job['last_data'])).total_seconds()>r['risk']['max_quote_age_s']:raise DataUnavailable('DATA_STALE')
    engine.release(self.connect,job,now);return True
   key=(uid,r['provider']);adapter=self.adapters.get(key)
   if not adapter:
    adapter={'pluto':PlutoAdapter,'eodhd':EODHDAdapter,'report_inbox':InboxAdapter}[r['provider']](self.connect,uid);self.adapters[key]=adapter
   sample=adapter.poll(job);result=engine.ingest(self.connect,uid,wid,mode,sample,now=engine.utc(),lease=lease)
   self.health(job,sample,None)
   self.log(job,'processed',result.get('calculation',{}).get('signal'))
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
 def health(self,job,sample,code):
  caps={'endpoint_access':True,'price_time':bool(sample.get('event_time')),'bid_ask':sample['bid'] is not None and sample['ask'] is not None,'interval_volume':sample['volume_type']=='interval','market_status':sample['market_status']!='UNKNOWN'} if sample else {}
  now=engine.utc().isoformat()
  with self.connect() as c:c.execute('INSERT INTO hw_provider_health VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,is_test,source) DO UPDATE SET attempted=excluded.attempted,succeeded=COALESCE(excluded.succeeded,hw_provider_health.succeeded),code=excluded.code,payload=CASE WHEN excluded.succeeded IS NOT NULL THEN excluded.payload ELSE hw_provider_health.payload END',(job['user_id'],job['is_test'],job['request_data']['provider'],now,now if sample else None,code,json.dumps(caps)))
 def log(self,job,status,code):
  logging.getLogger('escape.hotwatch').info(json.dumps({'service':'hotwatch','utc':engine.utc().isoformat(),'watch_ref':hashlib.sha256(job['watch_id'].encode()).hexdigest()[:16],'source':job['request_data']['provider'],'status':status,'code':code}))
 def run(self,interval=2):
  try:
   while not self.stop.is_set():
    with self.connect() as c:c.execute("INSERT INTO hw_heartbeat VALUES(1,?,'running') ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status",(engine.utc().isoformat(),))
    for _ in range(engine.capacity()):
     if self.stop.is_set() or not self.once():break
    self.stop.wait(interval)
  finally:
   with self.connect() as c:c.execute("INSERT INTO hw_heartbeat VALUES(1,?,'stopped') ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status",(engine.utc().isoformat(),))

def main():
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');parser.add_argument('--interval',type=int,default=2);parser.add_argument('--kill-switch',choices=['on','off']);parser.add_argument('--reason',default='Local server operator');args=parser.parse_args()
 if not 1<=args.interval<=30:parser.error('interval must be 1..30 seconds')
 logging.basicConfig(level=logging.INFO,format='%(message)s');app.init()
 if args.kill_switch:
  print(json.dumps(engine.system_kill(app.connect,args.kill_switch=='on',args.reason)));return
 runner=Runner(app.connect)
 for name in [signal.SIGINT,signal.SIGTERM]:signal.signal(name,lambda *_:runner.stop.set())
 if args.once:
  with app.connect() as c:c.execute("INSERT INTO hw_heartbeat VALUES(1,?,'run_once') ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status",(engine.utc().isoformat(),))
  count=0
  while count<engine.capacity() and runner.once():count+=1
  print(json.dumps({'service':'hotwatch','processed':count,'trading_enabled':False}))
 else:runner.run(args.interval)
if __name__=='__main__':main()
