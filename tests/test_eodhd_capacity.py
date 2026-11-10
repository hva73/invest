"""Provider limits are exercised against real temporary SQLite connections."""
import json,os,time,unittest,urllib.error
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import app,eodhd_capacity as capacity,eodhd_feeds
import test_hotwatch_engine as fixtures
from hotwatch_contract import EngineError

class CapacityTests(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.HotWatch();self.f.setUp()
  self.env=patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'synthetic'},clear=True);self.env.start()
  self.cap=capacity.Capacity(app.connect);self.now=1800000000
 def tearDown(self):self.env.stop();self.f.tearDown()
 def state(self):
  with app.connect() as c:return capacity.read(c)
 def test_eighty_percent_no_compounded_buffer_and_parallel_shared_budget(self):
  started=time.perf_counter()
  def send(_):
   try:self.cap.reserve(units=1,now=self.now);return True
   except EngineError as error:
    self.assertEqual(error.code,'PROVIDER_RATE_BUDGET');return False
  with ThreadPoolExecutor(max_workers=10) as pool:results=list(pool.map(send,range(810)))
  self.assertEqual(sum(results),800)
  with app.connect() as c:
   readback=capacity.snapshot(c,self.now)
   self.assertEqual(readback['http_effective_limit_per_minute'],800)
   self.assertEqual(readback['http_used_this_minute'],800)
  self.assertEqual(self.state()['known_units'],800)
  self.cap.reserve(1,self.now+60)
  self.assertLess(time.perf_counter()-started,30)
 def test_http_breakdown_exposes_only_endpoint_and_market(self):
  class Response:
   status=200;headers={}
   def __enter__(self):return self
   def __exit__(self,*_):pass
  class Opener:
   def open(self,*args,**kwargs):return Response()
  import urllib.request
  with self.cap.open(Opener(),urllib.request.Request('https://eodhd.com/api/intraday/SECRET.US?api_token=private')):pass
  with app.connect() as c:result=capacity.snapshot(c)
  encoded=json.dumps(result['endpoint_hourly'])
  self.assertIn('intraday:US',encoded);self.assertNotIn('SECRET',encoded);self.assertNotIn('private',encoded)
 def test_provider_headers_lower_budget_remaining_and_429_are_global(self):
  self.assertEqual(capacity.retry_seconds({'Retry-After':'Infinity'},self.now+50),10)
  self.cap.reserve(1,self.now)
  self.cap.observe(200,{'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'21'},2,now=self.now)
  self.cap.reserve(1,self.now)
  with self.assertRaisesRegex(EngineError,'PROVIDER_RATE_BUDGET'):capacity.Capacity(app.connect).reserve(1,self.now)
  self.cap.observe(429,{'Retry-After':'120'},3,now=self.now)
  with self.assertRaises(EngineError) as caught:self.cap.reserve(1,self.now+60)
  self.assertEqual(caught.exception.retry_after_s,60)
  self.cap.reserve(1,self.now+120)
  self.assertEqual(self.state()['http_429'],1)
 def test_cost_units_are_not_http_requests_and_unknown_is_explicit(self):
  for path,expected in [('real-time/AAPL.US',1),('intraday/AAPL.US',5),('screener',5),('fundamentals/AAPL.US',10),('exchange-symbol-list/US',1),('user',0)]:
   self.assertEqual(capacity.cost('https://eodhd.com/api/'+path),expected)
  self.assertEqual(capacity.cost('https://eodhd.com/api/real-time/A.US?s=B.US,C.US'),3)
  self.assertIsNone(capacity.cost('https://ws.eodhistoricaldata.com/history?market=us&symbol=AAPL'))
  for units in (1,5,10,None):self.cap.reserve(units,self.now)
  state=self.state();self.assertEqual(state['known_units'],16);self.assertEqual(state['requests'],4);self.assertEqual(state['unknown_cost_requests'],1)
 @patch('eodhd_capacity.TEMPORARY_DAILY_LIMIT_DAY','')
 def test_daily_budget_reserves_headroom_for_essential_scans_and_resets_utc(self):
  from datetime import datetime,timezone
  now=datetime(2026,11,10,23,59,55,tzinfo=timezone.utc).timestamp()
  with app.connect() as c:
   state=capacity.read(c);state.update(local_day='2026-11-10',known_units=0,account={'apiRequests':80,'dailyRateLimit':100,'extraLimit':0,'apiRequestsDate':'2026-11-10'},units_at_account=0);capacity.write(c,state,now)
  with self.assertRaisesRegex(EngineError,'EODHD_DAILY_BUDGET'):self.cap.reserve(1,now)
  capacity.Capacity(app.connect,'essential').reserve(1,now)
  self.cap.reserve(1,now+10)
 @patch('eodhd_capacity.TEMPORARY_DAILY_LIMIT_DAY','')
 def test_unknown_cost_is_not_assumed_free_near_daily_limit(self):
  from datetime import datetime,timezone
  now=datetime(2026,11,10,10,0,tzinfo=timezone.utc).timestamp()
  with app.connect() as c:
   state=capacity.read(c);state.update(local_day='2026-11-10',known_units=0,unknown_cost_requests=0,unknown_at_account=0,account={'apiRequests':79,'dailyRateLimit':100,'apiRequestsDate':'2026-11-10'},units_at_account=0);capacity.write(c,state,now)
  self.cap.reserve(None,now)
  with self.assertRaisesRegex(EngineError,'EODHD_DAILY_BUDGET'):self.cap.reserve(None,now+1)
 def test_realtime_history_breakdown_does_not_expose_symbol_or_token(self):
  class Response:
   status=200;headers={}
   def __enter__(self):return self
   def __exit__(self,*_):pass
  class Opener:
   def open(self,*args,**kwargs):return Response()
  with self.cap.open(Opener(),urllib.request.Request('https://ws.eodhistoricaldata.com/history?market=us&symbol=SECRET&api_token=private')):pass
  with app.connect() as c:encoded=json.dumps(capacity.snapshot(c)['endpoint_hourly'])
  self.assertIn('realtime_history:US',encoded);self.assertNotIn('SECRET',encoded);self.assertNotIn('private',encoded)
 def test_websocket_slots_separate_shared_released_on_error(self):
  with self.cap.websocket(20),capacity.Capacity(app.connect).websocket(20):
   with self.assertRaisesRegex(EngineError,'EODHD_WS_CAPACITY'):
    with self.cap.websocket(1):self.fail('capacity exceeded')
   with app.connect() as c:
    self.assertEqual(capacity.snapshot(c)['ws_subscriptions'],40)
    self.assertEqual(c.execute('SELECT count(*) FROM hw_request_budget').fetchone()[0],0)
  with self.assertRaises(ValueError):
   with self.cap.websocket(40):raise ValueError('test release')
  self.assertFalse(self.state()['ws_leases'])
 @patch('eodhd_capacity.TEMPORARY_DAILY_LIMIT_DAY','')
 def test_account_refresh_sanitized_and_daily_budget_does_not_stop_websockets(self):
  from datetime import datetime,timezone
  day=datetime.now(timezone.utc).date().isoformat()
  class Response:
   status=200;headers={}
   def __enter__(self):return self
   def __exit__(self,*_):pass
   def read(self,_):return json.dumps({'apiRequests':80000,'apiRequestsDate':day,'dailyRateLimit':100000,'extraLimit':500,'apiKey':'secret','name':'private','email':'private'}).encode()
  class Opener:
   calls=0
   def open(self,*_,**kw):self.calls+=1;return Response()
  opener=Opener();capacity.refresh_account(app.connect,opener);capacity.refresh_account(app.connect,opener)
  self.assertEqual(opener.calls,1)
  state=self.state();self.assertNotIn('private',json.dumps(state));self.assertNotIn('secret',json.dumps(state))
  with self.assertRaisesRegex(EngineError,'EODHD_DAILY_BUDGET'):self.cap.reserve(1)
  with self.cap.websocket(5):pass
  self.cap.reserve(0) # Usage endpoint remains available to discover a reset.
  self.cap.reserve(1,time.time()+86400)
 def test_purchased_buffer_applies_only_to_the_authorized_utc_day(self):
  from datetime import datetime,timezone
  now=datetime(2026,11,10,23,59,55,tzinfo=timezone.utc).timestamp()
  with app.connect() as c:
   state=capacity.read(c);state.update(local_day='2026-11-10',known_units=0,account={'apiRequests':199999,'dailyRateLimit':100000,'extraLimit':500,'apiRequestsDate':'2026-11-10'},units_at_account=0);capacity.write(c,state,now)
  self.cap.reserve(1,now)
  with self.assertRaisesRegex(EngineError,'EODHD_DAILY_BUDGET'):self.cap.reserve(1,now+1)
  with app.connect() as c:
   self.assertEqual(capacity.snapshot(c,now)['temporary_daily_limit']['limit_units'],200000)
   state=capacity.read(c);state.update(local_day='2026-11-11',known_units=0,account={'apiRequests':80000,'dailyRateLimit':100000,'apiRequestsDate':'2026-11-11'},units_at_account=0);capacity.write(c,state,now+10)
   self.assertIsNone(capacity.snapshot(c,now+10)['temporary_daily_limit'])
  with self.assertRaisesRegex(EngineError,'EODHD_DAILY_BUDGET'):self.cap.reserve(1,now+10)
  capacity.Capacity(app.connect,'essential').reserve(1,now+10)
 def test_temporary_buffer_never_relabels_a_stale_account_snapshot(self):
  self.assertEqual(capacity.daily_limit({'dailyRateLimit':100000,'apiRequestsDate':'2026-11-09'},'2026-11-10','routine'),80000)
 def test_history_cache_deduplicates_positions_without_refreshing_source_time(self):
  eodhd_feeds._history_cache.clear();calls=[]
  def fetch(*_):
   calls.append(1);time.sleep(.01)
   return {'status':'OK','received_at':'original','bars':[{'bar_open_at':'source-time','close':'10'}]}
  with patch.object(eodhd_feeds.EODHDFeeds,'_minute_bars_uncached',fetch),ThreadPoolExecutor(max_workers=5) as pool:
   results=list(pool.map(lambda _:eodhd_feeds.EODHDFeeds('synthetic').minute_bars('us','AAPL'),range(5)))
  self.assertEqual(len(calls),1);self.assertEqual(results[0]['received_at'],'original')
  results[0]['bars'][0]['close']='changed';self.assertEqual(results[1]['bars'][0]['close'],'10')
  eodhd_feeds._history_cache.clear()
 def test_existing_pluto_default_cannot_limit_eodhd_and_override_is_visible(self):
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):self.assertEqual(capacity.configured_limit(),800)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'30'}),app.connect() as c:
   result=capacity.snapshot(c);self.assertEqual(result['http_effective_limit_per_minute'],30);self.assertEqual(result['http_configured_override'],'30')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'900'}):self.assertEqual(capacity.configured_limit(),800)
 def test_http_429_transport_obeys_exact_retry_and_no_network_under_writer(self):
  class Opener:
   def open(self,*args,**kwargs):
    with app.connect() as c:
     c.execute('BEGIN IMMEDIATE') # Network is not called while a writer is held.
    raise urllib.error.HTTPError('https://eodhd.com/secret',429,'private',{'Retry-After':'7'},None)
  client=eodhd_feeds.EODHDFeeds('synthetic',capacity=self.cap,opener=Opener())
  reply=client._http(eodhd_feeds.HTTP_BASE,'/eod/A.US',{})
  self.assertEqual(reply['status'],'RATE_LIMIT');self.assertEqual(reply['retry_after_s'],7)
  self.assertNotIn('secret',str(reply));self.assertNotIn('private',str(reply))
  with self.assertRaises(EngineError) as caught:self.cap.reserve(1)
  self.assertGreater(caught.exception.retry_after_s,0);self.assertLessEqual(caught.exception.retry_after_s,7)
  with app.connect() as c:
   state=capacity.read(c);self.assertEqual(state['http_429'],1);self.assertEqual(state['last_http_status'],429)
 def test_websocket_429_does_not_stop_http_or_retry_every_symbol(self):
  self.cap.ws_limited({'Retry-After':'7'})
  with self.assertRaisesRegex(EngineError,'EODHD_WS_CAPACITY'):
   with capacity.Capacity(app.connect).websocket(1):self.fail('must honor shared cooldown')
  self.cap.reserve(1)
  self.assertEqual(self.state()['ws_429'],1)
