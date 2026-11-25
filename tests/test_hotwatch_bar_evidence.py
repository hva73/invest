"""Causal feed fusion: all timestamps and bars below are synthetic."""
import copy, json, sqlite3, unittest
from unittest.mock import patch
from contextlib import nullcontext
from hotwatch_adapters import DataUnavailable,EODHDAdapter
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from test_hotwatch_engine import tick,request
from hotwatch_features import verified_bar_samples,features,observation_status
from hotwatch_strategy import BASELINE,calculate
from hotwatch_engine import sample_errors
from hotwatch_contract import EngineError

class BarEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,4,15,15,tzinfo=timezone.utc)
  self.req=request();self.req.update(provider='eodhd',provider_symbol='MERC.US')
  self.sample=tick(self.now);self.sample.update(session_key='2026-11-04:REGULAR',source='eodhd',feed_type='mock WS trade',price_time_kind='trade',bid_at=self.now.isoformat(),ask_at=self.now.isoformat(),status_at=self.now.isoformat(),quote_feed='us_quotes',status_feed='us_status')
  self.sample['bar_history']=[{'bar_open_at':(self.now-timedelta(minutes=35-i)).isoformat(),'open':str(100+i),'high':str(101+i),'low':str(99+i),'close':str(100+i),'volume':str(100+i)} for i in range(35)]
  self.sample['bar_evidence']={'provider_symbol':'MERC.US','market':'us','exchange':'US','timezone':'America/New_York','session_date':'2026-11-04','open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[],'schedule_received_at':self.now.isoformat(),'exchange_open':True,'feed':'eodhd_realtime_history'}
 def test_actual_bars_keep_time_and_volume(self):
  sample_errors(self.sample,self.req,self.now)
  actual=verified_bar_samples(self.sample,self.req,self.now)
  self.assertEqual(len(actual),35);self.assertEqual(actual[-1]['event_time'],self.sample['bar_history'][-1]['bar_open_at']);self.assertEqual(features(actual,BASELINE['parameters'])['interval_volume'],'134')
  display=observation_status([self.sample],self.now,120,'WAIT','ACTIVE');self.assertIsNotNone(display['momentum_pct']['30'])
 def test_unusable_history_is_excluded_without_rejecting_valid_observation(self):
  for edit in ('future','holiday','other_symbol','missing_calendar','stale_schedule'):
   sample=copy.deepcopy(self.sample)
   if edit=='future':sample['bar_history'][-1]['bar_open_at']=self.now.isoformat()
   if edit=='holiday':sample['bar_evidence']['excluded_dates']=['2026-11-04']
   if edit=='other_symbol':sample['bar_evidence']['provider_symbol']='OTHER.US'
   if edit=='missing_calendar':del sample['bar_evidence']['open']
   if edit=='stale_schedule':sample['bar_evidence']['schedule_received_at']=(self.now-timedelta(seconds=121)).isoformat()
   with self.subTest(edit=edit):
    if edit=='missing_calendar':
     with self.assertRaises(EngineError):sample_errors(sample,self.req,self.now)
    else:self.assertEqual(sample_errors(sample,self.req,self.now),sample)
    self.assertIsNone(verified_bar_samples(sample,self.req,self.now))
 def test_gaps_do_not_generate_fabricated_bars(self):
  sample=copy.deepcopy(self.sample);del sample['bar_history'][-4]
  sample_errors(sample,self.req,self.now)
  actual=verified_bar_samples(sample,self.req,self.now);metrics=features(actual,BASELINE['parameters'])
  self.assertEqual(len(actual),34);self.assertEqual(metrics['sample_count'],34)
  self.assertIsNotNone(metrics['macd_histogram'])
  # The absent minute stays absent; period indicators retain observed bars.
  self.assertIsNone(metrics['return_3_pct']);self.assertIsNotNone(metrics['return_1_pct'])
 def test_extended_bars_require_same_session_and_verified_trade_phase(self):
  for phase,at in [('PRE',datetime(2026,11,4,13,0,tzinfo=timezone.utc)),('AFTER',datetime(2026,11,4,22,0,tzinfo=timezone.utc))]:
   with self.subTest(phase=phase):
    sample=copy.deepcopy(self.sample);sample.update(event_time=at.isoformat(),market_status=phase,session_key='2026-11-04:'+phase,status_at=at.isoformat(),status_feed='us_trades',bid_at=at.isoformat(),ask_at=at.isoformat());sample['context']['as_of']=at.isoformat()
    sample['bar_evidence'].update(exchange_open=False,schedule_received_at=at.isoformat())
    sample['bar_history']=[dict(b,bar_open_at=(at-timedelta(minutes=35-i)).isoformat()) for i,b in enumerate(sample['bar_history'])]
    sample_errors(sample,self.req,at);self.assertEqual(len(verified_bar_samples(sample,self.req,at)),35)
    for field,value in [('status_feed','us_status'),('status_at',(at-timedelta(seconds=1)).isoformat())]:
     invalid=copy.deepcopy(sample);invalid[field]=value;self.assertIsNone(verified_bar_samples(invalid,self.req,at))
    invalid=copy.deepcopy(sample);invalid['bar_history'][0]['bar_open_at']=datetime(2026,11,4,15,0,tzinfo=timezone.utc).isoformat()
    self.assertIsNone(verified_bar_samples(invalid,self.req,at))
 def test_invalid_ohlc_is_not_eligible_for_features(self):
  sample=copy.deepcopy(self.sample);sample['bar_history'][-1]['high']='1'
  sample_errors(sample,self.req,self.now)
  self.assertIsNone(verified_bar_samples(sample,self.req,self.now))
 def test_bar_identity_and_reported_age_are_enforced(self):
  sample=copy.deepcopy(self.sample)
  sample['bar_history']=[dict(b,bar_open_at=(datetime.fromisoformat(b['bar_open_at'])-timedelta(seconds=60)).isoformat()) for b in sample['bar_history']]
  # The 146.6s bar is outside the same 120s gate even with a fresh trade.
  later=self.now+timedelta(seconds=86.6)
  self.assertIsNone(verified_bar_samples(sample,self.req,later))
  sample['session_key']='2026-11-03:REGULAR'
  self.assertIsNone(verified_bar_samples(sample,self.req,self.now))
  sample['session_key']='2026-11-04:REGULAR'
  self.assertIsNotNone(verified_bar_samples(sample,self.req,self.now))

 def test_stale_or_ambiguous_stream_can_only_use_independent_rest_observation(self):
  now=self.now;adapter=EODHDAdapter(None,1,object())
  session={'request_data':self.req}
  bar_at=(now-timedelta(seconds=146.6)).isoformat()
  adapter.feeds=lambda _:type('Feeds',(),{'minute_bars':lambda *_:{'status':'OK','bars':[{'bar_open_at':bar_at,'close':'98'}]}})()
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'1'}
  for ages,rest_age,allowed in [([126,414],1,True),([10,10],1,True),([10,10],10,False)]:
   with self.subTest(ages=ages,rest_age=rest_age):
    messages=[{'price':str(99+i),'event_time':(now-timedelta(seconds=age)).isoformat(),'received_at':now.isoformat()} for i,age in enumerate(ages)]
    rest_at=now-timedelta(seconds=rest_age)
    body={'code':'MERC.US','timestamp':int(rest_at.timestamp()),'close':'100','currency':'USD'}
    response=type('Response',(),{'read':lambda *_:json.dumps(body).encode()})()
    with patch.dict('os.environ',env),patch('hotwatch_adapters.utc',return_value=now),patch.object(adapter,'capture',return_value={'status':'OK','messages':messages}),patch.object(adapter.pluto,'safe_context',return_value=self.sample['context']),patch('hotwatch_adapters.Capacity.open',return_value=nullcontext(response)):
     if not allowed:
      with self.assertRaisesRegex(DataUnavailable,'EODHD_AMBIGUOUS_TRADE'):adapter.poll(session)
      continue
     sample=adapter.poll(session)
    self.assertEqual(sample['event_time'],rest_at.isoformat())
    self.assertEqual(sample['market_status'],'UNKNOWN')
    self.assertIsNone(sample['bid'])
    result,_=calculate(sample,features([sample],BASELINE['parameters']),BASELINE,self.req['risk'],{},now)
    self.assertEqual(result['signal'],'NO_DATA')
    self.assertIn('MARKET_STATUS_UNKNOWN',result['reason_codes'])

 def test_untimed_pluto_fallback_requires_exact_verified_link_and_keeps_history(self):
  from hotwatch_service import recover_automatic_feeds
  db=sqlite3.connect(':memory:');self.addCleanup(db.close);db.row_factory=sqlite3.Row
  db.executescript('''
   CREATE TABLE hw_system_control(id, killed);
   INSERT INTO hw_system_control VALUES (1,0);
   CREATE TABLE hw_control(user_id, killed);
   CREATE TABLE hw_sessions(id, user_id, purpose, status, is_test, lease_until, request, last_error, next_due);
   CREATE TABLE hw_feed_recovery(watch_row_id, next_attempt);
   CREATE TABLE hw_samples(watch_row_id);
   CREATE TABLE hw_verified_feed_links(user_id, asset_id, ticker, currency, exchange, symbol, isin, verified_epoch);
   CREATE TABLE hw_cxe_feed_evidence(user_id, asset_id);
  ''')
  req=dict(self.req,provider='pluto',provider_symbol=None,purpose='automatic holding watch',is_test=False,watch_mode='exit')
  db.execute("INSERT INTO hw_sessions VALUES (1,1,?,'DEGRADED',0,0,?,'PLUTO_QUOTE_TIME_UNKNOWN',0)",(req['purpose'],json.dumps(req)))
  db.execute('INSERT INTO hw_samples VALUES (1)')
  db.execute("INSERT INTO hw_verified_feed_links VALUES (1,?,'MERC','USD','NYSE','MERC.US','US1234567890',?)",(req['asset_id'],self.now.timestamp()))
  db.commit()
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY'}
  with patch.dict('os.environ',env),patch('hotwatch_service.holding_instrument') as lookup,patch('hotwatch_engine.event') as event:
   self.assertEqual(recover_automatic_feeds(lambda:db,self.now),0)
   self.assertEqual(json.loads(db.execute('SELECT request FROM hw_sessions').fetchone()[0]),req)
   db.execute("UPDATE hw_verified_feed_links SET exchange='NASDAQ'")
   db.commit()
   self.assertEqual(recover_automatic_feeds(lambda:db,self.now),1)
   lookup.assert_not_called()
   event.assert_called_once()
  self.assertEqual(json.loads(db.execute('SELECT request FROM hw_sessions').fetchone()[0]),dict(req,provider='eodhd',provider_symbol='MERC.US'))
  self.assertEqual(db.execute('SELECT count(*) FROM hw_samples').fetchone()[0],1)

 def test_fresh_verified_trade_and_closed_bars_reach_engine_after_stale_history(self):
  now=self.now;adapter=EODHDAdapter(None,1,object())
  session={'request_data':self.req}
  stale_bars=[dict(b,bar_open_at=(datetime.fromisoformat(b['bar_open_at'])-timedelta(minutes=3)).isoformat()) for b in self.sample['bar_history']]
  fresh_bars=list(reversed(self.sample['bar_history']))
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'1'}
  def capture(_,kind,*args):
   item={'event_time':now.isoformat()}
   if kind=='us_trades':item.update(price='90',market_session='open')
   elif kind=='us_quotes':item.update(bid='89.95',ask='90.05')
   else:item.update(trading_status='T')
   return {'status':'OK','messages':[item]}
  schedule={'status':'OK','exchange_open':True,'timezone':'America/New_York','received_at':now.isoformat(),'calendar':{'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}}
  for bars,history_age,expected_count in [(stale_bars,0,0),(fresh_bars,1,34),(fresh_bars,0,35)]:
   history_at=now-timedelta(seconds=history_age)
   feeds=type('Feeds',(),{'minute_bars':lambda *_:{'status':'OK','bars':bars,'received_at':history_at.isoformat()}})()
   with patch.dict('os.environ',env),patch('hotwatch_adapters.utc',return_value=now),patch.object(adapter,'capture',side_effect=capture),patch.object(adapter,'feeds',return_value=feeds),patch.object(adapter,'market_status',return_value=schedule),patch.object(adapter.pluto,'safe_context',return_value=tick(now,held=True)['context']):
    sample=adapter.poll(session)
   actual=verified_bar_samples(sample,self.req,now)
   self.assertEqual(len(actual or []),expected_count)
   self.assertEqual((sample['event_time'],sample['bid_at'],sample['session_key']),(now.isoformat(),now.isoformat(),'2026-11-04:REGULAR'))
   metrics=features(actual or [sample],BASELINE['parameters'])
   metrics['price']=sample['price']
   result,_=calculate(sample,metrics,BASELINE,self.req['risk'],{},now)
   self.assertEqual(result['signal'],'SELL')
   self.assertIn('STOP_BREACHED',result['reason_codes'])

 def test_missing_actual_volume_does_not_become_a_buy_input(self):
  sample=copy.deepcopy(self.sample);sample['bar_history'][-1]['volume']=None
  sample_errors(sample,self.req,self.now);metrics=features(verified_bar_samples(sample,self.req,self.now),BASELINE['parameters'])
  self.assertIsNone(metrics['relative_volume']);metrics['price']=sample['price'];metrics['spread_pct']='0.1'
  result,_=calculate(sample,metrics,BASELINE,self.req['risk'],{},self.now);self.assertNotEqual(result['signal'],'BUY')

if __name__=='__main__':unittest.main()
