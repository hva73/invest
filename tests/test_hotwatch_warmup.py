import copy, json, sqlite3, unittest
from datetime import datetime,timedelta,timezone
from hotwatch_warmup import valid_bars,signal_session_verified

class WarmupHistory(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,7,12,0,tzinfo=timezone.utc)
  self.bars=[{'bar_open_at':(self.now-timedelta(minutes=34-i)).isoformat(),'open':'100','high':'102','low':'99','close':'101','volume':'20'} for i in range(34)]
 def test_closed_bars_are_unique_sorted_and_limited(self):
  rows=valid_bars(list(reversed(self.bars))+[self.bars[0]],self.now)
  self.assertEqual(len(rows),34);self.assertEqual(rows[0],self.bars[0]);self.assertEqual(rows[-1],self.bars[-1])
 def test_gaps_invalid_ohlcv_future_and_conflicting_duplicates_never_fabricate_history(self):
  rows=copy.deepcopy(self.bars);del rows[-3];self.assertEqual(len(valid_bars(rows,self.now)),2)
  rows=copy.deepcopy(self.bars);rows[-3]['high']='1';self.assertEqual(len(valid_bars(rows,self.now)),2)
  rows=copy.deepcopy(self.bars);rows[-3]['volume']=None;self.assertEqual(len(valid_bars(rows,self.now)),2)
  rows=copy.deepcopy(self.bars);rows.append(dict(rows[-1],close='100'));self.assertEqual(valid_bars(rows,self.now),[])
  rows=copy.deepcopy(self.bars);rows.append(dict(rows[-1],bar_open_at=self.now.isoformat()));self.assertEqual(len(valid_bars(rows,self.now)),34)
 def test_real_rest_response_shape_is_parsed_for_btc_minute_history(self):
  from eodhd_feeds import EODHDFeeds
  payload=[{'timestamp':int(datetime.fromisoformat(x['bar_open_at']).timestamp()),'open':100,'high':102,'low':99,'close':101,'volume':20} for x in self.bars]
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps(payload).encode()
  class Opener:
   def open(self,request,timeout):
    self.url=request.full_url;return Response()
  client=Opener();result=EODHDFeeds('synthetic',opener=client).intraday('BTC-USD.CC',interval='1m',start=int(self.now.timestamp())-7200,end=int(self.now.timestamp()))
  self.assertEqual(result['status'],'OK');self.assertEqual(len(valid_bars(result['bars'],self.now)),34);self.assertIn('/intraday/BTC-USD.CC?',client.url);self.assertIn('interval=1m',client.url)
 def test_history_can_inform_signals_only_with_fresh_same_session_schedule(self):
  now=datetime(2026,11,6,15,15,tzinfo=timezone.utc);c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  c.execute('CREATE TABLE hw_exchange_calendar(exchange TEXT,received TEXT,timezone TEXT,calendar TEXT)')
  schedule={'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',now.isoformat(),'America/New_York',json.dumps(schedule)))
  req={'provider_symbol':'TSLA.US','risk':{'max_quote_age_s':120}};sample={'market_status':'REGULAR','event_time':now.isoformat()};history={'first_observed':(now-timedelta(minutes=33)).isoformat()}
  self.assertTrue(signal_session_verified(c,req,sample,history,now))
  self.assertFalse(signal_session_verified(c,req,dict(sample,market_status='PRE'),history,now))
  self.assertFalse(signal_session_verified(c,req,sample,{'first_observed':(now-timedelta(hours=2)).isoformat()},now))
  self.assertFalse(signal_session_verified(c,req,sample,history,now+timedelta(seconds=121)))
  self.assertFalse(signal_session_verified(c,dict(req,provider_symbol='BTC-USD.CC'),sample,history,now))

if __name__=='__main__':unittest.main()
