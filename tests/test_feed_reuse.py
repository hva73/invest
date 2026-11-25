"""Shared feed regression tests; all provider/broker traffic is synthetic."""
import copy,hashlib,json,os,threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock,patch
from eodhd_feeds import EODHDFeeds
import app,hotwatch_adapters as adapters,hotwatch_engine as engine,hotwatch_service as service
from test_eodhd_feeds import WS
import test_hotwatch_engine as fixture
import test_post_install_capacity as capacity_fixture

class FeedReuse(unittest.TestCase):
 def setUp(self):
  self.f=fixture.HotWatch();self.f.setUp();self.now=self.f.now
  self.req=dict(self.f.req,is_test=False,provider='eodhd',provider_symbol='MERC.US')
  self.job={'id':123,'request_data':self.req,'state':'{}'}
  self.adapter=adapters.EODHDAdapter(app.connect,1)
  self.env=patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'feed-reuse','ESCAPE_HW_CONCURRENCY':'2','ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'0'});self.env.start()
  self.clock=patch('hotwatch_adapters.utc',return_value=self.now);self.clock.start()
  self.credential=hashlib.sha256(b'feed-reuse').digest()
  adapters._ws_batch_cache.clear();adapters._ws_batch_inflight.clear()
 def tearDown(self):
  adapters._ws_batch_cache.clear();adapters._ws_batch_inflight.clear()
  self.clock.stop();self.env.stop();self.f.tearDown()
 def test_six_quiet_empty_lookups_cost_two_instead_of_six(self):
  adapters._quiet_intraday_empty.clear();calls=[]
  def fetch():calls.append(1);return {'status':'NO_DATA'}
  for second in (0,60,120,180,240,300):
   with patch('hotwatch_adapters.time.monotonic',return_value=1000+second):adapters.quiet_intraday_lookup('feed-reuse','MERC.US','old',True,fetch)
  self.assertEqual(len(calls),2) # Five-minute expiry: 2 instead of 6 calls.
  adapters._quiet_intraday_empty.clear()
 def test_closed_market_empty_intraday_cache_wakes_for_new_data(self):
  adapters._quiet_intraday_empty.clear();calls=[]
  def fetch():calls.append(1);return {'status':'NO_DATA','received_at':'original'}
  first,hit=adapters.quiet_intraday_lookup('feed-reuse','MERC.US','old',True,fetch);self.assertFalse(hit)
  second,hit=adapters.quiet_intraday_lookup('feed-reuse','MERC.US','old',True,fetch);self.assertTrue(hit);self.assertEqual(second['received_at'],'original');self.assertEqual(len(calls),1)
  adapters.quiet_intraday_lookup('feed-reuse','MERC.US','new',True,fetch)
  adapters.quiet_intraday_lookup('feed-reuse','MERC.US','old',False,fetch)
  self.assertEqual(len(calls),3)
  adapters._quiet_intraday_empty.clear()
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
 def shared_job(self,uid,symbol='MERC.US',isin='US1234567890',session=None):
  with app.connect() as c:
   c.execute("INSERT OR IGNORE INTO users(id,username,role,active) VALUES(?,?,'member',1)",(uid,f'shared-fixture-{uid}'))
  if session is None:
   self._shared_seq=getattr(self,'_shared_seq',10000)+1
   # Real persisted sessions; keep synthetic subscribers outside the due
   # batch until explicitly polled so capture counts remain attributable.
   session=capacity_fixture.LiveCapacity.add(self,symbol,self._shared_seq,user=uid,due=self.now.timestamp()+3600)
  job=dict(session)
  req=dict(job['request_data'],asset_id=f'asset-{uid}-{symbol}',provider_symbol=symbol,ticker=symbol.split('.')[0])
  if not symbol.endswith('.US'):req.update(exchange=symbol.rsplit('.',1)[1],quote_currency='EUR')
  job['request_data']=req
  with app.connect() as c:
   if isin:
    c.execute('INSERT OR REPLACE INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',
              (uid,req['asset_id'],req['ticker'],req['quote_currency'],req['exchange'],symbol,isin,self.now.timestamp()))
   c.execute('UPDATE hw_sessions SET request=? WHERE id=? AND user_id=?',(json.dumps(req),job['id'],uid))
  return job
 def shared_client(self,key='feed-reuse'):
  def capture(feed,symbols,**kwargs):
   at=self.now.isoformat()
   return {'status':'OK','messages':[{'symbol':symbol,'event_time':at,'received_at':at,'price':'100','market_session':'open'}
                                    for symbol in ([symbols] if isinstance(symbols,str) else symbols)]}
  client=EODHDFeeds(key)
  client.capture=Mock(side_effect=capture)
  return client
 def test_cross_user_capture_counts_at_1_10_and_100_subscribers(self):
  jobs=[self.shared_job(uid) for uid in range(1,101)]
  subscribers=[adapters.EODHDAdapter(app.connect,uid) for uid in range(1,101)]
  for size in (1,10,100):
   for enabled in ('0','1'):
    with self.subTest(size=size,enabled=enabled),patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':enabled}):
     adapters._ws_batch_cache.clear()
     factory=Mock(side_effect=lambda *args,**kwargs:WS([{'s':'MERC','t':int(self.now.timestamp()*1000),'p':100}]))
     client=EODHDFeeds('feed-reuse',ws_factory=factory)
     results=[adapter.capture(client,'us_trades','MERC',job) for adapter,job in zip(subscribers[:size],jobs)]
     self.assertEqual(len(results),size)
     self.assertEqual([r['messages'][0]['price'] for r in results],['100']*size)
     self.assertEqual(factory.call_count,1 if enabled=='1' else size)
     self.assertEqual(len(adapters._ws_batch_cache),1 if enabled=='1' else size)
     if enabled=='1' and size>1:
      self.assertTrue(all(r['messages']==results[0]['messages'] for r in results))
      results[0]['messages'][0]['price']='999'
      self.assertEqual(subscribers[1].capture(client,'us_trades','MERC',jobs[1])['messages'][0]['price'],'100')
 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_cross_user_overlap_reuses_batch_without_recruiting_other_users(self):
  local=capacity_fixture.LiveCapacity.add(self,'MSFT.US',1)
  self.shared_job(1,'MSFT.US',session=local)
  first=self.shared_job(1)
  second=self.shared_job(2,'MSFT.US')
  disjoint=self.shared_job(2,'AMD.US')
  other=adapters.EODHDAdapter(app.connect,2)
  client=self.shared_client()
  self.adapter.capture(client,'us_trades','MERC',first)
  self.assertEqual(other.capture(client,'us_trades','MSFT',second)['messages'][0]['symbol'],'MSFT')
  self.assertEqual(other.capture(client,'us_trades','AMD',disjoint)['messages'][0]['symbol'],'AMD')
  self.assertEqual([call.args[1] for call in client.capture.call_args_list],[['MERC','MSFT'],'AMD'])
 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_cross_user_identity_feed_credential_and_test_scope_are_isolated(self):
  first,second=self.shared_job(1),self.shared_job(2)
  other=adapters.EODHDAdapter(app.connect,2)
  client=self.shared_client()
  self.adapter.capture(client,'us_trades','MERC',first)
  denied=self.shared_client('different-account')
  denied.capture.side_effect=None
  denied.capture.return_value={'status':'ENTITLEMENT_UNVERIFIED','messages':[]}
  for _ in range(2):
   self.assertEqual(other.capture(denied,'us_trades','MERC',second)['status'],'ENTITLEMENT_UNVERIFIED')
  self.assertEqual(denied.capture.call_count,1)
  other.capture(client,'us_quotes','MERC',second)
  other.capture(client,'us_trades','MERC',{**second,'request_data':dict(second['request_data'],is_test=True)})
  other.capture(client,'us_trades','MERC',{**second,'is_test':True})
  unseen=adapters.EODHDAdapter(app.connect,3)
  unseen.capture(client,'us_trades','MERC',self.shared_job(3,isin=None))
  unseen.capture(client,'us_trades','MERC',self.shared_job(3,isin='US1234567891'))
  self.assertEqual(client.capture.call_count,6)
  self.assertEqual(other.capture(client,'us_trades','MERC',second)['status'],'OK')
  self.assertEqual(client.capture.call_count,6)
  with app.connect() as c:
   c.execute('UPDATE hw_verified_feed_links SET verified_epoch=0 WHERE user_id=2')
  other.capture(client,'us_trades','MERC',second)
  self.assertEqual(client.capture.call_count,7)
 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_shared_capture_requires_persisted_tenant_watch_and_current_request(self):
  first,second=self.shared_job(1),self.shared_job(2)
  other=adapters.EODHDAdapter(app.connect,2)
  client=self.shared_client()
  self.adapter.capture(client,'us_trades','MERC',first)
  with app.connect() as c:
   self.assertIsNotNone(other.shared_stream_identity(c,second['request_data'],second['id']))
   self.assertIsNone(other.shared_stream_identity(c,second['request_data'],first['id']))
   self.assertIsNone(other.shared_stream_identity(c,dict(second['request_data'],profile='CRITICAL'),second['id']))
  forged=dict(second,id=first['id'])
  other.capture(client,'us_trades','MERC',forged)
  self.assertEqual(client.capture.call_count,2)  # no shared cache reuse
  other.capture(client,'us_trades','MERC',second)
  self.assertEqual(client.capture.call_count,2)
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET status='EXPIRED' WHERE id=?",(second['id'],))
   self.assertIsNone(other.shared_stream_identity(c,second['request_data'],second['id']))
 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_cross_user_concurrent_capture_defers_only_the_matching_instrument(self):
  started,finish=threading.Event(),threading.Event()
  client=self.shared_client()
  capture=client.capture.side_effect
  def blocked(feed,symbols,**kwargs):
   if symbols=='MERC':
    started.set()
    if not finish.wait(5):raise AssertionError('test did not unblock capture')
   return capture(feed,symbols,**kwargs)
  client.capture.side_effect=blocked
  first,second,disjoint=self.shared_job(1),self.shared_job(2),self.shared_job(2,'AMD.US')
  other=adapters.EODHDAdapter(app.connect,2)
  with ThreadPoolExecutor(max_workers=1) as pool:
   leader=pool.submit(self.adapter.capture,client,'us_trades','MERC',first)
   try:
    self.assertTrue(started.wait(5))
    self.assertEqual(other.capture(client,'us_trades','MERC',second)['status'],'COLLECTING')
    ready=other.pending_feed
    self.assertFalse(ready.is_set())
    self.assertEqual(other.capture(client,'us_trades','AMD',disjoint)['status'],'OK')
   finally:finish.set()
   self.assertEqual(leader.result(timeout=5)['status'],'OK')
  self.assertTrue(ready.is_set())
  self.assertEqual(other.capture(client,'us_trades','MERC',second)['status'],'OK')
  self.assertEqual(client.capture.call_count,2)
  self.assertFalse(adapters._ws_batch_inflight)
 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_cross_user_expiry_retry_and_cache_bound(self):
  first,second=self.shared_job(1),self.shared_job(2)
  other=adapters.EODHDAdapter(app.connect,2)
  client=self.shared_client()
  capture=client.capture.side_effect
  with patch('hotwatch_adapters.time.monotonic',return_value=100):
   self.adapter.capture(client,'us_trades','MERC',first)
  with patch('hotwatch_adapters.time.monotonic',return_value=161):
   client.capture.side_effect=[RuntimeError('synthetic failure'),{'status':'NO_MESSAGES','messages':[]},capture('us_trades','MERC')]
   with self.assertRaisesRegex(RuntimeError,'synthetic failure'):
    other.capture(client,'us_trades','MERC',second)
   self.assertEqual(other.capture(client,'us_trades','MERC',second)['status'],'NO_MESSAGES')
   self.assertEqual(other.capture(client,'us_trades','MERC',second)['status'],'NO_MESSAGES')
   self.assertEqual(client.capture.call_count,3)
  client.capture.side_effect=capture
  with patch('hotwatch_adapters.time.monotonic',return_value=176):
   self.assertEqual(other.capture(client,'us_trades','MERC',second)['status'],'OK')
   with patch('hotwatch_adapters.utc',return_value=self.now+timedelta(seconds=121)):
    other.capture(client,'us_trades','MERC',second)
  self.assertEqual(client.capture.call_count,5)
  client.capture.side_effect=None
  client.capture.return_value={'status':'NO_MESSAGES','messages':[]}
  for index in range(513):
   symbol=f'BOUND{index}'
   self.adapter.capture(client,'us_trades',symbol,self.shared_job(1,symbol+'.US'))
   self.assertLessEqual(len(adapters._ws_batch_cache),512)
  self.assertFalse(adapters._ws_batch_inflight)
 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_cross_user_availability_counts_and_expiry(self):
  subscribers=[adapters.EODHDAdapter(app.connect,uid) for uid in range(1,101)]
  overlap=[self.shared_job(uid) for uid in range(1,101)]
  disjoint=[self.shared_job(uid,f'DISTINCT{uid}.US') for uid in range(1,101)]
  partial={'symbol':'MERC','price':'100','received_at':self.now.isoformat()}
  outcomes=[
   ('NO_MESSAGES',{'status':'NO_MESSAGES','messages':[]}),
   ('INCOMPLETE',{'status':'NO_MESSAGES','messages':[],'partial_messages':[partial]}),
   ('ENTITLEMENT_UNVERIFIED',{'status':'ENTITLEMENT_UNVERIFIED','messages':[]}),
   ('NETWORK_OR_RESPONSE_ERROR',{'status':'NETWORK_OR_RESPONSE_ERROR','messages':[]}),
  ]
  for size in (1,10,100):
   for jobs,expected in ((overlap,1),(disjoint,size)):
    for status,response in outcomes:
     with self.subTest(size=size,distinct=jobs is disjoint,status=status):
      adapters._ws_batch_cache.clear()
      client=self.shared_client()
      def capture(feed,stream,**kwargs):
       if status=='INCOMPLETE':return dict(response,partial_messages=[dict(partial,symbol=stream)])
       return response
      client.capture.side_effect=capture
      for second,count in ((100,expected),(114,expected),(115,2*expected)):
       with patch('hotwatch_adapters.time.monotonic',return_value=second):
        for adapter,job in zip(subscribers[:size],jobs):
         stream=adapters.realtime_symbol(job['request_data']['provider_symbol'])
         result=adapter.capture(client,'us_trades',stream,job)
         self.assertEqual(result['status'],status)
         self.assertEqual(result['messages'],[])
         if status=='INCOMPLETE':self.assertEqual(result['partial_messages'],[dict(partial,symbol=stream)])
       self.assertEqual(client.capture.call_count,count)
       self.assertEqual(len(adapters._ws_batch_cache),expected)

 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_shared_quiet_does_not_cross_credential_feed_or_test_scope(self):
  first,second=self.shared_job(1),self.shared_job(2)
  other=adapters.EODHDAdapter(app.connect,2)
  client=self.shared_client()
  original=client.capture.side_effect
  client.capture.side_effect=[{'status':'NO_MESSAGES','messages':[]},original('us_quotes','MERC'),original('us_trades','MERC')]
  self.assertEqual(self.adapter.capture(client,'us_trades','MERC',first)['status'],'NO_MESSAGES')
  self.assertEqual(other.capture(self.shared_client('other-fixture'),'us_trades','MERC',second)['status'],'OK')
  self.assertEqual(other.capture(client,'us_quotes','MERC',second)['status'],'OK')
  self.assertEqual(other.capture(client,'us_trades','MERC',dict(second,is_test=True))['status'],'OK')
  self.assertEqual(other.capture(client,'us_trades','MERC',second)['status'],'NO_MESSAGES')
  self.assertEqual(client.capture.call_count,3)

 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_eu_quiet_exchange_and_symbol_collision(self):
  first=self.shared_job(1,'SAME.XETRA',isin='DE1234567890')
  same=self.shared_job(2,'SAME.XETRA',isin='DE1234567890')
  venue=self.shared_job(2,'SAME.AS',isin='DE1234567890')
  client=self.shared_client()
  original=client.capture.side_effect
  client.capture.side_effect=lambda feed,stream,**kw: (
   {'status':'NO_MESSAGES','messages':[]} if stream=='SAME.XETRA' else original(feed,stream,**kw))
  other=adapters.EODHDAdapter(app.connect,2)
  self.assertEqual(self.adapter.capture(client,'eu_trades','SAME.XETRA',first)['status'],'NO_MESSAGES')
  self.assertEqual(other.capture(client,'eu_trades','SAME.XETRA',same)['status'],'NO_MESSAGES')
  self.assertEqual(other.capture(client,'eu_trades','SAME.AS',venue)['messages'][0]['symbol'],'SAME.AS')
  self.assertEqual([call.args[1] for call in client.capture.call_args_list],['SAME.XETRA','SAME.AS'])
  self.assertEqual(len(adapters._ws_batch_cache),2)

 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1'})
 def test_quiet_probe_keeps_prior_timestamps_and_allows_freshness_retry(self):
  first,strict,ahead=(self.shared_job(uid) for uid in (1,2,3))
  strict['request_data']['risk']['max_quote_age_s']=5
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(strict['request_data']),strict['id']))
   ahead['last_data']=(self.now-timedelta(seconds=1)).isoformat()
   c.execute('UPDATE hw_sessions SET last_data=? WHERE id=?',(ahead['last_data'],ahead['id']))
  second,third=(adapters.EODHDAdapter(app.connect,uid) for uid in (2,3))
  client=self.shared_client()
  old=(self.now-timedelta(seconds=10)).isoformat()
  message={'symbol':'MERC','event_time':old,'received_at':old,'price':'100'}
  newer=dict(message,event_time=self.now.isoformat(),received_at=self.now.isoformat())
  client.capture.side_effect=[
   {'status':'OK','messages':[message]},
   {'status':'NO_MESSAGES','messages':[]},
   {'status':'OK','messages':[newer]},
  ]
  with patch('hotwatch_adapters.time.monotonic',return_value=100):
   self.assertEqual(self.adapter.capture(client,'us_trades','MERC',first)['messages'],[message])
   self.assertEqual(second.capture(client,'us_trades','MERC',strict)['status'],'NO_MESSAGES')
   self.assertEqual(third.capture(client,'us_trades','MERC',ahead)['status'],'NO_MESSAGES')
   self.assertEqual(self.adapter.capture(client,'us_trades','MERC',first)['messages'],[message])
   self.assertEqual(client.capture.call_count,2)
  with patch('hotwatch_adapters.time.monotonic',return_value=115):
   self.assertEqual(third.capture(client,'us_trades','MERC',ahead)['messages'],[newer])
   self.assertEqual(second.capture(client,'us_trades','MERC',strict)['messages'],[newer])
   self.assertEqual(client.capture.call_count,3)
 @patch.dict(os.environ,{'ESCAPE_HW_EODHD_CROSS_USER_WS_ENABLED':'1',
                         'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1',
                         'ESCAPE_HW_EODHD_FUSE_ENABLED':'0'})
 def test_cross_user_poll_only_shares_market_data(self):
  client=self.shared_client()
  contexts=[{'position':'held','quantity':'3','orders':['user-1']},
            {'position':'none','quantity':'0','orders':[]}]
  results=[]
  for uid,context in enumerate(contexts,1):
   adapter=adapters.EODHDAdapter(app.connect,uid)
   job=self.shared_job(uid)
   self.assertEqual(adapter.pluto.uid,uid)
   with patch.object(adapter.pluto,'safe_context',return_value=context) as broker,patch.object(adapter,'feeds',return_value=client),patch.object(adapter,'interval',return_value=60):
    results.append(adapter.poll(job))
    broker.assert_called_once_with(job['request_data'],'USD')
  self.assertEqual(client.capture.call_count,1)
  self.assertEqual([sample['context'] for sample in results],contexts)
  self.assertNotEqual(results[0]['asset_id'],results[1]['asset_id'])
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
 def test_quiet_symbols_share_stale_capture_response_without_refreshing_prices(self):
  jobs=[capacity_fixture.LiveCapacity.add(self,'QUIET'+str(i)+'.US',i,due=self.now.timestamp()-40+i) for i in range(39)]
  calls=[];old=(self.now-timedelta(minutes=5)).isoformat()
  class Client:
   def capture(_,feed,symbols,**kwargs):
    if isinstance(symbols,str):symbols=[symbols]
    calls.append(tuple(symbols))
    return {'status':'OK','messages':[{'symbol':s,'event_time':old,'received_at':self.now.isoformat(),'price':'100'} for s in symbols]}
  with patch('hotwatch_engine.verified_automatic_feed',return_value=True):
   for job in jobs:
    result=self.adapter.capture(Client(),'us_trades',job['request_data']['provider_symbol'].removesuffix('.US'),job)
    self.assertEqual(len(result['messages']),1)
    self.assertEqual(result['messages'][0]['event_time'],old)
    self.assertEqual(result['messages'][0]['received_at'],self.now.isoformat())
   self.assertEqual(len(calls),4)
   self.assertEqual(sum(map(len,calls)),39)
   # Quiet responses expire on the existing ACTIVE cadence, not on the
   # event's timestamp. No permanent suppression of a newly arriving trade.
   with patch('hotwatch_adapters.time.monotonic',return_value=time.monotonic()+16),patch('hotwatch_adapters.utc',return_value=self.now+timedelta(seconds=16)):
    self.adapter.capture(Client(),'us_trades','QUIET0',jobs[0])
  self.assertEqual(len(calls),5)
 def test_trade_that_expires_after_capture_is_refetched(self):
  client=Mock();old=(self.now-timedelta(seconds=119)).isoformat()
  client.capture.return_value={'status':'OK','messages':[{'symbol':'MERC','event_time':old,'received_at':self.now.isoformat(),'price':'100'}]}
  self.adapter.capture(client,'us_trades','MERC',self.job)
  later=self.now+timedelta(seconds=2)
  client.capture.return_value={'status':'OK','messages':[{'symbol':'MERC','event_time':later.isoformat(),'received_at':later.isoformat(),'price':'101'}]}
  with patch('hotwatch_adapters.utc',return_value=later):result=self.adapter.capture(client,'us_trades','MERC',self.job)
  self.assertEqual(client.capture.call_count,2);self.assertEqual(result['messages'][0]['price'],'101')
 def test_quiet_quote_feed_reuses_brief_negative_then_detects_new_quote(self):
  job=dict(self.job,request_data=dict(self.req,profile='NORMAL'))
  client=Mock();old=(self.now-timedelta(minutes=5)).isoformat()
  client.capture.return_value={'status':'OK','messages':[{'symbol':'MERC','event_time':old,'received_at':self.now.isoformat(),'price':'100'}]}
  self.adapter.capture(client,'us_quotes','MERC',job)
  with patch('hotwatch_adapters.time.monotonic',return_value=time.monotonic()+25):
   result=self.adapter.capture(client,'us_quotes','MERC',job)
   self.assertEqual(result['messages'][0]['event_time'],old);self.assertEqual(client.capture.call_count,1)
  later=self.now+timedelta(seconds=31)
  client.capture.return_value={'status':'OK','messages':[{'symbol':'MERC','event_time':later.isoformat(),'received_at':later.isoformat(),'price':'101'}]}
  with patch('hotwatch_adapters.time.monotonic',return_value=time.monotonic()+31),patch('hotwatch_adapters.utc',return_value=later):
   result=self.adapter.capture(client,'us_quotes','MERC',job)
  self.assertEqual(client.capture.call_count,2);self.assertEqual(result['messages'][0]['event_time'],later.isoformat())
 def test_quiet_trade_feed_keeps_twenty_second_refresh_limit(self):
  job=dict(self.job,request_data=dict(self.req,profile='NORMAL'));client=Mock()
  old=(self.now-timedelta(minutes=5)).isoformat()
  client.capture.return_value={'status':'OK','messages':[{'symbol':'MERC','event_time':old,'received_at':self.now.isoformat(),'price':'100'}]}
  self.adapter.capture(client,'us_trades','MERC',job)
  later=self.now+timedelta(seconds=21);client.capture.return_value={'status':'OK','messages':[{'symbol':'MERC','event_time':later.isoformat(),'received_at':later.isoformat(),'price':'101'}]}
  with patch('hotwatch_adapters.time.monotonic',return_value=time.monotonic()+21),patch('hotwatch_adapters.utc',return_value=later):result=self.adapter.capture(client,'us_trades','MERC',job)
  self.assertEqual(client.capture.call_count,2);self.assertEqual(result['messages'][0]['event_time'],later.isoformat())
 def test_scan_diagnostics_use_requested_symbol_not_newest_other_batch_member(self):
  job=capacity_fixture.LiveCapacity.add(self,'OTHER.US',1,due=self.now.timestamp())
  client=Mock();client.capture.return_value={'status':'OK','messages':[{'symbol':'MERC','event_time':(self.now-timedelta(minutes=5)).isoformat(),'received_at':self.now.isoformat(),'price':'100'},{'symbol':'OTHER','event_time':self.now.isoformat(),'received_at':self.now.isoformat(),'price':'200'}],'connections_opened':1,'subscriptions_sent':2}
  with patch('hotwatch_engine.verified_automatic_feed',return_value=True):self.adapter.capture(client,'us_trades','MERC',self.job)
  metrics=self.adapter.capture_metrics[-1]
  self.assertEqual(metrics['source_age_s'],300);self.assertEqual(metrics['messages'],1)
  self.assertEqual(metrics['connections_opened'],1);self.assertEqual(metrics['subscriptions_sent'],2)
 def test_batch_limit_metrics_survive_symbol_split_and_cache_reuse(self):
  capacity_fixture.LiveCapacity.add(self,'OTHER.US',1,due=self.now.timestamp())
  client=Mock();client.capture.return_value={'status':'OK','messages':[{'symbol':'OTHER','event_time':self.now.isoformat(),'received_at':self.now.isoformat(),'price':'200'}],'batch_valid_count':250,'batch_partial_count':0,'batch_limit_reached':True}
  with patch('hotwatch_engine.verified_automatic_feed',return_value=True):
   result=self.adapter.capture(client,'us_trades','MERC',self.job)
   self.assertEqual(result['status'],'INCOMPLETE')
   self.assertTrue(self.adapter.capture_metrics[-1]['batch_limit_reached'])
   self.assertEqual(self.adapter.capture_metrics[-1]['batch_valid_count'],250)
   self.adapter.capture(client,'us_trades','MERC',self.job)
  self.assertFalse(self.adapter.capture_metrics[-1]['cache_hit'])
  self.assertTrue(self.adapter.capture_metrics[-1]['batch_limit_reached'])
  self.assertEqual(client.capture.call_count,2)
 def test_saturated_partial_batch_is_incomplete_then_recovers_on_next_scan(self):
  client=Mock();client.capture.side_effect=[
   {'status':'NO_MESSAGES','messages':[],'partial_messages':[{'symbol':'MERC','price':'100'}],'batch_valid_count':0,'batch_partial_count':250,'batch_limit_reached':True},
   {'status':'OK','messages':[{'symbol':'MERC','event_time':self.now.isoformat(),'received_at':self.now.isoformat(),'price':'101'}],'batch_valid_count':1,'batch_partial_count':0,'batch_limit_reached':False}]
  first=self.adapter.capture(client,'us_trades','MERC',self.job)
  self.assertEqual(first['status'],'INCOMPLETE');self.assertEqual(first['partial_messages'][0]['price'],'100');self.assertEqual(client.capture.call_count,1)
  second=self.adapter.capture(client,'us_trades','MERC',self.job)
  self.assertEqual(second['status'],'OK');self.assertEqual(second['messages'][0]['price'],'101');self.assertEqual(client.capture.call_count,2)
 def test_real_capture_limit_does_not_cache_missing_batch_symbol(self):
  from eodhd_feeds import EODHDFeeds
  from test_eodhd_feeds import WS
  capacity_fixture.LiveCapacity.add(self,'OTHER.US',1,due=self.now.timestamp())
  at=int(self.now.timestamp()*1000)
  first_ws=WS([{'s':'OTHER','t':at-i,'p':200} for i in range(250)]+[{'s':'MERC','t':at,'p':100}])
  second_ws=WS([{'s':'MERC','t':at,'p':101}]);streams=iter([first_ws,second_ws]);client=EODHDFeeds('SYNTHETIC',ws_factory=lambda *a,**kw:next(streams))
  with patch('hotwatch_engine.verified_automatic_feed',return_value=True):
   first=self.adapter.capture(client,'us_trades','MERC',self.job)
   self.assertEqual(first['status'],'INCOMPLETE');self.assertEqual(len(first_ws.messages),1)
   second=self.adapter.capture(client,'us_trades','MERC',self.job)
  self.assertEqual(second['status'],'OK');self.assertEqual(second['messages'][0]['price'],'101')
 def test_non_saturated_empty_batch_still_uses_negative_cache(self):
  client=Mock();client.capture.return_value={'status':'NO_MESSAGES','messages':[],'batch_limit_reached':False}
  self.assertEqual(self.adapter.capture(client,'us_trades','MERC',self.job)['status'],'NO_MESSAGES')
  self.assertEqual(self.adapter.capture(client,'us_trades','MERC',self.job)['status'],'NO_MESSAGES')
  self.assertEqual(client.capture.call_count,1);self.assertTrue(self.adapter.capture_metrics[-1]['cache_hit'])
 def test_incomplete_trade_still_collects_quote_without_promoting_it_to_trade(self):
  from decimal import Decimal
  old=self.now-timedelta(minutes=5);calls=[]
  def capture(client,feed,symbol,session):
   calls.append(feed)
   if feed.endswith('trades'):return {'status':'INCOMPLETE','messages':[]}
   return {'status':'OK','messages':[{'symbol':'MERC','event_time':self.now.isoformat(),'received_at':self.now.isoformat(),'bid':'99','ask':'101'}]}
  rest=({'code':'MERC.US','close':'100','currency':'USD'},self.now,1,old,Decimal('100'))
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  with patch.dict(os.environ,env),patch.object(self.adapter,'capture',side_effect=capture),patch.object(self.adapter,'feeds',return_value=Mock()),patch.object(self.adapter.pluto,'safe_context',return_value=fixture.tick(self.now,held=True)['context']),patch.object(adapters,'shared_quote',return_value=rest):
   sample=self.adapter.poll(self.job)
  self.assertEqual(calls,['us_trades','us_quotes']);self.assertEqual(self.adapter.last_feed_diagnostics['websocket_trade_status'],'INCOMPLETE')
  self.assertEqual(sample['event_time'],old.isoformat());self.assertNotEqual(sample.get('price_time_kind'),'trade')
  self.assertEqual(self.adapter.last_partial_observations[-1]['quality'],'TRADE_MISSING')
 def test_cached_stale_trade_and_fresh_quotes_cannot_become_actionable(self):
  from decimal import Decimal
  from hotwatch_strategy import BASELINE,calculate
  old=self.now-timedelta(minutes=5);client=Mock();calls=[]
  def capture(feed,symbols,**kwargs):
   calls.append(feed)
   if isinstance(symbols,str):symbols=[symbols]
   at=old if feed.endswith('trades') else self.now
   return {'status':'OK','messages':[dict(symbol=s,event_time=at.isoformat(),received_at=self.now.isoformat(),price='100',bid='99.99',ask='100.01',market_session='open') for s in symbols]}
  client.capture.side_effect=capture
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  rest=({'code':'MERC.US','close':'100','currency':'USD'},self.now,1,old,Decimal('100'))
  with patch.dict(os.environ,env),patch.object(self.adapter,'feeds',return_value=client),patch.object(self.adapter.pluto,'safe_context',return_value=fixture.tick(self.now,held=True)['context']),patch.object(adapters,'shared_quote',return_value=rest):
   first=self.adapter.poll(self.job);second=self.adapter.poll(self.job)
  self.assertEqual(calls,['us_trades','us_quotes'])
  self.assertEqual(first['event_time'],old.isoformat());self.assertEqual(second['event_time'],old.isoformat())
  self.assertNotEqual(second.get('price_time_kind'),'trade')
  # Even a breached analytical stop cannot use the stale price as current.
  result,_=calculate(second,fixture.good_metrics(),BASELINE,dict(self.req['risk'],stop_price='101'),{},self.now)
  self.assertEqual(result['signal'],'NO_DATA');self.assertIn('DATA_STALE',result['reason_codes'])
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
    # Either earlier claim may win the shared capture after broker context
    # returns; the other must yield so the ready exit can run.
    self.assertTrue(any((job['watch_id'],'deferred','FEED_COLLECTING') in records for job in jobs[:2]))
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
