import sys,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_drain_diagnostic as m

class Diagnostic(unittest.TestCase):
 def setup_adapter(self):
  a=Mock();a.lock.return_value=nullcontext();a.target=Path('/synthetic/app')
  a.service_status.return_value='started';a.service.status.return_value='stopped'
  return a
 def call(self,a,validate=lambda:True,classify=lambda _: {'passenger_active':1}):
  return m.diagnose(a,validate,lambda _:nullcontext(),lambda _:'passenger_active',classify)
 def test_drains_only_after_stop_and_recovers(self):
  a=self.setup_adapter();result=self.call(a)
  self.assertEqual(result['status'],'observed');self.assertTrue(result['health_verified'])
  self.assertEqual(result['classification'],{'passenger_active':1})
  a.stop_service.assert_called_once();a.start_service.assert_called_once();a.verify_recovery_health.assert_called_once()
 def test_stop_failure_still_attempts_recovery(self):
  a=self.setup_adapter();a.stop_service.side_effect=ValueError('stop')
  self.assertEqual(self.call(a)['status'],'observation_unavailable');a.start_service.assert_called_once()
 def test_validation_failure_never_stops(self):
  a=self.setup_adapter()
  def fail():raise ValueError('marker')
  self.assertEqual(self.call(a,validate=fail)['status'],'validation_or_lock_failed');a.stop_service.assert_not_called()
 def test_nontrue_validation_never_stops(self):
  a=self.setup_adapter();self.assertEqual(self.call(a,validate=lambda:False)['status'],'validation_or_lock_failed');a.stop_service.assert_not_called()
 def test_health_failure_is_not_claimed_as_recovered(self):
  a=self.setup_adapter();a.verify_recovery_health.side_effect=ValueError('health')
  result=self.call(a);self.assertEqual(result['status'],'recovery_unverified');self.assertFalse(result['health_verified'])
 def test_selector_change_invalidates_observation(self):
  a=self.setup_adapter();a.service.status.side_effect=['stopped','started']
  result=self.call(a);self.assertEqual(result['status'],'observation_unavailable');self.assertTrue(result['health_verified'])

if __name__=='__main__':unittest.main()
