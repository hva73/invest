"""Shared feed regression tests; all provider/broker traffic is synthetic."""
import copy,hashlib,json,os,threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock,patch
import app,hotwatch_adapters as adapters,hotwatch_engine as engine,hotwatch_service as service
import test_hotwatch_engine as fixture
import test_post_install_capacity as capacity_fixture

class FeedReuse(unittest.TestCase):
 def setUp(self):
  self.f=fixture.HotWatch();self.f.setUp();self.now=self.f.now
  self.req=dict(self.f.req,is_test=False,provider='eodhd',provider_symbol='MERC.US')
  self.job={'id':123,'request_data':self.req,'state':'{}'}
  self.adapter=adapters.EODHDAdapter(app.connect,1)
  self.env=patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'feed-reuse','ESCAPE_HW_CONCURRENCY':'2'});self.env.start()
  self.clock=patch('hotwatch_adapters.utc',return_value=self.now);self.clock.start()
  self.credential=hashlib.sha256(b'feed-reuse').digest()
  adapters._ws_batch_cache.clear();adapters._ws_batch_inflight.clear()
 def tearDown(self):
  adapters._ws_batch_cache.clear();adapters._ws_batch_inflight.clear()
  self.clock.stop();self.env.stop();self.f.tearDown()
 def cached(self,symbol='MERC',feed='us_trades',source_age=10,cache_age=0,uid=1):
  at=(self.now-timedelta(seconds=source_age)).isoformat()
  message={'symbol':symbol,'event_time':at,'received_at':at,'price':'100','market_session':'open'}
  adapters._ws_batch_cache[(uid,self.credential,feed,symbol)]=(time.monotonic()-cache_age,{'status':'OK','messages':[message]})
  return message
 def busy(self,feed='us_trades'):
  # Old implementation would block here; fail promptly instead of hanging.
  pending=Mock();pending.wait.side_effect=AssertionError('worker blocked behind shared capture')
  adapters._ws_batch_inflight[(1,self.credential,feed)]=pending
  return pending
 def test_fresh_observation_is_used_while_another_capture_is_running(self):
  message=self.cached(cache_age=21);pending=self.busy();client=Mock()
  result=self.adapter.capture(client,'us_trades','MERC',self.job)
  self.assertEqual(result['messages'],[message]);client.capture.assert_not_called();pending.wait.assert_not_called()
  self.assertEqual(adapters._ws_batch_cache[(1,self.credential,'us_trades','MERC')][1]['messages'],[message])
 def test_stale_or_future_observation_is_never_promoted_during_capture(self):
  pending=self.busy();client=Mock()
  for age in (121,-1):
   self.cached(source_age=age)
   result=self.adapter.capture(client,'us_trades','MERC',self.job)
   self.assertEqual(result['status'],'COLLECTING');self.assertEqual(result['messages'],[])
   self.assertFalse(self.adapter.capture_metrics[-1]['cache_hit']);self.assertEqual(self.adapter.capture_metrics[-1]['capture_attempts'],0)
  client.capture.assert_not_called();pending.wait.assert_not_called()
 def test_cache_does_not_cross_user_or_credentials(self):
  self.cached(uid=2);self.busy();client=Mock()
  self.assertEqual(self.adapter.capture(client,'us_trades','MERC',self.job)['status'],'COLLECTING')
  self.cached()
  with patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'another-key'}):
   client.capture.return_value={'status':'NO_MESSAGES','messages':[]}
   self.assertEqual(self.adapter.capture(client,'us_trades','MERC',self.job)['status'],'NO_MESSAGES')
  client.capture.assert_called_once()
 def test_batches_skip_reusable_symbols_and_fill_with_missing_observations(self):
  jobs=[capacity_fixture.LiveCapacity.add(self,'TEST'+str(i)+'.US',i,due=self.now.timestamp()-30+i) for i in range(20)]
  originals=[self.cached('TEST'+str(i)) for i in range(10)]
  client=Mock();client.capture.return_value={'status':'NO_MESSAGES','messages':[]}
  with patch('hotwatch_engine.verified_automatic_feed',return_value=True):
   self.adapter.capture(client,'us_trades','TEST19',jobs[-1])
  symbols=client.capture.call_args.args[1]
  self.assertEqual(set(symbols),{'TEST'+str(i) for i in range(10,20)})
  for i,message in enumerate(originals):
   self.assertEqual(adapters._ws_batch_cache[(1,self.credential,'us_trades','TEST'+str(i))][1]['messages'],[message])
 def test_failed_leader_releases_collection_for_a_retry(self):
  client=Mock();client.capture.side_effect=RuntimeError('synthetic failure')
  with self.assertRaises(RuntimeError):self.adapter.capture(client,'us_trades','MERC',self.job)
  self.assertEqual(adapters._ws_batch_inflight,{})
  client.capture.side_effect=None;client.capture.return_value={'status':'NO_MESSAGES','messages':[]}
  self.assertEqual(self.adapter.capture(client,'us_trades','MERC',self.job)['status'],'NO_MESSAGES')
 def test_fresh_normal_cache_observation_reused_for_existing_poll_cadence(self):
  self.job['request_data']=dict(self.req,profile='NORMAL')
  message=self.cached(cache_age=25,source_age=30);client=Mock()
  client.capture.return_value={'status':'NO_MESSAGES','messages':[]}
  result=self.adapter.capture(client,'us_trades','MERC',self.job)
  self.assertEqual(result['messages'],[message]);client.capture.assert_not_called()
  self.assertEqual(result['messages'][0]['received_at'],message['received_at'])
  self.assertEqual(result['messages'][0]['event_time'],message['event_time'])
  # Cadence reuse cannot extend the freshness threshold.
  self.cached(cache_age=25,source_age=121)
  client.capture.return_value={'status':'NO_MESSAGES','messages':[]}
  self.assertEqual(self.adapter.capture(client,'us_trades','MERC',self.job)['status'],'NO_MESSAGES')
  client.capture.assert_called_once()
 def test_collection_completion_event_is_shared_and_set_after_failure(self):
  entered=threading.Event();release=threading.Event()
  class Client:
   def capture(_,feed,symbol,**kwargs):
    entered.set();release.wait(2);raise RuntimeError('synthetic failure')
  with ThreadPoolExecutor(max_workers=1) as pool:
   future=pool.submit(self.adapter.capture,Client(),'us_trades','MERC',self.job)
   try:
    self.assertTrue(entered.wait(1))
    other=adapters.EODHDAdapter(app.connect,1)
    result=other.capture(Client(),'us_trades','MISSING',self.job)
    self.assertEqual(result['status'],'COLLECTING');self.assertFalse(other.pending_feed.is_set())
   finally:release.set()
   with self.assertRaisesRegex(RuntimeError,'synthetic failure'):future.result(timeout=1)
  self.assertTrue(other.pending_feed.is_set());self.assertEqual(adapters._ws_batch_inflight,{})
 def test_deferred_attempt_does_not_consume_completed_scan_budget(self):
  runner=service.Runner(app.connect)
  with patch.dict(os.environ,{'ESCAPE_HW_PARALLEL_SCANS':'1'}),patch.object(engine,'capacity',return_value=2),patch.object(service.Runner,'once',side_effect=['deferred',True,True]) as once:
   self.assertEqual(runner.drain(),2)
  self.assertEqual(once.call_count,3)
 def test_pending_feed_yields_lease_without_hiding_deadline_or_faulting(self):
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET request=json_set(request,'$.provider','eodhd'),status='ACTIVE' WHERE watch_id=?",(self.f.req['watch_id'],))
  runner=service.Runner(app.connect);adapter=Mock()
  event=threading.Event();failure=adapters.DataUnavailable('FEED_COLLECTING');failure.feed_ready=event
  adapter.poll.side_effect=failure;adapter.capture_metrics=[]
  runner.adapters[(1,'eodhd')]=adapter;runner.health=Mock();runner.log=Mock()
  with app.connect() as c:before=dict(engine.row_for(c,1,self.f.req['watch_id'],True))
  with patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_warmup.refresh') as warmup:
   self.assertEqual(runner.once(self.now,watch_id=self.f.req['watch_id']),'deferred')
   # Elapsed wall time must not cause another failed claim for the same
   # collection. Completion, not a fixed retry timer, makes it eligible.
   self.assertFalse(runner.once(self.now+timedelta(seconds=10),watch_id=self.f.req['watch_id']))
   adapter.poll.assert_called_once()
  with app.connect() as c:after=dict(engine.row_for(c,1,self.f.req['watch_id'],True))
  for key in ('next_due','last_data','last_calculation','failures','last_error','status','state'):
   self.assertEqual(after[key],before[key],key)
  self.assertIsNone(after['lease_owner']);self.assertEqual(after['lease_until'],0)
  runner.health.assert_not_called();warmup.assert_not_called()
  self.assertIsNone(engine.claim(app.connect,self.now,watch_id=self.f.req['watch_id'],exclude_ids=tuple(runner.pending_feeds)))
  # Waiting without an owner must not consume a worker's concurrency slot.
  jobs=[capacity_fixture.LiveCapacity.add(self,'FREE'+str(i)+'.US',i,due=self.now.timestamp()) for i in range(2)]
  with app.connect() as c:
   for job in jobs:c.execute('UPDATE hw_sessions SET lease_owner=NULL,lease_until=0 WHERE id=?',(job['id'],))
  claimed=[engine.claim(app.connect,self.now,exclude_ids=tuple(runner.pending_feeds)),engine.claim(app.connect,self.now,exclude_ids=tuple(runner.pending_feeds))]
  self.assertEqual({j['id'] for j in claimed},{j['id'] for j in jobs})
  self.assertIsNone(engine.claim(app.connect,self.now))
  for job in claimed:engine.release(app.connect,job,self.now)
  event.set()
  with patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_warmup.refresh'):
   self.assertEqual(runner.once(self.now,watch_id=self.f.req['watch_id']),'deferred')
  self.assertEqual(adapter.poll.call_count,2)
  with app.connect() as c:self.assertEqual(engine.row_for(c,1,self.f.req['watch_id'],True)['next_due'],before['next_due'])
 def test_pending_quote_keeps_actual_trade_for_independent_exit(self):
  from hotwatch_strategy import BASELINE,calculate
  context=fixture.tick(self.now,held=True)['context']
  client=Mock()
  def capture(feed,*args,**kwargs):
   if feed.endswith('trades'):return {'status':'OK','messages':[{'symbol':'MERC','price':'100','event_time':self.now.isoformat(),'received_at':self.now.isoformat(),'market_session':'open'}]}
   return {'status':'COLLECTING','messages':[]}
  # Exercise the existing poll-to-strategy path, not a fabricated decision.
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}),patch.object(self.adapter,'capture',side_effect=capture),patch.object(self.adapter,'feeds',return_value=client),patch.object(self.adapter.pluto,'safe_context',return_value=context):
   sample=self.adapter.poll(self.job)
  self.assertEqual(sample['event_time'],self.now.isoformat());self.assertIsNone(sample['bid'])
  risk=dict(self.req['risk'],stop_price='101')
  result,_=calculate(sample,fixture.good_metrics(),BASELINE,risk,{},self.now)
  self.assertEqual(result['signal'],'SELL');self.assertIn('STOP_BREACHED',result['reason_codes'])
  sample['context']=fixture.tick(self.now)['context']
  result,_=calculate(sample,fixture.good_metrics(),BASELINE,risk,{},self.now)
  self.assertNotEqual(result['signal'],'BUY')
  client.capture.assert_not_called()
 def test_slow_capture_does_not_block_cached_work_on_second_worker(self):
  entered=threading.Event();release=threading.Event();calls=[]
  message=self.cached('READY',cache_age=21)
  class Client:
   def capture(_,feed,symbols,**kwargs):
    calls.append(feed);entered.set();release.wait(3)
    return {'status':'NO_MESSAGES','messages':[]}
  with ThreadPoolExecutor(max_workers=2) as pool:
   leader=pool.submit(self.adapter.capture,Client(),'us_trades','MERC',self.job)
   try:
    self.assertTrue(entered.wait(1))
    ready=pool.submit(self.adapter.capture,Client(),'us_trades','READY',self.job)
    self.assertEqual(ready.result(timeout=.5)['messages'],[message])
    missing=pool.submit(self.adapter.capture,Client(),'us_trades','MISSING',self.job)
    self.assertEqual(missing.result(timeout=.5)['status'],'COLLECTING')
    self.assertEqual(calls,['us_trades'])
   finally:release.set()
   leader.result(timeout=2)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_two_real_workers_reach_ready_exit_while_shared_trade_is_blocked(self):
  entered=threading.Event();release=threading.Event();ready=threading.Event();errors=[];records=[];calls=[]
  jobs=[capacity_fixture.LiveCapacity.add(self,symbol+'.US',i,due=self.now.timestamp()-3+i) for i,symbol in enumerate(('SLOW','MISSING','READY'))]
  self.cached('READY',cache_age=21)
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',(self.now.timestamp()+60,self.f.req['watch_id']))
   c.execute("UPDATE hw_sessions SET request=json_set(request,'$.watch_mode','exit','$.risk.stop_price','101') WHERE id=?",(jobs[2]['id'],))
  class Feeds:
   def capture(_,feed,symbols,**kwargs):
    calls.append(feed)
    if isinstance(symbols,str):symbols=[symbols]
    if feed=='us_trades':entered.set();release.wait(3)
    rows=[dict(symbol=s,event_time=self.now.isoformat(),received_at=self.now.isoformat(),price='100',market_session='open',bid='99.99',ask='100.01',trading_status='T') for s in symbols]
    return {'status':'OK','messages':rows}
  def logged(worker,job,status,code,metrics=None):
   records.append((job['watch_id'],status,code))
   if job['id']==jobs[2]['id'] and status=='processed':ready.set()
  runner=service.Runner(app.connect)
  def run():
   try:runner.drain()
   except Exception as error:errors.append(error)
  env={'ESCAPE_HW_PARALLEL_SCANS':'2','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  with patch.dict(os.environ,env),patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_engine.verified_automatic_feed',return_value=True),patch.object(adapters.EODHDAdapter,'feeds',return_value=Feeds()),patch.object(adapters.PlutoAdapter,'safe_context',return_value=fixture.tick(self.now,held=True)['context']),patch.object(service.Runner,'log',logged),patch('hotwatch_warmup.refresh'):
   thread=threading.Thread(target=run);thread.start()
   try:
    self.assertTrue(entered.wait(1));self.assertTrue(ready.wait(1),'ready exit blocked behind unrelated feed collection')
    self.assertIn((jobs[2]['watch_id'],'processed','SELL'),records)
    self.assertIn((jobs[1]['watch_id'],'deferred','FEED_COLLECTING'),records)
   finally:release.set();thread.join(4)
  self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
  self.assertEqual(calls.count('us_trades'),1)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_one_drain_completes_39_distinct_sessions_despite_deferred_claims(self):
  jobs=[capacity_fixture.LiveCapacity.add(self,'QUEUE'+str(i)+'.US',i,due=self.now.timestamp()-40+i) for i in range(39)]
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',(self.now.timestamp()+60,self.f.req['watch_id']))
   for job in jobs[::2]:c.execute("UPDATE hw_sessions SET request=json_set(request,'$.watch_mode','exit') WHERE id=?",(job['id'],))
  records=[];captures=[]
  class Feeds:
   def capture(_,feed,symbols,**kwargs):
    if isinstance(symbols,str):symbols=[symbols]
    captures.append((feed,tuple(symbols)));time.sleep(.02)
    return {'status':'OK','messages':[dict(symbol=s,event_time=self.now.isoformat(),received_at=self.now.isoformat(),price='100',market_session='open',bid='99.99',ask='100.01',trading_status='T') for s in symbols]}
  def logged(worker,job,status,code,metrics=None):records.append((job['id'],status))
  runner=service.Runner(app.connect)
  env={'ESCAPE_HW_PARALLEL_SCANS':'2','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  with patch.dict(os.environ,env),patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_engine.verified_automatic_feed',return_value=True),patch.object(adapters.EODHDAdapter,'feeds',return_value=Feeds()),patch.object(adapters.PlutoAdapter,'safe_context',return_value=fixture.tick(self.now,held=True)['context']),patch.object(service.Runner,'log',logged),patch('hotwatch_warmup.refresh'):
   count=runner.drain()
  self.assertTrue(any(status=='deferred' for _,status in records))
  self.assertEqual(count,39);self.assertEqual({ident for ident,status in records if status=='processed'},{j['id'] for j in jobs})
  self.assertFalse(any(status=='degraded' for _,status in records))
  self.assertLessEqual(len(captures),15)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)

if __name__=='__main__':unittest.main()
