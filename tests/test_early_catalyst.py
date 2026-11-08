"""Rules use synthetic evidence, never real money or invented historical data."""
import copy,unittest
from datetime import datetime,timedelta,timezone
from hotwatch_strategy import EARLY_CATALYST_V1,validate_strategy,early_watch,calculate
from hotwatch_features import features
from test_hotwatch_engine import tick,request,good_metrics

class EarlyCatalyst(unittest.TestCase):
 def setUp(self):
  self.spec=copy.deepcopy(EARLY_CATALYST_V1)
  self.m={'ordinary_share':True,'pluto_tradable':True,'catalyst_verified':True,'catalyst_age_minutes':'120','earnings_previous_session':False,'no_verified_news':False,'reference_gain_pct':'1','news_reaction_pct':'1','relative_volume':'1.5'}
 def test_schema_and_watch_are_separate_from_buy(self):
  self.assertEqual(validate_strategy(self.spec),[]);self.assertTrue(early_watch(self.spec,self.m))
  for key in ('ordinary_share','pluto_tradable'):
   self.assertFalse(early_watch(self.spec,{**self.m,key:False}));self.assertFalse(early_watch(self.spec,{**self.m,key:None}))
  self.assertFalse(early_watch(self.spec,{**self.m,'news_reaction_pct':'0.9','relative_volume':'1.4'}))
  self.assertTrue(early_watch(self.spec,{**self.m,'news_reaction_pct':'0','relative_volume':'1.5'}))
  self.assertFalse(early_watch(self.spec,{**self.m,'catalyst_age_minutes':'121'}))
  self.assertFalse(early_watch(self.spec,{**self.m,'catalyst_age_minutes':'-1'}))
  self.assertTrue(early_watch(self.spec,{**self.m,'catalyst_age_minutes':'1000','earnings_previous_session':True}))
  self.assertTrue(early_watch(self.spec,{**self.m,'catalyst_verified':False,'no_verified_news':True,'relative_volume':'3'}))
  self.assertFalse(early_watch(self.spec,{**self.m,'catalyst_verified':False,'no_verified_news':True,'relative_volume':'2.99'}))
  self.assertFalse(early_watch(self.spec,{**self.m,'reference_gain_pct':'10','news_reaction_pct':'0.1','relative_volume':'1'}))
  self.assertTrue(early_watch(self.spec,{**self.m,'reference_gain_pct':'0.1','news_reaction_pct':'1','relative_volume':'1'}))
 def test_uploaded_cases_explicitly_do_not_contain_trade_times(self):
  import json
  from pathlib import Path
  data=json.loads((Path(__file__).parent/'fixtures/early_catalyst_20261106.json').read_text())
  self.assertEqual({x['ticker'] for x in data['cases']},{'GOGO.US','STAK.US','KRMN.US','CIIT.US','AF.PA','AELIS.PA'})
  self.assertIn('Not verified',data['news_timestamps']);self.assertEqual(data['candle_interval'],'5m')
 def test_actual_three_minutes_not_three_sparse_observations(self):
  base=datetime.now(timezone.utc);p=self.spec['parameters']
  samples=[tick(base+timedelta(minutes=i),i,price=str(100+i)) for i in range(4)]
  self.assertEqual(features(samples,p)['return_window_pct'],'3.00')
  sparse=[tick(base+timedelta(minutes=5*i),i,price=str(100+i)) for i in range(4)]
  self.assertIsNone(features(sparse,p)['return_window_pct'])
 def test_buy_requires_confirmations_risk_and_not_macd(self):
  now=datetime.now(timezone.utc);sample=tick(now);risk={**request()['risk'],'entry_allowed':True,'exit_allowed':True}
  m={**good_metrics(),**self.m,'sample_count':20,'return_window_pct':'0.5','acceleration_pct_s2':'0.1','relative_volume':'1.8','spread_pct':'0.8','rsi':'90','reference_gain_pct':'15','macd_histogram':None}
  first,state=calculate(sample,m,self.spec,risk,{},now);self.assertEqual(first['signal'],'WAIT');self.assertIn('CONFIRMATION_PENDING',first['reason_codes'])
  later=now+timedelta(seconds=16);sample=tick(later,2);second,_=calculate(sample,m,self.spec,risk,state,later);self.assertEqual(second['signal'],'BUY')
  blocked,_=calculate(sample,{**m,'spread_pct':'1.01'},self.spec,risk,state,later);self.assertNotEqual(blocked['signal'],'BUY');self.assertIn('SPREAD_TOO_WIDE',blocked['reason_codes'])
  self.spec['parameters']['use_macd_confirmation']=True
  blocked,_=calculate(sample,m,self.spec,risk,state,later);self.assertNotEqual(blocked['signal'],'BUY')
  confirmed,_=calculate(sample,{**m,'macd_histogram':'0.1'},self.spec,risk,state,later);self.assertEqual(confirmed['signal'],'BUY')
 def test_diagnostics_separate_signal_risk_and_missing_data(self):
  now=datetime.now(timezone.utc);sample=tick(now);risk={**request()['risk'],'entry_allowed':True,'exit_allowed':True}
  m={**good_metrics(),**self.m,'sample_count':20,'return_window_pct':'0.6','acceleration_pct_s2':'0.1','relative_volume':'2','spread_pct':'0.5','rsi':'60','reference_gain_pct':'2'}
  wait,_=calculate(sample,{**m,'return_window_pct':'0.1'},self.spec,risk,{},now)
  self.assertEqual(wait['decision_diagnostics']['strategy'],'NOT_MET');self.assertEqual(wait['decision_diagnostics']['risk'],'NOT_EVALUATED')
  missing,_=calculate(sample,{**m,'return_window_pct':None},self.spec,risk,{},now)
  self.assertEqual(missing['decision_diagnostics']['strategy'],'UNKNOWN')
  sample['context']['fees_dkk']=None
  unknown,_=calculate(sample,m,self.spec,risk,{},now)
  self.assertEqual(unknown['decision_diagnostics']['strategy'],'MET');self.assertEqual(unknown['decision_diagnostics']['risk'],'MISSING_DATA');self.assertIn('RISK_INPUTS_UNKNOWN',unknown['decision_diagnostics']['missing_data_codes'])
  sample['context']['fees_dkk']='1';small={**risk,'max_notional_dkk':'10'}
  rejected,_=calculate(sample,m,self.spec,small,{},now)
  self.assertEqual(rejected['decision_diagnostics']['strategy'],'MET');self.assertEqual(rejected['decision_diagnostics']['risk'],'BLOCKED');self.assertIn('POSITION_SIZE_LIMIT',rejected['decision_diagnostics']['blocking_codes'])
  pending,_=calculate(sample,m,self.spec,risk,{},now)
  self.assertTrue(pending['decision_diagnostics']['confirmation_pending']);self.assertEqual(pending['decision_diagnostics']['risk'],'PASSED')
 def test_overheat_and_editable_thresholds(self):
  from hotwatch_strategy import matches
  p=self.spec['parameters'];m={**self.m,'return_window_pct':'0.5','relative_volume':'2','acceleration_pct_s2':'1','spread_pct':'0.5','rsi':'80','consolidating':False,'new_breakout':False,'new_setup':False}
  self.assertTrue(matches(self.spec['entry_rules'],{**m,'reference_gain_pct':'15'},p))
  self.assertFalse(matches(self.spec['entry_rules'],{**m,'reference_gain_pct':'15.01'},p))
  self.assertTrue(matches(self.spec['entry_rules'],{**m,'reference_gain_pct':'30','new_breakout':True},p))
  self.assertFalse(matches(self.spec['entry_rules'],{**m,'reference_gain_pct':'30.01','new_breakout':True},p))
  self.assertTrue(matches(self.spec['entry_rules'],{**m,'reference_gain_pct':'30.01','new_setup':True},p))
  self.spec['parameters']['news_max_age_minutes']=60;self.assertFalse(early_watch(self.spec,self.m))
  self.spec['parameters']['min_acceleration']='-1';self.assertTrue(validate_strategy(self.spec))
 def test_losing_news_or_overheat_confirmation_releases_buy(self):
  now=datetime.now(timezone.utc);sample=tick(now);risk={**request()['risk'],'entry_allowed':True,'exit_allowed':True}
  m={**good_metrics(),**self.m,'sample_count':20,'return_window_pct':'0.5','acceleration_pct_s2':'0.1','relative_volume':'1.8','spread_pct':'0.5','rsi':'80','reference_gain_pct':'20','consolidating':False,'new_breakout':False,'new_setup':False}
  state={'signal':'BUY','last_signal_at':now.timestamp(),'last_action_at':0}
  result,_=calculate(sample,m,self.spec,risk,state,now);self.assertNotEqual(result['signal'],'BUY')
if __name__=='__main__':unittest.main()
