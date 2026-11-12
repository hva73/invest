"""Simulated provider responses only; no real network or credentials."""
import copy,json,os,unittest,urllib.error
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from eodhd_feeds import EODHDFeeds
from hotwatch_adapters import EODHDAdapter,unknown_context

SECRET='MOCK-SECRET-ONLY'
class Response:
 def __init__(self,payload):self.payload=payload
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def read(self,limit):return json.dumps(self.payload).encode()
class Opener:
 def __init__(self,payload):self.payload=payload;self.url=None
 def open(self,request,**kwargs):self.url=request.full_url;return Response(self.payload)
class WS:
 def __init__(self,messages):self.messages=list(messages);self.sent=None
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def send(self,msg):self.sent=json.loads(msg)
 def recv(self,timeout):
  if not self.messages:raise TimeoutError()
  return json.dumps(self.messages.pop(0))

class FeedTests(unittest.TestCase):
 def test_batch_limit_diagnostics_cover_valid_partial_and_quiet_streams(self):
  now=int(datetime.now(timezone.utc).timestamp()*1000)
  for rows,valid,partial,limited in [
   ([{'s':'FAST','t':now+i,'p':10} for i in range(3)]+[{'s':'SLOW','t':now,'p':20}],3,0,True),
   ([{'s':'FAST','p':10} for _ in range(3)]+[{'s':'SLOW','t':now,'p':20}],0,3,True),
   ([{'s':'FAST','t':now,'p':10}],1,0,False),
   ([],0,0,False),
  ]:
   with self.subTest(valid=valid,partial=partial,limited=limited):
    ws=WS(rows);result=EODHDFeeds(SECRET,ws_factory=lambda *a,**kw:ws).capture('us_trades',['FAST','SLOW'],duration=2,max_messages=3)
    self.assertEqual((result['batch_valid_count'],result['batch_partial_count'],result['batch_limit_reached']),(valid,partial,limited))
    if limited:self.assertEqual(len(ws.messages),1)
 def test_adapter_shared_quotes_deduplicate_only_same_symbol_and_credentials(self):
  import hotwatch_adapters as adapter
  adapter._quote_cache.clear();calls=[]
  def fetch():calls.append(1);return ({'code':'BRK-B.US','timestamp':1730000000},'original-received',1)
  first=adapter.shared_quote('token-a','BRK-B.US',fetch)
  second=adapter.shared_quote('token-a','BRK-B.US',fetch)
  adapter.shared_quote('token-b','BRK-B.US',fetch)
  adapter.shared_quote('token-a','BRK-A.US',fetch)
  self.assertEqual(len(calls),3);self.assertEqual(first,second);self.assertEqual(second[1],'original-received')
  self.assertNotIn('token-a',str(adapter._quote_cache))
  adapter._quote_cache.clear()
 def test_concurrent_same_symbol_snapshots_share_one_provider_call(self):
  import eodhd_feeds,time
  from concurrent.futures import ThreadPoolExecutor
  eodhd_feeds._snapshot_cache.clear();calls=[]
  def fetch(_self,_symbol):
   calls.append(1);time.sleep(.03)
   return {'status':'OK','price':'12','event_time':'2026-11-06T20:00:00+00:00','received_at':'2026-11-06T20:00:01+00:00'}
  with patch.object(EODHDFeeds,'_snapshot_uncached',fetch),ThreadPoolExecutor(max_workers=2) as pool:
   result=list(pool.map(lambda _:EODHDFeeds('SYNTHETIC').snapshot('AMD.US'),range(2)))
  self.assertEqual(len(calls),1);self.assertEqual(result[0],result[1])
  eodhd_feeds._snapshot_cache.clear()
 def test_snapshot_is_shared_briefly_without_refreshing_source_time_or_crossing_keys(self):
  import eodhd_feeds
  eodhd_feeds._snapshot_cache.clear()
  fake=Opener({'code':'AMD.US','timestamp':1730000000,'close':12.5,'volume':100})
  calls=[]
  with patch('eodhd_feeds.urllib.request.build_opener',return_value=fake),patch('eodhd_feeds.time.monotonic',side_effect=[10,10,11,12,12,20,20]):
   first=EODHDFeeds(SECRET,reserve=lambda:calls.append('one')).snapshot('AMD.US')
   second=EODHDFeeds(SECRET,reserve=lambda:calls.append('two')).snapshot('AMD.US')
   separate=EODHDFeeds('different-key',reserve=lambda:calls.append('other')).snapshot('AMD.US')
   expired=EODHDFeeds(SECRET,reserve=lambda:calls.append('expired')).snapshot('AMD.US')
  self.assertEqual(calls,['one','other','expired'])
  self.assertEqual(first['event_time'],second['event_time'])
  self.assertEqual(first['received_at'],second['received_at'])
  self.assertEqual(first['event_time'],separate['event_time'])
  self.assertEqual(first['event_time'],expired['event_time'])
  eodhd_feeds._snapshot_cache.clear()
 def test_realtime_minute_bars_preserve_open_millisecond_and_interval_volume(self):
  opener=Opener([{'s':'AMD.US','i':'1m','t':1730000000000,'o':10,'h':12,'l':9,'c':11,'v':45}]);result=EODHDFeeds(SECRET,opener=opener).minute_bars('us','AMD')
  self.assertEqual(result['status'],'OK');self.assertEqual(result['bars'][0]['bar_open_at'],'2024-10-27T03:33:20+00:00');self.assertEqual(result['bars'][0]['volume_type'],'interval');self.assertIn('ws.eodhistoricaldata.com/history?',opener.url);self.assertNotIn(SECRET,str(result))
 def test_snapshot_shows_actual_price_and_source_time(self):
  opener=Opener({'code':'AMD.US','timestamp':1730000000,'close':12.5,'volume':100})
  res=EODHDFeeds(SECRET,opener=opener).snapshot('AMD.US')
  self.assertEqual(res['price'],'12.5');self.assertEqual(res['event_time'],'2024-10-27T03:33:20+00:00');self.assertEqual(res['volume_type'],'unknown');self.assertNotIn(SECRET,str(res))
 def test_historical_bar_seconds_and_empty(self):
  opener=Opener([{'timestamp':1730000000,'open':10,'high':12,'low':9,'close':11,'volume':20}]);client=EODHDFeeds(SECRET,opener=opener)
  result=client.intraday('NOVO-B.CO','5m',1730000000,1730001000);self.assertEqual(result['bars'][0]['bar_open_at'],'2024-10-27T03:33:20+00:00');self.assertIn('/api/intraday/NOVO-B.CO?',opener.url)
  self.assertEqual(EODHDFeeds(SECRET,opener=Opener([])).minute_bars('eu','NOVO-B.CO')['status'],'NO_DATA')
 def test_bar_limit_keeps_newest_observations(self):
  rows=[{'timestamp':1730000000+i*60,'open':10,'high':12,'low':9,'close':11,'volume':20} for i in range(1001)]
  result=EODHDFeeds(SECRET,opener=Opener(list(reversed(rows)))).intraday('AMD.US')
  self.assertEqual(len(result['bars']),1000)
  self.assertEqual(result['bars'][-1]['bar_open_at'],datetime.fromtimestamp(rows[-1]['timestamp'],timezone.utc).isoformat())
 def test_conflicting_bars_at_same_source_time_are_rejected(self):
  a={'timestamp':1730000000,'open':10,'high':12,'low':9,'close':11,'volume':20};b=dict(a,close=12)
  self.assertEqual(EODHDFeeds(SECRET,opener=Opener([a,b])).intraday('AMD.US')['status'],'INVALID_RESPONSE')
  self.assertEqual(len(EODHDFeeds(SECRET,opener=Opener([a,a])).intraday('AMD.US')['bars']),1)
 def test_millisecond_source_timestamp_is_exact(self):
  from eodhd_feeds import _timestamp
  self.assertEqual(_timestamp(1730000000123,1000),'2024-10-27T03:33:20.123000+00:00')
 def test_delayed_quote_preserves_independent_times_and_missing_times(self):
  data={'data':{'AMD.US':{'symbol':'AMD.US','bidPrice':10,'askPrice':11,'bidTime':1730000000000,'askTime':1730000005000}}}
  result=EODHDFeeds(SECRET,opener=Opener(data)).us_quotes('AMD.US');q=result['quote'];self.assertNotEqual(q['bid_at'],q['ask_at']);self.assertEqual(q['bid'],'10');self.assertIn('delayed',q['documented_delay'])
  del data['data']['AMD.US']['askTime'];self.assertIsNone(EODHDFeeds(SECRET,opener=Opener(data)).us_quotes('AMD.US')['quote']['ask_at'])
 def test_exchange_open_is_receive_time_not_invented_source_time(self):
  result=EODHDFeeds(SECRET,opener=Opener({'Code':'CO','isOpen':True,'Timezone':'Europe/Copenhagen'})).market_status('CO')
  self.assertTrue(result['exchange_open']);self.assertIsNone(result['source_time']);self.assertTrue(result['received_at'])
 def test_exchange_calendar_requires_explicit_hours_and_exceptions(self):
  raw={'Code':'US','isOpen':True,'Timezone':'America/New_York','TradingHours':{'Open':'09:30:00','Close':'16:00:00','WorkingDays':'Mon,Tue,Wed,Thu,Fri'},'ExchangeHolidays':{'0':{'Date':'2026-11-26'}},'ExchangeEarlyCloseDays':{'0':{'Date':'2026-11-27'}}}
  result=EODHDFeeds(SECRET,opener=Opener(raw)).market_status('US');self.assertEqual(result['calendar']['excluded_dates'],['2026-11-26','2026-11-27'])
  del raw['ExchangeEarlyCloseDays'];self.assertIsNone(EODHDFeeds(SECRET,opener=Opener(raw)).market_status('US')['calendar'])
 def test_permission_rate_and_sensitive_errors_are_explicit(self):
  class Failure:
   def __init__(self,code):self.code=code
   def open(self,req,**kw):raise urllib.error.HTTPError('https://x/'+SECRET,self.code,'error',{},None)
  for code,expected in [(401,'ENTITLEMENT_UNVERIFIED'),(402,'ENTITLEMENT_UNVERIFIED'),(403,'ENTITLEMENT_UNVERIFIED'),(429,'RATE_LIMIT'),(500,'HTTP_ERROR')]:
   res=EODHDFeeds(SECRET,opener=Failure(code)).minute_bars('us','AMD');self.assertEqual(res['status'],expected);self.assertNotIn(SECRET,str(res))
 def test_local_request_budget_is_distinct_from_provider_rate_limit(self):
  from hotwatch_adapters import DataUnavailable
  def exhausted():raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
  client=EODHDFeeds(SECRET,reserve=exhausted,opener=Opener([]),ws_factory=lambda *a,**kw:WS([]))
  self.assertEqual(client.minute_bars('us','AMD')['status'],'LOCAL_BUDGET_EXHAUSTED')
  self.assertEqual(client.capture('us_trades','AMD',1)['status'],'NO_MESSAGES') # HTTP exhaustion must not block a WebSocket.
 def test_live_trade_survives_exhausted_local_quote_budget(self):
  from test_hotwatch_engine import request
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0);adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'45.2','trade_size':'7','market_session':'open'}]}
    return {'status':'LOCAL_BUDGET_EXHAUSTED'}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['price'],'45.2');self.assertEqual(sample['trade_size'],'7');self.assertIsNone(sample['volume']);self.assertEqual(sample['market_status'],'REGULAR');self.assertIsNone(sample['bid']);self.assertEqual(adapter.last_feed_diagnostics['websocket_quote_status'],'LOCAL_BUDGET_EXHAUSTED')
 def test_live_trade_survives_downstream_rate_limit_with_available_quote(self):
  from test_hotwatch_engine import request
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0)
  for limited_feed in ('us_quotes','us_status'):
   with self.subTest(limited_feed=limited_feed):
    adapter=EODHDAdapter(None,1,Opener({}))
    class Feeds:
     def capture(self,feed,*args,**kwargs):
      if feed==limited_feed:return {'status':'RATE_LIMIT','messages':[]}
      if feed=='us_trades':return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'45.2','trade_size':'7','market_session':'extended-hours'}]}
      if feed=='us_quotes':return {'status':'OK','messages':[{'event_time':now.isoformat(),'bid':'45.1','ask':'45.3'}]}
      return {'status':'OK','messages':[]}
    with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
    self.assertEqual(sample['price'],'45.2');self.assertEqual(sample['trade_size'],'7');self.assertEqual(sample['market_status'],'UNKNOWN');self.assertIsNone(sample['volume'])
    self.assertEqual(sample['bid'],'45.1' if limited_feed=='us_status' else None)
 def test_ws_trade_quote_status_and_no_messages(self):
  for feed,msg,field in [('us_trades',{'s':'AMD','t':1730000000000,'p':10,'v':5,'ms':'open'},'price'),('us_quotes',{'s':'AMD','t':1730000000000,'bp':10,'ap':11},'bid'),('us_status',{'s':'AMD','t':1730000000000,'h':'T'},'trading_status')]:
   ws=WS([msg]);client=EODHDFeeds(SECRET,ws_factory=lambda *a,**k:ws);result=client.capture(feed,'AMD',1)
   self.assertEqual(result['status'],'OK');self.assertIsNotNone(result['messages'][0][field]);self.assertEqual(ws.sent,{'action':'subscribe','symbols':'AMD'});self.assertNotIn(SECRET,str(result))
  self.assertEqual(EODHDFeeds(SECRET,ws_factory=lambda *a,**k:WS([])).capture('eu_trades','NOVO-B.CO',1)['status'],'NO_MESSAGES')
 def test_european_websocket_batches_symbols_without_cross_contamination(self):
  symbols=['NOVO-B.CO','GMAB.CO','DSV.CO','VWS.CO','CARL-B.CO']
  rows=[{'s':symbol,'t':1730000000000+i,'p':100+i,'v':i+1,'ms':'open'} for i,symbol in enumerate(symbols)]
  rows.append({'s':'OTHER.CO','t':1730000001000,'p':900,'v':1})
  ws=WS(rows);result=EODHDFeeds(SECRET,ws_factory=lambda *a,**k:ws).capture('eu_trades',symbols,1,250)
  self.assertEqual(ws.sent['symbols'],','.join(symbols));self.assertEqual({m['symbol'] for m in result['messages']},set(symbols))
  self.assertEqual([m['trade_size'] for m in result['messages']],['1','2','3','4','5'])
  self.assertEqual(len({m['event_time'] for m in result['messages']}),5)
 def test_untimed_european_trade_is_retained_without_inventing_source_time(self):
  ws=WS([{'s':'NOVO-B.CO','p':'100','v':7}]);client=EODHDFeeds(SECRET,ws_factory=lambda *a,**k:ws)
  result=client.capture('eu_trades','NOVO-B.CO',1)
  self.assertEqual(result['status'],'NO_MESSAGES');self.assertEqual(result['messages'],[])
  self.assertEqual(result['partial_messages'][0]['price'],'100');self.assertNotIn('event_time',result['partial_messages'][0])
 def test_websocket_entitlement_error_and_untrusted_fields_do_not_leak(self):
  ws=WS([{'status_code':403,'message':SECRET}]);self.assertEqual(EODHDFeeds(SECRET,ws_factory=lambda *a,**k:ws).capture('us_trades','AMD',1)['status'],'ENTITLEMENT_UNVERIFIED')
  ws=WS([{'s':'AMD','t':1730000000000,'p':10,'extra':SECRET}]);res=EODHDFeeds(SECRET,ws_factory=lambda *a,**k:ws).capture('us_trades','AMD',1);self.assertNotIn(SECRET,str(res))
 def test_probe_stops_after_rate_limit(self):
  from hotwatch_service import probe_eodhd
  with patch('eodhd_feeds.EODHDFeeds') as factory:
   feed=factory.return_value;feed.snapshot.return_value={'status':'OK'};feed.minute_bars.return_value={'status':'RATE_LIMIT'}
   out=probe_eodhd(None,'AMD.US','us',1)
   self.assertEqual(out['checks']['minute_bars']['status'],'RATE_LIMIT');self.assertEqual(out['checks']['ws_trades']['status'],'NOT_TESTED_RATE_LIMIT');feed.capture.assert_not_called();feed.intraday.assert_not_called()
 def test_opt_in_stream_falls_back_to_rest_when_unavailable(self):
  from test_hotwatch_engine import request
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0)
  opener=Opener({'code':'MERC.US','timestamp':int(now.timestamp()),'close':'12.34','currency':'USD'});adapter=EODHDAdapter(None,1,opener)
  class Missing:
   def capture(self,*a,**k):return {'status':'ENTITLEMENT_UNVERIFIED'}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Missing()),patch('eodhd_capacity.Capacity.observe'),patch('eodhd_capacity.Capacity.reserve'),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['price'],'12.34');self.assertIn('/api/real-time/',opener.url);self.assertEqual(adapter.last_feed_diagnostics['websocket_trade_status'],'ENTITLEMENT_UNVERIFIED')
 def test_rest_uses_previous_close_from_same_provider_snapshot(self):
  from test_hotwatch_engine import request
  from hotwatch_features import observation_status
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0)
  opener=Opener({'code':'MERC.US','timestamp':int(now.timestamp()),'close':'12.00','previousClose':'10.00','currency':'USD'});adapter=EODHDAdapter(None,1,opener)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}),patch('eodhd_capacity.Capacity.observe'),patch('eodhd_capacity.Capacity.reserve'),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['previous_close'],'10.00');self.assertEqual(observation_status([sample],now,120,'NO_DATA','DEGRADED')['daily_change_pct'],'20.0')
 def test_opt_in_live_trade_is_real_observation_but_unknown_risk_fields_remain_unknown(self):
  from test_hotwatch_engine import request
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0);adapter=EODHDAdapter(None,1,Opener({}))
  class Live:
   def capture(self,*args,**kwargs):return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'45.2'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Live()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['event_time'],now.isoformat());self.assertEqual(sample['price'],'45.2');self.assertEqual(sample['market_status'],'UNKNOWN');self.assertIsNone(sample['bid']);self.assertIsNone(sample['volume'])
 def test_fused_live_trade_uses_fresh_independent_quote_and_status_times(self):
  from test_hotwatch_engine import request
  import hotwatch_engine
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0);adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):item={'event_time':(now-timedelta(seconds=4)).isoformat(),'price':'45.2','market_session':'open'}
    elif feed.endswith('quotes'):item={'event_time':(now-timedelta(seconds=2)).isoformat(),'bid':'45.1','ask':'45.3'}
    else:item={'event_time':(now-timedelta(seconds=1)).isoformat(),'trading_status':'T'}
    return {'status':'OK','messages':[item]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  hotwatch_engine.sample_errors(sample,req,now);self.assertEqual(sample['market_status'],'REGULAR');self.assertEqual(sample['bid'],'45.1');self.assertNotEqual(sample['event_time'],sample['bid_at']);self.assertNotEqual(sample['bid_at'],sample['status_at'])
  stale=copy.deepcopy(sample);stale['ask_at']=(now-timedelta(seconds=121)).isoformat()
  # Old optional quotes are retained as observations; the buy gate still rejects them.
  hotwatch_engine.sample_errors(stale,req,now)
  from hotwatch_strategy import risk_gate
  from test_hotwatch_engine import good_metrics,tick
  stale['context']=tick(now)['context']
  signal,codes,_=risk_gate(stale,good_metrics(),req['risk'],now,'BUY')
  self.assertNotEqual(signal,'BUY');self.assertIn('SPREAD_UNKNOWN',codes)
 def test_stale_or_crossed_quotes_do_not_become_a_spread(self):
  from test_hotwatch_engine import request
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0);adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'45.2','market_session':'open'}]}
    if feed.endswith('quotes'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'bid':'46','ask':'45'}]}
    return {'status':'ENTITLEMENT_UNVERIFIED'}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  self.assertIsNone(sample['bid']);self.assertIsNone(sample['ask']);self.assertEqual(sample['market_status'],'REGULAR');self.assertEqual(sample['status_feed'],'us_trades')
 def test_extended_trades_require_matching_current_exchange_calendar(self):
  from hotwatch_adapters import extended_session
  from datetime import datetime,timezone,timedelta
  now=datetime(2026,11,5,13,15,tzinfo=timezone.utc)
  trade={'event_time':now.isoformat(),'market_session':'extended-hours'}
  schedule={'status':'OK','exchange_open':False,'timezone':'America/New_York','received_at':now.isoformat(),'calendar':{'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}}
  self.assertEqual(extended_session(trade,schedule,now,120),'PRE')
  after=now.replace(hour=22);self.assertEqual(extended_session({'event_time':after.isoformat(),'market_session':'extended hours'},dict(schedule,received_at=after.isoformat()),after,120),'AFTER')
  self.assertIsNone(extended_session(dict(trade,market_session=None),schedule,now,120))
  self.assertIsNone(extended_session(trade,dict(schedule,received_at=(now-timedelta(minutes=3)).isoformat()),now,120))
  holiday=dict(schedule,calendar={**schedule['calendar'],'excluded_dates':['2026-11-05']});self.assertIsNone(extended_session(trade,holiday,now,120))
  self.assertIsNone(extended_session(trade,dict(schedule,exchange_open=True),now,120))
  weekend=datetime(2026,11,7,13,15,tzinfo=timezone.utc)
  self.assertIsNone(extended_session({'event_time':weekend.isoformat(),'market_session':'extended-hours'},dict(schedule,received_at=weekend.isoformat()),weekend,120))
 def test_local_budget_preserves_daily_or_minute_reason(self):
  from hotwatch_adapters import local_budget_error
  self.assertEqual(local_budget_error({'budget_reason':'EODHD_DAILY_BUDGET'}).code,'EODHD_DAILY_BUDGET')
  self.assertEqual(local_budget_error({'budget_reason':'PROVIDER_RATE_BUDGET'}).code,'PROVIDER_RATE_BUDGET')
  self.assertEqual(local_budget_error({}).code,'PROVIDER_RATE_BUDGET')
 def test_xetra_trade_and_quote_reach_adapter_with_original_event_times(self):
  from test_hotwatch_engine import request,tick
  req=request();req.update(ticker='LHA',exchange='CHIX',asset_id='synthetic-LHA',quote_currency='EUR',provider='eodhd',provider_symbol='LHA.XETRA')
  now=datetime(2026,11,10,9,45,tzinfo=timezone.utc);trade_at=(now-timedelta(seconds=20)).isoformat();quote_at=(now-timedelta(seconds=5)).isoformat()
  adapter=EODHDAdapter(None,1,Opener({}));calls=[]
  class Feeds:
   def capture(self,feed,symbol,**kwargs):
    calls.append((feed,symbol))
    if feed=='eu_trades':return {'status':'OK','messages':[{'event_time':trade_at,'received_at':now.isoformat(),'price':'8.844','trade_size':'705','market_session':'open'}]}
    if feed=='eu_quotes':return {'status':'OK','messages':[{'event_time':quote_at,'received_at':now.isoformat(),'bid':'8.842','ask':'8.846'}]}
    return {'status':'NO_MESSAGES','messages':[]}
  context=tick(now,held=True)['context']
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  with patch.dict(os.environ,env,clear=True),patch.object(adapter,'feeds',return_value=Feeds()),patch.object(adapter.pluto,'safe_context',return_value=context),patch('hotwatch_adapters.utc',return_value=now):sample=adapter.poll({'request_data':req})
  self.assertIn(('eu_trades','LHA.XETRA'),calls);self.assertIn(('eu_quotes','LHA.XETRA'),calls)
  self.assertEqual(sample['event_time'],trade_at);self.assertEqual(sample['bid_at'],quote_at);self.assertEqual(sample['ask_at'],quote_at);self.assertEqual(sample['price'],'8.844');self.assertEqual(sample['market_status'],'REGULAR');self.assertEqual(sample['context']['position'],'held')
 def test_conflicting_quotes_at_same_source_time_preserve_trade_without_spread(self):
  from test_hotwatch_engine import request,tick
  req=request();req.update(ticker='LHA',exchange='CHIX',asset_id='synthetic-LHA',quote_currency='EUR',provider='eodhd',provider_symbol='LHA.XETRA')
  now=datetime(2026,11,10,9,45,tzinfo=timezone.utc);trade_at=(now-timedelta(seconds=20)).isoformat();quote_at=(now-timedelta(seconds=5)).isoformat();adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def capture(self,feed,symbol,**kwargs):
    if feed=='eu_trades':return {'status':'OK','messages':[{'event_time':trade_at,'received_at':now.isoformat(),'price':'8.844','trade_size':'705','market_session':'open'}]}
    if feed=='eu_quotes':return {'status':'OK','messages':[{'event_time':quote_at,'bid':'8.842','ask':'8.846'},{'event_time':quote_at,'bid':'8.843','ask':'8.846'}]}
    return {'status':'NO_MESSAGES','messages':[]}
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  with patch.dict(os.environ,env,clear=True),patch.object(adapter,'feeds',return_value=Feeds()),patch.object(adapter.pluto,'safe_context',return_value=tick(now,held=True)['context']),patch('hotwatch_adapters.utc',return_value=now):sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['event_time'],trade_at);self.assertEqual(sample['price'],'8.844');self.assertIsNone(sample['bid']);self.assertIsNone(sample['ask'])
  self.assertEqual(adapter.last_feed_diagnostics['websocket_quote_status'],'AMBIGUOUS_SAME_TIMESTAMP')
  import hotwatch_engine
  hotwatch_engine.sample_errors(sample,req,now)
 def test_amsterdam_default_stream_is_used_without_changing_source_time(self):
  from test_hotwatch_engine import request,tick
  req=request();req.update(ticker='ASML',exchange='AMS',asset_id='synthetic-ASML',quote_currency='EUR',provider='eodhd',provider_symbol='ASML.AS')
  now=datetime(2026,11,10,9,45,tzinfo=timezone.utc);trade_at=(now-timedelta(seconds=4)).isoformat();adapter=EODHDAdapter(None,1,Opener({}));calls=[]
  class Feeds:
   def capture(self,feed,symbol,**kwargs):
    calls.append((feed,symbol))
    if feed=='eu_trades':return {'status':'OK','messages':[{'event_time':trade_at,'received_at':now.isoformat(),'price':'1360','market_session':'open'}]}
    return {'status':'NO_MESSAGES','messages':[]}
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  with patch.dict(os.environ,env,clear=True),patch.object(adapter,'feeds',return_value=Feeds()),patch.object(adapter.pluto,'safe_context',return_value=tick(now)['context']),patch('hotwatch_adapters.utc',return_value=now):sample=adapter.poll({'request_data':req})
  self.assertIn(('eu_trades','ASML.AS'),calls);self.assertEqual(sample['event_time'],trade_at);self.assertEqual(sample['market_status'],'REGULAR');self.assertIsNone(sample['bid'])
 def test_swedish_and_norwegian_streams_preserve_independent_source_times(self):
  from test_hotwatch_engine import request,tick
  now=datetime(2026,11,10,9,45,tzinfo=timezone.utc);trade_at=(now-timedelta(seconds=4)).isoformat();quote_at=(now-timedelta(seconds=2)).isoformat()
  for exchange,currency in [('ST','SEK'),('OL','NOK')]:
   with self.subTest(exchange=exchange):
    req=request();req.update(ticker='SYN',exchange='CHIX',asset_id='synthetic-SYN',quote_currency=currency,provider='eodhd',provider_symbol='SYN.'+exchange)
    adapter=EODHDAdapter(None,1,Opener({}));calls=[]
    class Feeds:
     def capture(self,feed,symbol,**kwargs):
      calls.append((feed,symbol))
      if feed=='eu_trades':return {'status':'OK','messages':[{'event_time':trade_at,'received_at':now.isoformat(),'price':'100','market_session':'open'}]}
      if feed=='eu_quotes':return {'status':'OK','messages':[{'event_time':quote_at,'received_at':now.isoformat(),'bid':'99','ask':'101'}]}
      return {'status':'NO_MESSAGES','messages':[]}
    env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
    with patch.dict(os.environ,env,clear=True),patch.object(adapter,'feeds',return_value=Feeds()),patch.object(adapter.pluto,'safe_context',return_value=tick(now)['context']),patch('hotwatch_adapters.utc',return_value=now):sample=adapter.poll({'request_data':req})
    self.assertIn(('eu_trades','SYN.'+exchange),calls);self.assertIn(('eu_quotes','SYN.'+exchange),calls)
    self.assertEqual((sample['event_time'],sample['bid_at'],sample['ask_at'],sample['currency']),(trade_at,quote_at,quote_at,currency))
 def test_explicit_eu_stream_override_excludes_new_markets(self):
  from test_hotwatch_engine import request,tick
  now=datetime(2026,11,10,9,45,tzinfo=timezone.utc)
  for exchange,currency in [('ST','SEK'),('OL','NOK')]:
   with self.subTest(exchange=exchange):
    req=request();req.update(ticker='SYN',exchange='CHIX',asset_id='synthetic-SYN',quote_currency=currency,provider='eodhd',provider_symbol='SYN.'+exchange)
    adapter=EODHDAdapter(None,1,Opener({}));env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0','ESCAPE_HW_EODHD_WS_EU_EXCHANGES':'CO'}
    with patch.dict(os.environ,env,clear=True),patch.object(adapter,'capture',side_effect=AssertionError('excluded market must not open stream')),patch('eodhd_capacity.Capacity.open',return_value=Response({'code':'SYN.'+exchange,'timestamp':int(now.timestamp()),'close':'100','currency':currency})),patch.object(adapter.pluto,'safe_context',return_value=tick(now)['context']),patch('hotwatch_adapters.utc',return_value=now):sample=adapter.poll({'request_data':req})
    self.assertEqual(adapter.last_feed_diagnostics['websocket_trade_status'],'MARKET_MAPPING_UNVERIFIED');self.assertEqual(sample['event_time'],now.isoformat());self.assertIsNone(sample['bid'])
 def test_xetra_raw_websocket_events_keep_source_time(self):
  epoch=int(datetime(2026,11,10,9,45,tzinfo=timezone.utc).timestamp()*1000)
  ws=WS([{'s':'LHA.XETRA','p':8.844,'v':705,'ms':'open','t':epoch}]);result=EODHDFeeds(SECRET,ws_factory=lambda *a,**k:ws).capture('eu_trades','LHA.XETRA',1)
  self.assertEqual(result['status'],'OK');self.assertEqual(result['messages'][0]['symbol'],'LHA.XETRA');self.assertEqual(result['messages'][0]['event_time'],datetime.fromtimestamp(epoch/1000,timezone.utc).isoformat())
 def test_adapter_marks_verified_premarket_trade_without_buy_permission(self):
  from test_hotwatch_engine import request,good_metrics,tick
  from hotwatch_engine import sample_errors
  from hotwatch_strategy import risk_gate
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime(2026,11,5,13,15,tzinfo=timezone.utc);adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'100','market_session':'extended-hours'}]}
    if feed.endswith('quotes'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'bid':'99.9','ask':'100.1'}]}
    return {'status':'NO_MESSAGES','messages':[]}
   def market_status(self,exchange):
    return {'status':'OK','exchange_open':False,'timezone':'America/New_York','received_at':now.isoformat(),'calendar':{'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=tick(now)['context']),patch('hotwatch_adapters.utc',return_value=now):sample=adapter.poll({'request_data':req})
  sample_errors(sample,req,now);self.assertEqual(sample['market_status'],'PRE');self.assertEqual(sample['status_at'],now.isoformat())
  signal,codes,_=risk_gate(sample,good_metrics(),req['risk'],now,'BUY');self.assertEqual(signal,'WAIT');self.assertIn('OUTSIDE_REGULAR_SESSION',codes)
  sample['context']=tick(now,held=True)['context']
  signal,codes,_=risk_gate(sample,good_metrics(),req['risk'],now,'SELL');self.assertEqual(signal,'SELL');self.assertIn('EXTENDED_HOURS_EXECUTION_UNCONFIRMED',codes)
 def test_afterhours_warmup_does_not_split_at_utc_midnight(self):
  from datetime import datetime,timezone,timedelta
  from test_hotwatch_engine import request,tick
  from hotwatch_features import features
  from hotwatch_strategy import BASELINE
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US')
  adapter=EODHDAdapter(None,1,Opener({}));first=datetime(2026,11,6,23,59,tzinfo=timezone.utc)
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'OK','messages':[{'event_time':self.at.isoformat(),'price':'100','market_session':'extended-hours'}]}
    return {'status':'NO_MESSAGES','messages':[]}
   def market_status(self,exchange):
    return {'status':'OK','exchange_open':False,'timezone':'America/New_York','received_at':self.at.isoformat(),'calendar':{'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}}
  feed=Feeds();samples=[]
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'0'}),patch.object(adapter,'feeds',return_value=feed):
   for at in (first,first+timedelta(minutes=1)):
    feed.at=at
    with patch('hotwatch_adapters.PlutoAdapter.context',return_value=tick(at)['context']),patch('hotwatch_adapters.utc',return_value=at):samples.append(adapter.poll({'request_data':req}))
  self.assertEqual([s['session_key'] for s in samples],['2026-11-06:AFTER','2026-11-06:AFTER'])
  self.assertEqual(features(samples,BASELINE['parameters'])['sample_count'],2)
 def test_afterhours_bars_use_only_the_verified_extended_session(self):
  from test_hotwatch_engine import request,tick
  from hotwatch_features import verified_bar_samples
  from hotwatch_engine import sample_errors
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime(2026,11,6,22,0,tzinfo=timezone.utc);adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'100','market_session':'extended-hours'}]}
    return {'status':'NO_MESSAGES','messages':[]}
   def market_status(self,exchange):return {'status':'OK','exchange_open':False,'timezone':'America/New_York','received_at':now.isoformat(),'calendar':{'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}}
   def minute_bars(self,*args):return {'status':'OK','bars':[{'bar_open_at':at.isoformat(),'open':'100','high':'101','low':'99','close':'100','volume':'10'} for at in (now-timedelta(minutes=62),now-timedelta(minutes=2),now-timedelta(minutes=1))]}
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'1'}
  with patch.dict(os.environ,env),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=tick(now)['context']),patch('hotwatch_adapters.utc',return_value=now):sample=adapter.poll({'request_data':req})
  sample_errors(sample,req,now);self.assertEqual(sample['market_status'],'AFTER');self.assertEqual(len(sample['bar_history']),2);self.assertEqual(len(verified_bar_samples(sample,req,now)),2)
 def test_extended_trade_does_not_override_unclear_instrument_status(self):
  from test_hotwatch_engine import request,tick
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime(2026,11,6,22,0,tzinfo=timezone.utc)
  adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'100','market_session':'extended-hours'}]}
    if feed.endswith('status'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'trading_status':'S'}]}
    return {'status':'NO_MESSAGES','messages':[]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=tick(now)['context']),patch('hotwatch_adapters.utc',return_value=now):
   sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['market_status'],'UNKNOWN')
 def test_closed_bar_uses_actual_bar_open_time_without_inventing_trade_time(self):
  from test_hotwatch_engine import request
  import hotwatch_engine
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0);adapter=EODHDAdapter(None,1,Opener({}));at=(now-timedelta(minutes=3)).isoformat()
  class Feeds:
   def minute_bars(self,*args):return {'status':'OK','bars':[{'bar_open_at':at,'open':'10','high':'12','low':'9','close':'11','volume':'50'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  hotwatch_engine.sample_errors(sample,req,now);self.assertEqual(sample['event_time'],at);self.assertEqual(sample['price_time_kind'],'bar_open');self.assertEqual(sample['close'],'11');self.assertEqual(sample['volume_type'],'interval');self.assertEqual(sample['market_status'],'UNKNOWN')
 def test_intraday_fallback_requests_only_possible_new_bars_with_overlap(self):
  from test_hotwatch_engine import request
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime(2026,11,10,5,20,tzinfo=timezone.utc);previous=now-timedelta(minutes=2);new=now-timedelta(minutes=1)
  adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def minute_bars(self,*args):return {'status':'NO_DATA'}
   def intraday(self,symbol,start,end):
    self.window=(start,end)
    return {'status':'OK','bars':[{'bar_open_at':new.isoformat(),'open':'10','high':'12','low':'9','close':'11','volume':'50'}]}
  feed=Feeds();env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'1'}
  with patch.dict(os.environ,env),patch.object(adapter,'feeds',return_value=feed),patch('hotwatch_adapters.utc',return_value=now),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):
   sample=adapter.poll({'request_data':req,'last_data':previous.isoformat()})
   self.assertEqual(feed.window,(int(previous.timestamp())-60,int(now.timestamp())));self.assertEqual(sample['event_time'],new.isoformat());self.assertEqual(sample['close'],'11')
   for last in (None,(now-timedelta(hours=25)).isoformat()):
    sample=adapter.poll({'request_data':req,'last_data':last})
    self.assertEqual(feed.window,(int(now.timestamp())-86400,int(now.timestamp())));self.assertEqual(sample['event_time'],new.isoformat())
