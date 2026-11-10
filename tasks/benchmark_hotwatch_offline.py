"""Offline review harness. Real Runner/SQLite, fake market transport, no network."""
import sys,os,json,time,copy,tempfile,threading,resource,statistics,socket
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import app,report_ingest,hotwatch_engine as engine,hotwatch_service as service
from hotwatch_contract import checksum
from eodhd_capacity import Capacity
from test_hotwatch_engine import request,tick
from test_intel_workflows import merc_report

def percentile(v,p):
 return round(sorted(v)[min(len(v)-1,int((len(v)-1)*p))],3) if v else None

def run(n,workers,delay):
 with tempfile.TemporaryDirectory() as temp,patch.object(app,'DB',temp+'/audit.db'),patch.dict(os.environ,{'ESCAPE_HW_CAPACITY':str(n),'ESCAPE_HW_PARALLEL_SCANS':str(workers),'ESCAPE_HW_CONCURRENCY':str(workers),'ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'0','ESCAPE_EODHD_API_KEY':'offline-audit','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'},clear=True),patch.object(socket,'create_connection',side_effect=AssertionError('Network forbidden')):
  app.init();app.create_user('offline-audit-password');report_ingest.save(app.connect,1,merc_report(True))
  req=request();engine.create(app.connect,1,req)
  with app.connect() as c:
   base=dict(c.execute('SELECT * FROM hw_sessions').fetchone());c.execute('DELETE FROM hw_events');c.execute('DELETE FROM hw_sessions')
   for i in range(n):
    r=copy.deepcopy(req);r.update(watch_id='audit-'+str(i),purpose='audit '+str(i),candidate_id='audit-candidate-'+str(i),provider='eodhd',provider_symbol='MERC.US',watch_mode='exit' if i%3==0 else 'entry',report_id='manual-pluto')
    row=dict(base,watch_id=r['watch_id'],purpose=r['purpose'],candidate_id=r['candidate_id'],request=json.dumps(r),digest=checksum(r));row.pop('id')
    columns=list(row);c.execute('INSERT INTO hw_sessions('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[row[k] for k in columns])
   mode=c.execute('PRAGMA journal_mode').fetchone()[0];timeout=c.execute('PRAGMA busy_timeout').fetchone()[0]
  transactions=[];sql_times=[];records=[];errors=[];guard=threading.Lock();stopped=threading.Event()
  def connect():
   c=app.connect()
   def trace(sql):
    if sql.upper().startswith('BEGIN'):
     with guard:transactions.append(time.perf_counter())
   c.set_trace_callback(trace);return c
  class FakeAdapter:
   def __init__(self,connect,uid):self.connect=connect;self.pluto=object()
   def poll(self,job):
    start=time.perf_counter();at=engine.utc();cap=Capacity(self.connect)
    cap.reserve(1);cap.observe(200,{},delay*1000)
    for _ in range(3):
     with cap.websocket(1):pass
    time.sleep(delay)
    sample=tick(engine.utc(),time.monotonic_ns(),held=job['request_data']['watch_mode']=='exit',price='94' if job['watch_id']=='audit-0' else '100');sample['source']='eodhd'
    with guard:records.append({'watch':job['watch_id'],'held':sample['context']['position']=='held','due':job['next_due'],'due_to_poll_ms':(at.timestamp()-job['next_due'])*1000,'poll_s':time.perf_counter()-start})
    return sample
  runner=service.Runner(connect)
  def background():
   while not stopped.wait(.5):
    try:
     runner.heartbeat('running')
     started=time.perf_counter();engine.sync(connect,1,True,session_limit=10,summary_only=True);sql_times.append((time.perf_counter()-started)*1000)
    except Exception as e:errors.append(type(e).__name__+':'+str(e))
  thread=threading.Thread(target=background);thread.start()
  with app.connect() as c:c.execute('UPDATE hw_sessions SET next_due=?',(engine.utc().timestamp(),))
  start=time.perf_counter();cpu=time.process_time()
  try:
   # Explicit capacity applies only to this disposable offline fixture.
   with patch.object(service,'EODHDAdapter',FakeAdapter):processed=runner.drain()
  finally:stopped.set();thread.join()
  elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu
  with app.connect() as c:
   calculations=[json.loads(r[0]) for r in c.execute('SELECT payload FROM hw_calculations')]
   proposals=c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0]
   unique=c.execute('SELECT count(DISTINCT watch_row_id) FROM hw_calculations').fetchone()[0]
   faults=[dict(r) for r in c.execute('SELECT watch_id,last_error FROM hw_sessions WHERE last_error IS NOT NULL')]
  result={'sessions':n,'workers':workers,'fake_provider_delay_s':delay,'processed':processed,'unique_evaluated':unique,'elapsed_s':round(elapsed,3),'throughput_per_min':round(len(calculations)*60/elapsed,2),'cpu_s':round(cpu,3),'peak_rss_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),'queue_delay_p95_ms':percentile([r['due_to_poll_ms'] for r in records],.95),'queue_delay_max_ms':percentile([r['due_to_poll_ms'] for r in records],1),'queue_over_60_s':sum(r['due_to_poll_ms']>60000 for r in records),'status_read_p95_ms':percentile(sql_times,.95),'begun_transactions_including_reads':len(transactions),'transactions_per_scan_including_background':round(len(transactions)/max(1,len(calculations)),2),'db_timing':runner.connect.database_metrics(),'sell':sum(c['signal']=='SELL' for c in calculations),'held_evaluations':sum(r['held'] for r in records),'buy':sum(c['signal']=='BUY' for c in calculations),'proposals':proposals,'faults':faults,'background_errors':errors,'journal_mode':mode,'busy_timeout_ms':timeout}
  print(json.dumps(result),flush=True)
  return result

if __name__=='__main__':
 if len(sys.argv)>1:run(int(sys.argv[1]),int(sys.argv[2]),float(sys.argv[3]))
 else:
  import subprocess
  for delay,counts in [(.25,[40,60,100,150]),(3,[40])]:
   for n in counts:
    for workers in (1,2,4,6):subprocess.run([sys.executable,__file__,str(n),str(workers),str(delay)],check=True)
