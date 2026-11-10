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
  rows=copy.deepcopy(self.bars);del rows[-3];self.assertEqual(valid_bars(rows,self.now),rows)
  rows=copy.deepcopy(self.bars);rows[-3]['high']='1';self.assertEqual(len(valid_bars(rows,self.now)),33)
  rows=copy.deepcopy(self.bars);rows[-3]['volume']=None;self.assertEqual(len(valid_bars(rows,self.now)),33)
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
 def test_sparse_history_status_keeps_actual_bars_without_fabricating_minute_returns(self):
  import app,hotwatch_engine as engine,hotwatch_warmup as warmup
  import test_hotwatch_engine as fixture
  from unittest.mock import patch
  f=fixture.HotWatch();f.setUp()
  try:
   now=f.now.replace(second=0,microsecond=0)
   req=dict(f.req,provider='eodhd',provider_symbol='MERC.US')
   # Forty actual closed bars, two minutes apart. No one-minute baseline.
   bars=[dict(self.bars[0],bar_open_at=(now-timedelta(minutes=79-2*i)).isoformat(),close=str(100+i/100)) for i in range(40)]
   with app.connect() as c:
    c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),req['watch_id']))
    row=engine.row_for(c,1,req['watch_id'],True)
    c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,req['asset_id'],req['ticker'],req['quote_currency'],req['exchange'],req['provider_symbol'],'US1234567890',now.timestamp()))
    c.execute('INSERT INTO hw_warmup_history VALUES(?,?,?,?,?,?)',(row['id'],req['provider_symbol'],now.isoformat(),json.dumps(bars),now.timestamp()+300,'OK'))
    with patch('hotwatch_engine.valid_cxe_evidence',return_value=None):result=warmup.status(c,row,req,now)
    self.assertEqual(result['count'],34);self.assertEqual(result['historical_count'],40)
    self.assertEqual(result['state'],'WARMUP COMPLETE');self.assertIsNotNone(result['metrics']['ema_long'])
    self.assertIsNone(result['metrics']['return_1_pct']);self.assertIsNone(result['metrics']['return_3_pct'])
    self.assertEqual(result['last_observed'],now.isoformat())
    self.assertEqual(c.execute('SELECT count(*) FROM hw_calculations').fetchone()[0],0)
    self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
  finally:f.tearDown()
 def test_quiet_history_is_reused_but_refreshes_when_market_wakes_or_new_data_arrives(self):
  import app,hotwatch_engine as engine,hotwatch_warmup as warmup
  import test_hotwatch_engine as fixture
  from unittest.mock import patch
  f=fixture.HotWatch();f.setUp()
  try:
   now=f.now;req=dict(f.req,provider='eodhd',provider_symbol='MERC.US')
   with app.connect() as c:
    c.execute('UPDATE hw_sessions SET request=?,is_test=0,last_data=? WHERE watch_id=?',(json.dumps(req),(now-timedelta(minutes=20)).isoformat(),req['watch_id']))
    row=engine.row_for(c,1,req['watch_id'],False)
    c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,req['asset_id'],req['ticker'],req['quote_currency'],req['exchange'],req['provider_symbol'],'US1234567890',now.timestamp()))
    c.execute('INSERT INTO hw_warmup_history VALUES(?,?,?,?,?,?)',(row['id'],req['provider_symbol'],(now-timedelta(minutes=10)).isoformat(),'[]',now.timestamp()-1,'NO_DATA'))
   class Feed:
    calls=0
    def intraday(self,*args,**kwargs):self.calls+=1;return {'status':'NO_DATA'}
   feed=Feed();job={'id':row['id'],'user_id':1,'is_test':False,'request_data':req}
   with patch('hotwatch_engine.valid_cxe_evidence',return_value=None),patch('hotwatch_engine.effective_poll_interval',return_value=60),patch('hotwatch_engine.quiet_market_interval',return_value=120):
    self.assertIsNone(warmup.refresh(app.connect,job,now,feed));self.assertEqual(feed.calls,0)
   with patch('hotwatch_engine.valid_cxe_evidence',return_value=None),patch('hotwatch_engine.effective_poll_interval',return_value=60),patch('hotwatch_engine.quiet_market_interval',return_value=60):
    self.assertEqual(warmup.refresh(app.connect,job,now,feed),'NO_DATA');self.assertEqual(feed.calls,1)
  finally:f.tearDown()
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
