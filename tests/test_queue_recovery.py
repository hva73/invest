"""Synthetic queue regressions: no market or broker network traffic."""
import copy,json,os,threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
import app,hotwatch_engine as engine,hotwatch_adapters as adapters
import test_hotwatch_engine as fixture
import test_post_install_capacity as capacity_fixture

class QueueRecovery(unittest.TestCase):
 def setUp(self):
  self.f=fixture.HotWatch();self.f.setUp();self.now=self.f.now
  adapters._ws_batch_cache.clear()
 def tearDown(self):
  adapters._ws_batch_cache.clear();self.f.tearDown()
 def add_exit(self,critical=False):
  r=copy.deepcopy(self.f.req);r.update(watch_id='exit-queue',purpose='exit queue fixture',watch_mode='exit')
  engine.create(app.connect,1,r,self.now)
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',(self.now.timestamp(),r['watch_id']))
   c.execute('UPDATE hw_sessions SET state=? WHERE watch_id=?',(json.dumps({'adaptive_profile':'CRITICAL' if critical else 'ACTIVE','scheduled_interval_s':5 if critical else 15}),r['watch_id']))
  return r
 def candidate_due(self,seconds,interval=15):
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET next_due=?,state=? WHERE watch_id=?',((self.now-timedelta(seconds=seconds)).timestamp(),json.dumps({'scheduled_interval_s':interval}),self.f.req['watch_id']))
 def test_candidate_missed_interval_precedes_new_critical_exit(self):
  self.add_exit(critical=True);self.candidate_due(16)
  self.assertEqual(engine.claim(app.connect,self.now)['watch_id'],self.f.req['watch_id'])
 def test_current_exit_has_priority_at_equal_deadline(self):
  r=self.add_exit(critical=True);self.candidate_due(0)
  self.assertEqual(engine.claim(app.connect,self.now)['watch_id'],r['watch_id'])
 def test_normal_candidate_does_not_wait_an_extra_scheduled_interval(self):
  self.add_exit();self.candidate_due(1,60)
  self.assertEqual(engine.claim(app.connect,self.now)['watch_id'],self.f.req['watch_id'])
 def test_overdue_exit_precedes_new_candidate(self):
  r=self.add_exit(critical=True);self.candidate_due(0)
  with app.connect() as c:c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',((self.now-timedelta(seconds=1)).timestamp(),r['watch_id']))
  self.assertEqual(engine.claim(app.connect,self.now)['watch_id'],r['watch_id'])
 def test_both_late_exit_and_candidate_are_oldest_due_first(self):
  r=self.add_exit(critical=True);self.candidate_due(30)
  with app.connect() as c:c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',((self.now-timedelta(seconds=40)).timestamp(),r['watch_id']))
  first=engine.claim(app.connect,self.now);second=engine.claim(app.connect,self.now)
  self.assertEqual([first['watch_id'],second['watch_id']],[r['watch_id'],self.f.req['watch_id']])
 def test_39_mixed_sessions_claim_oldest_deadline_with_two_leases(self):
  jobs=[capacity_fixture.LiveCapacity.add(self,'TEST'+str(i)+'.US',i,due=self.now.timestamp()-39+i) for i in range(39)]
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',(self.now.timestamp()+60,self.f.req['watch_id']))
   for job in jobs[1::2]:c.execute("UPDATE hw_sessions SET request=json_set(request,'$.watch_mode','exit'),state=json_set(state,'$.adaptive_profile','CRITICAL') WHERE id=?",(job['id'],))
  claimed=[]
  with patch.dict(os.environ,{'ESCAPE_HW_CONCURRENCY':'2'}):
   while len(claimed)<len(jobs):
    pair=[engine.claim(app.connect,self.now),engine.claim(app.connect,self.now)]
    pair=[job for job in pair if job]
    self.assertTrue(pair)
    if len(pair)==2:self.assertIsNone(engine.claim(app.connect,self.now))
    claimed.extend(job['id'] for job in pair)
    for job in pair:engine.release(app.connect,job,self.now)
  self.assertEqual(claimed,[job['id'] for job in jobs])
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_status_batch_reused_without_renewing_source_or_receive_time(self):
  req=dict(self.f.req,is_test=False);jobs=[{'id':123,'request_data':req,'state':'{}'} for _ in range(5)]
  calls=[];old=(self.now-timedelta(hours=6)).isoformat();received=self.now.isoformat()
  class Client:
   def capture(_,feed,symbol,**kwargs):
    calls.append(feed);time.sleep(.02)
    return {'status':'OK','messages':[{'symbol':'MERC','event_time':old,'received_at':received,'trading_status':'T'}]}
  client=Client();runner=adapters.EODHDAdapter(app.connect,1)
  with patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'queue-test'}),patch('hotwatch_adapters.utc',return_value=self.now):
   with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda j:runner.capture(client,'us_status','MERC',j),jobs))
   self.assertEqual(len(calls),1)
   for result in results:
    self.assertEqual(result['messages'][0]['event_time'],old)
    self.assertEqual(result['messages'][0]['received_at'],received)
   # The response cache expires normally; stale status is never upgraded.
   with patch('hotwatch_adapters.time.monotonic',return_value=time.monotonic()+21):runner.capture(client,'us_status','MERC',jobs[0])
   self.assertEqual(len(calls),2)
 def test_39_sessions_two_workers_share_bounded_status_captures(self):
  jobs=[capacity_fixture.LiveCapacity.add(self,'TEST'+str(i)+'.US',i,due=self.now.timestamp()-40+i) for i in range(39)]
  from hotwatch_service import serialized_database
  connect=serialized_database(app.connect);workers=[adapters.EODHDAdapter(connect,1) for _ in range(2)];calls=[];lock=threading.Lock()
  with connect() as c:
   for job in jobs[:22]:c.execute("UPDATE hw_sessions SET request=json_set(request,'$.watch_mode','exit') WHERE id=?",(job['id'],))
  old=(self.now-timedelta(hours=6)).isoformat()
  class Client:
   def capture(_,feed,symbols,**kwargs):
    if isinstance(symbols,str):symbols=[symbols]
    with lock:calls.append(len(symbols))
    time.sleep(.01)
    return {'status':'OK','messages':[{'symbol':s,'event_time':old,'received_at':self.now.isoformat(),'trading_status':'T'} for s in symbols]}
  def worker(i):
   for job in jobs[i::2]:
    symbol=job['request_data']['provider_symbol'].removesuffix('.US')
    value=workers[i].capture(Client(),'us_status',symbol,job)
    self.assertEqual(value['messages'][0]['event_time'],old)
    with connect() as c:c.execute('UPDATE hw_sessions SET next_due=? WHERE id=?',(self.now.timestamp()+60,job['id']))
  with patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'queue-test-39'}),patch('hotwatch_adapters.utc',return_value=self.now),patch('hotwatch_engine.verified_automatic_feed',return_value=True),ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(worker,range(2)))
  self.assertLessEqual(len(calls),6);self.assertLessEqual(sum(calls),60)
  with connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_empty_worker_rejoins_when_other_scan_completes(self):
  import hotwatch_service as service
  runner=service.Runner(app.connect);empty=threading.Event();resumed=threading.Event();release=threading.Event();calls={};errors=[]
  def once(worker):
   calls[worker]=calls.get(worker,0)+1
   if worker is runner:
    if calls[worker]==1:empty.wait(2);return True
    release.wait(3);return False
   if calls[worker]==1:empty.set();return False
   resumed.set();return False
  def run():
   try:runner.drain()
   except Exception as error:errors.append(error)
  with patch.dict(os.environ,{'ESCAPE_HW_PARALLEL_SCANS':'2','ESCAPE_HW_CONCURRENCY':'2'}),patch.object(service.Runner,'once',once):
   thread=threading.Thread(target=run);thread.start()
   try:self.assertTrue(resumed.wait(1),'worker retired after a transient empty queue')
   finally:release.set();thread.join(4)
  self.assertFalse(thread.is_alive());self.assertFalse(errors)
 def test_idle_worker_rechecks_due_queue_while_other_provider_stays_blocked(self):
  import hotwatch_service as service
  runner=service.Runner(app.connect);empty=threading.Event();resumed=threading.Event();release=threading.Event();calls={};errors=[]
  def once(worker):
   calls[worker]=calls.get(worker,0)+1
   if worker is runner:release.wait(5);return False
   if calls[worker]==1:empty.set();return False
   resumed.set();return False
  def run():
   try:runner.drain()
   except Exception as error:errors.append(error)
  with patch.dict(os.environ,{'ESCAPE_HW_PARALLEL_SCANS':'2','ESCAPE_HW_CONCURRENCY':'2'}),patch.object(service.Runner,'once',once):
   thread=threading.Thread(target=run);thread.start()
   try:
    self.assertTrue(empty.wait(1));self.assertTrue(resumed.wait(3),'idle worker did not resume while the provider was blocked')
    self.assertEqual(sum(calls.values()),3,'empty claims must not busy-poll')
   finally:release.set();thread.join(4)
  self.assertFalse(thread.is_alive());self.assertFalse(errors)
 def test_old_status_cannot_override_unknown_trade_session(self):
  from test_post_install_capacity import ENV
  now=self.now;adapter=adapters.EODHDAdapter(None,1,opener=object())
  req=dict(self.f.req,provider='eodhd',provider_symbol='MERC.US')
  class Feeds:
   def capture(_,feed,symbol,**kwargs):
    row={'event_time':now.isoformat(),'price':'100','market_session':'unknown'} if feed.endswith('trades') else {'event_time':now.isoformat(),'bid':'99.9','ask':'100.1'} if feed.endswith('quotes') else {'event_time':(now-timedelta(hours=6)).isoformat(),'trading_status':'T'}
    return {'status':'OK','messages':[row]}
  with patch.dict(os.environ,{**ENV,'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'queue-test'}),patch('hotwatch_adapters.utc',return_value=now),patch.object(adapter,'feeds',return_value=Feeds()),patch.object(adapter.pluto,'safe_context',return_value=adapters.unknown_context()):
   sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['market_status'],'UNKNOWN');self.assertNotIn('status_at',sample)
 def test_overdue_candidates_are_in_batch_before_newly_due_holdings(self):
  add=lambda symbol,n,due:capacity_fixture.LiveCapacity.add(self,symbol,n,due=due)
  candidate=add('OLD.US',1,self.now.timestamp()-30)
  for i in range(11):
   job=add('H'+str(i)+'.US',i+2,self.now.timestamp())
   with app.connect() as c:c.execute("UPDATE hw_sessions SET request=json_set(request,'$.watch_mode','exit') WHERE id=?",(job['id'],))
  adapter=adapters.EODHDAdapter(app.connect,1);calls=[]
  class Client:
   def capture(_,feed,symbols,**kwargs):
    calls.append(symbols);return {'status':'NO_MESSAGES','messages':[]}
  with patch('hotwatch_adapters.utc',return_value=self.now),patch('hotwatch_engine.verified_automatic_feed',return_value=True):
   adapter.capture(Client(),'us_trades','H10',job)
   adapter.capture(Client(),'us_trades','OLD',candidate)
  self.assertEqual(len(calls),1);self.assertIn('OLD',calls[0]);self.assertEqual(len(calls[0]),10)

if __name__=='__main__':unittest.main()
