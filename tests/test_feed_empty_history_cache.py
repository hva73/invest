import unittest
from unittest.mock import patch
import eodhd_feeds

class EmptyHistoryCache(unittest.TestCase):
 def setUp(self):eodhd_feeds._history_cache.clear()
 def tearDown(self):eodhd_feeds._history_cache.clear()
 def test_empty_history_is_reused_briefly_then_new_bar_is_fetched(self):
  clock=[100.0];calls=[]
  def fetch(*args):
   calls.append(args)
   return {'status':'NO_DATA','received_at':'original'} if len(calls)==1 else {'status':'OK','received_at':'fresh','bars':[{'bar_open_at':'observed'}]}
  client=eodhd_feeds.EODHDFeeds('synthetic')
  with patch.object(eodhd_feeds.time,'monotonic',side_effect=lambda:clock[0]),patch.object(client,'_minute_bars_uncached',side_effect=fetch):
   self.assertEqual(client.minute_bars('us','AAPL')['received_at'],'original')
   clock[0]+=4.9;self.assertEqual(client.minute_bars('us','AAPL')['received_at'],'original');self.assertEqual(len(calls),1)
   clock[0]+=.1;self.assertEqual(client.minute_bars('us','AAPL')['received_at'],'fresh');self.assertEqual(len(calls),2)
 def test_budget_errors_are_never_cached(self):
  client=eodhd_feeds.EODHDFeeds('synthetic');responses=[{'status':'LOCAL_BUDGET_EXHAUSTED'},{'status':'OK','bars':[]}]
  with patch.object(client,'_minute_bars_uncached',side_effect=responses) as fetch:
   self.assertEqual(client.minute_bars('us','AAPL')['status'],'LOCAL_BUDGET_EXHAUSTED')
   self.assertEqual(client.minute_bars('us','AAPL')['status'],'OK');self.assertEqual(fetch.call_count,2)

if __name__=='__main__':unittest.main()
