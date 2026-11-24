import unittest
from unittest.mock import patch
import eodhd_feeds as feeds


class IntradayExactDedupe(unittest.TestCase):
 def setUp(self):
  feeds._intraday_cache.clear()
  feeds._history_cache.clear()
 def tearDown(self):
  feeds._intraday_cache.clear()
  feeds._history_cache.clear()
 def test_same_request_across_instances_preserves_timestamp_and_copies(self):
  a,b=feeds.EODHDFeeds('synthetic'),feeds.EODHDFeeds('synthetic')
  clock=[100.0]
  result={'status':'OK','received_at':'original','bars':[{'close':'10'}]}
  with patch.object(feeds.time,'monotonic',side_effect=lambda:clock[0]),patch.object(a,'_intraday_uncached',return_value=result) as fetch,patch.object(b,'_intraday_uncached',return_value={'status':'NO_DATA','received_at':'fresh','bars':[]}) as second:
   first=a.intraday('AAPL.US',start=60,end=120)
   first['bars'][0]['close']='999'
   clock[0]=100.9
   same=b.intraday('AAPL.US',start=60,end=120)
   self.assertEqual(same['received_at'],'original')
   self.assertEqual(same['bars'][0]['close'],'10')
   second.assert_not_called()
   clock[0]=101.0
   self.assertEqual(b.intraday('AAPL.US',start=60,end=120)['received_at'],'fresh')
   fetch.assert_called_once()
   second.assert_called_once()
 def test_exact_identity_interval_range_and_limit(self):
  a,b=feeds.EODHDFeeds('synthetic'),feeds.EODHDFeeds('other')
  with patch.object(feeds.time,'monotonic',return_value=100),patch.object(a,'_intraday_uncached',return_value={'status':'NO_DATA','received_at':'t','bars':[]}) as fetch,patch.object(b,'_intraday_uncached',return_value={'status':'NO_DATA','bars':[]}) as other:
   a.intraday('AAPL.US',start=60,end=120)
   a.intraday('AAPL.US',start=60,end=120)
   a.intraday('MSFT.US',start=60,end=120)
   a.intraday('AAPL.US',interval='5m',start=60,end=120)
   a.intraday('AAPL.US',start=61,end=120)
   a.intraday('AAPL.US',start=60,end=121)
   a.intraday('AAPL.US',start=60,end=120,max_points=5)
   b.intraday('AAPL.US',start=60,end=120)
   self.assertEqual(fetch.call_count,6)
   other.assert_called_once()
 def test_unbounded_and_custom_transport_not_cached(self):
  a=feeds.EODHDFeeds('synthetic')
  b=feeds.EODHDFeeds('synthetic',opener=object())
  with patch.object(a,'_intraday_uncached',return_value={'status':'NO_DATA'}) as fetch,patch.object(b,'_intraday_uncached',return_value={'status':'NO_DATA'}) as custom:
   for _ in range(2):
    a.intraday('AAPL.US')
    a.intraday('AAPL.US',start=60,end=120,max_points=None)
    a.intraday('AAPL.US',start=60,end=120,max_points=1001)
    b.intraday('AAPL.US',start=60,end=120)
   self.assertEqual(fetch.call_count,6)
   self.assertEqual(custom.call_count,2)
 def test_rate_budget_and_invalid_never_cached(self):
  a=feeds.EODHDFeeds('synthetic')
  statuses=['RATE_LIMIT','LOCAL_BUDGET_EXHAUSTED','INVALID_RESPONSE','NO_DATA']
  with patch.object(a,'_intraday_uncached',side_effect=[{'status':s} for s in statuses]) as fetch:
   for s in statuses:self.assertEqual(a.intraday('AAPL.US',start=60,end=120)['status'],s)
   self.assertEqual(fetch.call_count,4)
 def test_malformed_nonempty_is_not_no_data_or_cached(self):
  a=feeds.EODHDFeeds('synthetic')
  with patch.object(a,'_http',side_effect=[{'status':'OK','payload':[{'s':'OTHER','i':'1m','t':100000}]},{'status':'OK','received_at':'empty','payload':[]},{'status':'OK','payload':[{'timestamp':100}]},{'status':'OK','received_at':'empty','payload':[]}]) as fetch:
   self.assertEqual(a.minute_bars('us','AAPL')['status'],'INVALID_RESPONSE')
   self.assertEqual(a.minute_bars('us','AAPL')['status'],'NO_DATA')
   self.assertEqual(a.intraday('AAPL.US',start=60,end=120)['status'],'INVALID_RESPONSE')
   self.assertEqual(a.intraday('AAPL.US',start=60,end=120)['status'],'NO_DATA')
   self.assertEqual(fetch.call_count,4)

if __name__=='__main__':unittest.main()
