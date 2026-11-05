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
  self.assertEqual(client.capture('us_trades','AMD',1)['status'],'LOCAL_BUDGET_EXHAUSTED')
 def test_live_trade_survives_exhausted_local_quote_budget(self):
  from test_hotwatch_engine import request
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0);adapter=EODHDAdapter(None,1,Opener({}))
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'45.2','market_session':'open'}]}
    return {'status':'LOCAL_BUDGET_EXHAUSTED'}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['price'],'45.2');self.assertEqual(sample['market_status'],'REGULAR');self.assertIsNone(sample['bid']);self.assertEqual(adapter.last_feed_diagnostics['websocket_quote_status'],'LOCAL_BUDGET_EXHAUSTED')
 def test_ws_trade_quote_status_and_no_messages(self):
  for feed,msg,field in [('us_trades',{'s':'AMD','t':1730000000000,'p':10,'v':5,'ms':'open'},'price'),('us_quotes',{'s':'AMD','t':1730000000000,'bp':10,'ap':11},'bid'),('us_status',{'s':'AMD','t':1730000000000,'h':'T'},'trading_status')]:
   ws=WS([msg]);client=EODHDFeeds(SECRET,ws_factory=lambda *a,**k:ws);result=client.capture(feed,'AMD',1)
   self.assertEqual(result['status'],'OK');self.assertIsNotNone(result['messages'][0][field]);self.assertEqual(ws.sent,{'action':'subscribe','symbols':'AMD'});self.assertNotIn(SECRET,str(result))
  self.assertEqual(EODHDFeeds(SECRET,ws_factory=lambda *a,**k:WS([])).capture('eu_trades','NOVO-B.CO',1)['status'],'NO_MESSAGES')
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
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Missing()),patch('hotwatch_adapters.reserve'),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['price'],'12.34');self.assertIn('/api/real-time/',opener.url);self.assertEqual(adapter.last_feed_diagnostics['websocket_trade_status'],'ENTITLEMENT_UNVERIFIED')
 def test_rest_uses_previous_close_from_same_provider_snapshot(self):
  from test_hotwatch_engine import request
  from hotwatch_features import observation_status
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0)
  opener=Opener({'code':'MERC.US','timestamp':int(now.timestamp()),'close':'12.00','previousClose':'10.00','currency':'USD'});adapter=EODHDAdapter(None,1,opener)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}),patch('hotwatch_adapters.reserve'),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
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
  with self.assertRaisesRegex(ValueError,'quote_evidence_stale'):hotwatch_engine.sample_errors(stale,req,now)
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
 def test_closed_bar_uses_actual_bar_open_time_without_inventing_trade_time(self):
  from test_hotwatch_engine import request
  import hotwatch_engine
  req=request();req.update(provider='eodhd',provider_symbol='MERC.US');now=datetime.now(timezone.utc).replace(microsecond=0);adapter=EODHDAdapter(None,1,Opener({}));at=(now-timedelta(minutes=3)).isoformat()
  class Feeds:
   def minute_bars(self,*args):return {'status':'OK','bars':[{'bar_open_at':at,'open':'10','high':'12','low':'9','close':'11','volume':'50'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'1'}),patch.object(adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):sample=adapter.poll({'request_data':req})
  hotwatch_engine.sample_errors(sample,req,now);self.assertEqual(sample['event_time'],at);self.assertEqual(sample['price_time_kind'],'bar_open');self.assertEqual(sample['close'],'11');self.assertEqual(sample['volume_type'],'interval');self.assertEqual(sample['market_status'],'UNKNOWN')
