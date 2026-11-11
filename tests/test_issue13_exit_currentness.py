"""Synthetic position/currentness regressions; no orders or user pushes."""
import copy,unittest
from datetime import datetime,timedelta,timezone
from hotwatch_strategy import BASELINE,calculate
from test_hotwatch_engine import good_metrics,request,tick

class ExitCurrentness(unittest.TestCase):
 def test_identical_exposure_in_another_portfolio_resets_exit_confirmation(self):
  at=datetime(2026,11,11,15,tzinfo=timezone.utc);metrics=good_metrics();metrics.update(return_3_pct='-3',breakdown=True)
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='portfolio-one');state={}
  for seconds in (0,10):
   now=at+timedelta(seconds=seconds);result,state=calculate(tick(now,seconds,price='100',held=True),metrics,BASELINE,risk,state,now)
  self.assertEqual(state['confirmations'],2)
  risk['_position_scope']='portfolio-two';now=at+timedelta(seconds=20)
  result,state=calculate(tick(now,20,price='100',held=True),metrics,BASELINE,risk,state,now)
  self.assertEqual(result['signal'],'WAIT');self.assertEqual(state['confirmations'],1)

 def test_changed_verified_exposure_resets_ordinary_exit_confirmation(self):
  at=datetime(2026,11,11,15,tzinfo=timezone.utc);metrics=good_metrics();metrics.update(return_3_pct='-3',breakdown=True)
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='one');state={}
  for seconds in (0,10):
   now=at+timedelta(seconds=seconds);result,state=calculate(tick(now,seconds,price='100',held=True),metrics,BASELINE,risk,state,now)
  self.assertEqual(state['confirmations'],2)
  now=at+timedelta(seconds=20);sample=tick(now,20,price='100',held=True);sample['context']['quantity']='11'
  result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['signal'],'WAIT');self.assertEqual(state['confirmations'],1)
 def test_unverified_trailing_does_not_suppress_critical_stop(self):
  at=datetime(2026,11,11,15,tzinfo=timezone.utc);metrics=good_metrics();metrics['distance_high_pct']='-3'
  risk=copy.deepcopy(request()['risk']);risk['stop_price']=None;state={}
  for seconds in (0,10,20):
   now=at+timedelta(seconds=seconds);result,state=calculate(tick(now,seconds,held=True),metrics,BASELINE,risk,state,now)
  self.assertNotEqual(result['signal'],'SELL');self.assertNotIn('TRAILING_EXIT',result['reason_codes'])
  now=at+timedelta(seconds=30);risk['stop_price']='101';sample=tick(now,30,held=True);sample['context']['quantity']='11'
  result,_=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['signal'],'SELL');self.assertIn('STOP_BREACHED',result['reason_codes'])
 def test_cost_change_resets_but_numeric_formatting_does_not(self):
  at=datetime(2026,11,11,15,tzinfo=timezone.utc);metrics=good_metrics();metrics.update(return_3_pct='-3',breakdown=True)
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='one');state={}
  for seconds,cost in ((0,'98'),(10,'98.00')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price='100',held=True);sample['context']['cost_price']=cost
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(state['confirmations'],2)
  now=at+timedelta(seconds=20);sample=tick(now,20,price='100',held=True);sample['context']['cost_price']='99'
  result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['signal'],'WAIT');self.assertEqual(state['confirmations'],1)
