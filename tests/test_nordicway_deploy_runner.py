import io
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import nordicway_deploy_runner as runner
from nordicway_deploy_sequence import Outcome

SHA = 'a' * 40
TOKEN = 'test_token_12345'


def crash_during_deploy(bridge):
    def die(adapter, sha):
        os._exit(23)
    runner.run(SHA, TOKEN, bridge=Path(bridge), adapter_factory=Mock(), deploy=die,
               prepare=lambda checkout, sha: None)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = Path(self.temp.name)
        (self.bridge / 'approved-sha').write_text(SHA + '\n')
        (self.bridge / 'approved-sha').chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def run_deploy(self, result):
        factory = Mock()
        response = runner.run(SHA, TOKEN, bridge=self.bridge, adapter_factory=factory,
                              deploy=lambda adapter, sha: result, prepare=lambda checkout, sha: None)
        self.assertEqual(factory.call_args.kwargs['cpanel_token'], TOKEN)
        self.assertNotIn(TOKEN, str(response))
        return response

    def test_approved_success_clears_claim(self):
        result = self.run_deploy(Outcome('ok', 'complete', True, '/private/backup'))
        self.assertFalse(result['recovery_required'])
        self.assertNotIn('/private/backup', str(result))
        self.assertFalse((self.bridge / 'deployment-incomplete.json').exists())

    def test_complete_update_of_intentionally_stopped_app_clears_claim(self):
        result = self.run_deploy(Outcome('updated_stopped', 'complete', False,
                                        '/private/backup'))
        self.assertEqual(result['status'], 'updated_stopped')
        self.assertFalse(result['service_restored'])
        self.assertFalse(result['recovery_required'])
        self.assertFalse((self.bridge / 'deployment-incomplete.json').exists())
        # No stale recovery marker should block the next independent release.
        again = self.run_deploy(Outcome('updated_stopped', 'complete', False))
        self.assertFalse(again['recovery_required'])

    def test_stopped_release_with_failed_stage_stays_blocked(self):
        result = self.run_deploy(Outcome('updated_stopped', 'verify_install', False))
        self.assertTrue(result['recovery_required'])
        self.assertTrue((self.bridge / 'deployment-incomplete.json').exists())

    def test_failure_blocks_a_second_attempt(self):
        result = self.run_deploy(Outcome('failed', 'backup_and_apply', False))
        self.assertTrue(result['recovery_required'])
        with self.assertRaises(FileExistsError):
            self.run_deploy(Outcome('ok', 'complete', True))

    def test_pre_stop_rejection_does_not_leave_recovery_block(self):
        for stage in ('authorization', 'preflight', 'quota', 'stage', 'service_state'):
            with self.subTest(stage=stage):
                result = self.run_deploy(Outcome('failed', stage, False))
                self.assertFalse(result['recovery_required'])
                self.assertFalse((self.bridge / 'deployment-incomplete.json').exists())
        self.assertEqual(self.run_deploy(Outcome('ok', 'complete', True))['status'], 'ok')

    def test_service_state_reason_is_forwarded_without_recovery_marker(self):
        result = self.run_deploy(Outcome('failed', 'service_state', False, reason='state_record_failed'))
        self.assertEqual(result['reason'], 'state_record_failed')
        self.assertFalse(result['recovery_required'])

    def test_stop_failure_still_requires_recovery(self):
        result = self.run_deploy(Outcome('failed', 'stop', False))
        self.assertTrue(result['recovery_required'])

    def test_checkout_failure_does_not_leave_recovery_block(self):
        def failed_checkout(checkout, sha):
            raise ValueError('checkout_not_clean')
        factory = Mock()
        result = runner.run(SHA, TOKEN, bridge=self.bridge, adapter_factory=factory,
                            prepare=failed_checkout)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['recovery_required'])
        self.assertFalse((self.bridge / 'deployment-incomplete.json').exists())
        factory.assert_not_called()

    def test_process_death_leaves_durable_block(self):
        child = multiprocessing.get_context('fork').Process(target=crash_during_deploy, args=(str(self.bridge),))
        child.start()
        child.join(10)
        self.assertEqual(child.exitcode, 23)
        self.assertTrue((self.bridge / 'deployment-incomplete.json').is_file())
        with self.assertRaises(FileExistsError):
            self.run_deploy(Outcome('ok', 'complete', True))

    def test_unapproved_or_unsafe_policy_never_calls_deploy(self):
        factory = Mock()
        for approval in ('b' * 40, 'HEAD', SHA + ';id'):
            (self.bridge / 'approved-sha').write_text(approval)
            with self.assertRaises(ValueError):
                runner.run(SHA, TOKEN, bridge=self.bridge, adapter_factory=factory)
        self.assertFalse(factory.called)
        (self.bridge / 'approved-sha').write_text(SHA)
        (self.bridge / 'approved-sha').chmod(0o644)
        with self.assertRaises(ValueError):
            runner.run(SHA, TOKEN, bridge=self.bridge, adapter_factory=factory)

    def test_request_is_bounded_and_has_only_token(self):
        with patch.object(runner, 'run', return_value={'status': 'ok'}) as call:
            self.assertEqual(runner.run_request(SHA, io.BytesIO(b'{"cpanel_token":"test_token_12345"}'))['status'], 'ok')
            call.assert_called_once_with(SHA, TOKEN)
        for data in (b'{}', b'{"cpanel_token":"x", "cmd":"id"}', b'x' * 4097):
            with self.assertRaises(ValueError):
                runner.run_request(SHA, io.BytesIO(data))
