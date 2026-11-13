import sys, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_stop_observer as observer

class Observation(unittest.TestCase):
 def test_snapshots_taken_only_after_selector_reports_stopped(self):
  states=iter(['started','started','stopped','stopped','started'])
  snapshots=iter([{'passenger_active':2},{'passenger_active':1}])
  result=observer.observe(SimpleNamespace(status=lambda:next(states)),lambda:next(snapshots),sleep=lambda _:None)
  self.assertEqual(result,{'status':'observed','selector_started_again':True,
                           'first':{'passenger_active':2},'last':{'passenger_active':1}})
 def test_not_running_before_test_is_rejected(self):
  self.assertEqual(observer.observe(SimpleNamespace(status=lambda:'stopped'),lambda:{}),{'status':'baseline_not_running'})
 def test_selector_failure_is_unavailable(self):
  def fail():raise ValueError('selector_failed')
  self.assertEqual(observer.observe(SimpleNamespace(status=fail),lambda:{}),{'status':'observation_unavailable'})
 def test_timeout_does_not_claim_observation(self):
  ticks=iter([0,0,2])
  result=observer.observe(SimpleNamespace(status=lambda:'started'),lambda:{},timeout=1,clock=lambda:next(ticks),sleep=lambda _:None)
  self.assertEqual(result,{'status':'timeout','stop_observed':False})

if __name__=='__main__':unittest.main()
