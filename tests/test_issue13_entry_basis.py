"""Regression target for issue 13; all observations are synthetic."""
import copy
import unittest
from datetime import datetime, timedelta, timezone

from hotwatch_strategy import BASELINE, calculate
from test_hotwatch_engine import good_metrics, request, tick


class EntryBasis(unittest.TestCase):
 @unittest.expectedFailure
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

 def test_independent_verified_stop_still_sells(self):
  at=datetime(2026,11,11,15,0,tzinfo=timezone.utc)
  risk=copy.deepcopy(request()['risk']);risk['stop_price']='9.95'
  result,_=calculate(tick(at,price='9.90',held=True),good_metrics(),BASELINE,risk,{},at)
  self.assertEqual(result['signal'],'SELL')
  self.assertIn('STOP_BREACHED',result['reason_codes'])


if __name__=='__main__':unittest.main()
