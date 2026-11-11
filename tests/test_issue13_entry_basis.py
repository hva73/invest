"""Regression target for issue 13; all observations are synthetic."""
import copy
import unittest
import json
from datetime import datetime, timedelta, timezone

from hotwatch_strategy import BASELINE, calculate
from test_hotwatch_engine import good_metrics, request, tick


class EntryBasis(unittest.TestCase):
 def test_historical_market_high_is_not_a_verified_position_high(self):
  # The instrument reached 10.50 before the position was bought at 9.90.
  # There is no verified entry time or position high in the broker context.
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  metrics=good_metrics();metrics.update(price='9.90',distance_high_pct=str((9.90/10.50-1)*100))
  risk=copy.deepcopy(request()['risk']);risk['stop_price']=None
  state={}
  for seconds in (0,10,20):
   now=at+timedelta(seconds=seconds)
   sample=tick(now,price='9.90',held=True);sample['context']['cost_price']='9.90'
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertNotIn('TRAILING_EXIT',result['reason_codes'])
  self.assertNotEqual(result['signal'],'SELL')
  self.assertEqual(result['position_trailing']['status'],'WAITING_FOR_VERIFIED_POSITION_HISTORY')

 def test_independent_verified_stop_still_sells(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  risk=copy.deepcopy(request()['risk']);risk['stop_price']='9.95'
  result,_=calculate(tick(at,price='9.90',held=True),good_metrics(),BASELINE,risk,{},at)
  self.assertEqual(result['signal'],'SELL')
  self.assertIn('STOP_BREACHED',result['reason_codes'])

 def test_verified_post_observation_peak_and_restart(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one-cycle-one')
  state={};metrics=good_metrics();metrics['distance_high_pct']='-25'
  for seconds,price in ((0,'100'),(10,'105'),(20,'102'),(30,'102'),(40,'102')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True)
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
   state=json.loads(json.dumps(state)) # persisted state across restart
  self.assertEqual(result['signal'],'SELL')
  self.assertIn('TRAILING_EXIT',result['reason_codes'])
  self.assertEqual(result['signal_basis'],'verified_position_high')
  self.assertEqual(result['position_trailing']['high'],'105')
  self.assertEqual(result['position_trailing']['high_time'],(at+timedelta(seconds=10)).isoformat())
  duplicate,state=calculate(sample,metrics,BASELINE,risk,state,now,new_market_event=False)
  self.assertEqual(duplicate['signal'],'SELL')
  self.assertEqual(duplicate['position_trailing']['status'],'VERIFIED')

 def test_position_changes_and_unknown_evidence_reset_high(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='depot-one-cycle-one')
  metrics=good_metrics();state={}
  def run(second,price='100',change=None,scope=None):
   nonlocal state
   now=at+timedelta(seconds=second);sample=tick(now,second,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True)
   if change:sample['context'].update(change)
   r=dict(risk)
   if scope is not None:r['_position_scope']=scope
   result,state=calculate(sample,metrics,BASELINE,r,state,now)
   return result
  run(0);run(10,'105')
  # Additional buy / partial sale invalidates the old high.
  for seconds,change in ((20,{'quantity':'11'}),(30,{'quantity':'9'})):
   result=run(seconds,'100',change);self.assertNotIn('TRAILING_EXIT',result['reason_codes']);self.assertIsNone(result['position_trailing']['high'])
  run(40);run(50,'105')
  # An intervening complete sale and rebuy can restore the same quantity;
  # changed fill evidence still invalidates the previous high.
  orders=[{'order_id':'sell','status':'FILLED','requested_quantity':'10','filled_quantity':'10','side':'SELL'},{'order_id':'buy','status':'FILLED','requested_quantity':'10','filled_quantity':'10','side':'BUY'}]
  result=run(60,'100',{'orders':orders});self.assertNotIn('TRAILING_EXIT',result['reason_codes']);self.assertIsNone(result['position_trailing']['high'])
  result=run(70,'100',{'position_history_complete':False});self.assertEqual(result['position_trailing']['status'],'WAITING_FOR_VERIFIED_POSITION_HISTORY');self.assertNotIn('position_trailing',state)
  run(80);run(90,'105');result=run(100,'100',scope='depot-two-cycle-two');self.assertNotIn('TRAILING_EXIT',result['reason_codes']);self.assertIsNone(result['position_trailing']['high'])

 def test_unfilled_order_does_not_create_a_new_position(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='same-depot')
  state={};metrics=good_metrics()
  for seconds,price in ((0,'100'),(10,'105'),(20,'104')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True)
   if seconds==20:sample['context']['orders']=[{'order_id':'not-filled','status':'OPEN','requested_quantity':'1','filled_quantity':'0','side':'BUY'}]
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertEqual(result['position_trailing']['high'],'105')

 def test_long_observation_gap_cannot_reuse_the_old_high(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc);risk=copy.deepcopy(request()['risk']);risk.update(stop_price=None,_position_scope='same-depot')
  state={};metrics=good_metrics()
  for seconds,price in ((0,'100'),(10,'105'),(311,'100')):
   now=at+timedelta(seconds=seconds);sample=tick(now,seconds,price=price,held=True)
   sample['context'].update(orders_complete=True,position_history_complete=True)
   result,state=calculate(sample,metrics,BASELINE,risk,state,now)
  self.assertIsNone(result['position_trailing']['high'])
  self.assertNotIn('TRAILING_EXIT',result['reason_codes'])


if __name__=='__main__':unittest.main()
