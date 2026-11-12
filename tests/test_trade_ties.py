import os, unittest, time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock
from test_hotwatch_engine import request
from test_eodhd_feeds import Opener, SECRET
from hotwatch_adapters import EODHDAdapter, DataUnavailable, unknown_context

class TradeAmbiguity(unittest.TestCase):
 def setUp(self):
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.req=request();self.req.update(provider='eodhd',provider_symbol='CRWV.US',ticker='CRWV')
  self.adapter=EODHDAdapter(None,1,Opener({}))
 def poll(self, prices, latest=False):
  now=self.now
  rows=[{'event_time':now.isoformat(),'price':p,'market_session':'extended-hours'} for p in prices]
  if latest: rows.append({'event_time':(now+timedelta(seconds=1)).isoformat(),'price':'56.40','market_session':'extended-hours'})
  class Feeds:
   def capture(_, *args, **kwargs):return {'status':'OK','messages':rows}
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':SECRET,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  clock=now+timedelta(seconds=2)
  with patch.dict(os.environ,env),patch.object(self.adapter,'feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()),patch('hotwatch_adapters.utc',return_value=clock):
   return self.adapter.poll({'request_data':self.req})
 def test_ambiguous_latest_timestamp_fails_closed_in_both_orders(self):
  for prices in [('56.44','56.43'),('56.43','56.44')]:
   with self.subTest(prices=prices):
    with self.assertRaises(DataUnavailable) as raised:self.poll(prices)
    self.assertEqual(raised.exception.code,'EODHD_AMBIGUOUS_TRADE')
    self.assertEqual(raised.exception.position_context,unknown_context())
 def test_newer_unambiguous_trade_recovers(self):
  sample=self.poll(['56.44','56.43'],latest=True)
  self.assertEqual(sample['price'],'56.40')
 def test_identical_prices_at_same_timestamp_remain_usable(self):
  sample=self.poll(['56.44','56.44'])
  self.assertEqual(sample['price'],'56.44')

class CrossBatchAmbiguity(unittest.TestCase):
 def test_equal_time_distinct_prices_survive_cache_refresh(self):
  from test_feed_reuse import FeedReuse
  import hotwatch_adapters as adapters
  fixture=FeedReuse();fixture.setUp()
  try:
   at=(fixture.now-timedelta(seconds=65)).isoformat()
   prior={'symbol':'MERC','event_time':at,'received_at':at,'price':'56.44','market_session':'extended-hours'}
   key=(1,fixture.credential,'us_trades','MERC')
   adapters._ws_batch_cache[key]=(time.monotonic()-65,{'status':'OK','messages':[prior]})
   client=Mock();client.capture.return_value={'status':'OK','messages':[dict(prior,price='56.43')]}
   result=fixture.adapter.capture(client,'us_trades','MERC',fixture.job)
   self.assertEqual({x['price'] for x in result['messages']},{'56.43','56.44'})
  finally:fixture.tearDown()
 def test_conflict_survives_older_capture_then_recovers_with_newer_trade(self):
  from test_feed_reuse import FeedReuse
  import hotwatch_adapters as adapters
  fixture=FeedReuse();fixture.setUp()
  try:
   at=(fixture.now-timedelta(seconds=65)).isoformat()
   previous={'symbol':'MERC','event_time':at,'received_at':at,'price':'56.44','market_session':'extended-hours'}
   key=(1,fixture.credential,'us_trades','MERC')
   adapters._ws_batch_cache[key]=(time.monotonic()-65,{'status':'OK','messages':[previous,dict(previous,price='56.43')]})
   older=dict(previous,event_time=(fixture.now-timedelta(seconds=75)).isoformat(),price='55')
   client=Mock();client.capture.return_value={'status':'OK','messages':[older]}
   result=fixture.adapter.capture(client,'us_trades','MERC',fixture.job)
   self.assertEqual({x['price'] for x in result['messages']},{'56.43','56.44'})
   # Expire the cache cadence while the original events remain fresh.
   saved,value=adapters._ws_batch_cache[key];adapters._ws_batch_cache[key]=(saved-65,value)
   newer=dict(previous,event_time=fixture.now.isoformat(),received_at=fixture.now.isoformat(),price='56.40')
   client.capture.return_value={'status':'OK','messages':[newer]}
   result=fixture.adapter.capture(client,'us_trades','MERC',fixture.job)
   self.assertEqual([x['price'] for x in result['messages']],['56.40'])
  finally:fixture.tearDown()

if __name__=='__main__': unittest.main(verbosity=2)
