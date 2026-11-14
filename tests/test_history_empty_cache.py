import unittest
from unittest.mock import Mock, patch
import eodhd_feeds as feeds


class HistoryEmptyCacheTests(unittest.TestCase):
 def setUp(self):
  feeds._history_cache.clear()
  self.client=object.__new__(feeds.EODHDFeeds)
  self.client._shared_status=True;self.client._key='fixture'

 def test_empty_is_shared_for_one_second_then_refetched(self):
  self.client._minute_bars_uncached=Mock(side_effect=[{'status':'NO_DATA','received_at':'original'},{'status':'OK','bars':[{'close':'1'}]}])
  with patch.object(feeds.time,'monotonic',side_effect=[10,10,10.5,11.01,11.01]):
   first=self.client.minute_bars('us','AAA');second=self.client.minute_bars('us','AAA');third=self.client.minute_bars('us','AAA')
  self.assertEqual(first,second);self.assertEqual(second['received_at'],'original');self.assertEqual(third['status'],'OK');self.assertEqual(self.client._minute_bars_uncached.call_count,2)

 def test_errors_not_cached_and_symbols_isolated(self):
  self.client._minute_bars_uncached=Mock(side_effect=[{'status':'RATE_LIMIT'},{'status':'NO_DATA'},{'status':'NO_DATA'}])
  self.client.minute_bars('us','AAA');self.client.minute_bars('us','AAA');self.client.minute_bars('us','BBB')
  self.assertEqual(self.client._minute_bars_uncached.call_count,3)

 def test_positive_result_keeps_existing_twenty_second_cache(self):
  self.client._minute_bars_uncached=Mock(return_value={'status':'OK','bars':[]})
  with patch.object(feeds.time,'monotonic',side_effect=[10,10,29.9]):
   self.client.minute_bars('us','AAA');self.client.minute_bars('us','AAA')
  self.assertEqual(self.client._minute_bars_uncached.call_count,1)

if __name__=='__main__':unittest.main()
