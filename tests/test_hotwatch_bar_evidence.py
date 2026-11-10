"""Causal feed fusion: all timestamps and bars below are synthetic."""
import copy, unittest
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
  self.sample=tick(self.now);self.sample.update(source='eodhd',feed_type='mock WS trade',price_time_kind='trade',bid_at=self.now.isoformat(),ask_at=self.now.isoformat(),status_at=self.now.isoformat(),quote_feed='us_quotes',status_feed='us_status')
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
 def test_missing_actual_volume_does_not_become_a_buy_input(self):
  sample=copy.deepcopy(self.sample);sample['bar_history'][-1]['volume']=None
  sample_errors(sample,self.req,self.now);metrics=features(verified_bar_samples(sample,self.req,self.now),BASELINE['parameters'])
  self.assertIsNone(metrics['relative_volume']);metrics['price']=sample['price'];metrics['spread_pct']='0.1'
  result,_=calculate(sample,metrics,BASELINE,self.req['risk'],{},self.now);self.assertNotEqual(result['signal'],'BUY')

if __name__=='__main__':unittest.main()
