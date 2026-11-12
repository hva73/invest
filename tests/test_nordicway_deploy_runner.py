import io
import hashlib
import hmac
import json
import time
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import nordicway_deploy_runner as runner
import nordicway_owner_approval as owner
import nordicway_deploy_client as client
from types import SimpleNamespace
from nordicway_deploy_sequence import Outcome

SHA = 'a' * 40
TOKEN = 'test_token_12345'


def crash_during_deploy(bridge):
    def die(adapter, sha):
        os._exit(23)
    runner.run(SHA, TOKEN, bridge=Path(bridge), authorization_lock=Path(bridge)/'test-lock', adapter_factory=Mock(), deploy=die,
               prepare=lambda checkout, sha: None)


def crash_after_marker_before_ticket_consumption(bridge):
    original = Path.unlink
    def die(path, *args, **kwargs):
        if path.name == 'approval-ticket.json': os._exit(24)
        return original(path, *args, **kwargs)
    with patch.object(Path, 'unlink', die):
        runner.run(SHA, TOKEN, bridge=Path(bridge), authorization_lock=Path(bridge)/'test-lock',
                   adapter_factory=Mock(), prepare=lambda *_: None)


def hold_authorization_lock(lock, ready, release):
    with owner.deployment_lock(lock):
        ready.set()
        release.wait(5)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = Path(self.temp.name)
        (self.bridge / 'approved-sha').write_text(SHA + '\n')
        (self.bridge / 'approved-sha').chmod(0o600)
        (self.bridge / 'test-lock').touch(mode=0o600)
        self.ticket()

    def tearDown(self):
        self.temp.cleanup()

    def ticket(self, sha=SHA):
        path = self.bridge / 'approval-ticket.json'
        path.write_text(json.dumps({'sha':sha,'nonce':'1'*32,'expires':int(time.time())+60}))
        path.chmod(0o600)

    def run_deploy(self, result):
        if not (self.bridge / 'approval-ticket.json').exists(): self.ticket()
        factory = Mock()
        response = runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock', adapter_factory=factory,
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
        result = runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock', adapter_factory=factory,
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
                runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock', adapter_factory=factory)
        self.assertFalse(factory.called)
        (self.bridge / 'approved-sha').write_text(SHA)
        (self.bridge / 'approved-sha').chmod(0o644)
        with self.assertRaises(ValueError):
            runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock', adapter_factory=factory)

    def test_concurrent_authorization_lock_blocks_runner_before_claim(self):
        ctx = multiprocessing.get_context('fork')
        ready, release = ctx.Event(), ctx.Event()
        child = ctx.Process(target=hold_authorization_lock,
                            args=(self.bridge/'test-lock', ready, release))
        child.start()
        try:
            self.assertTrue(ready.wait(5))
            with self.assertRaises(BlockingIOError):
                self.run_deploy(Outcome('ok', 'complete', True))
            self.assertFalse((self.bridge/'deployment-incomplete.json').exists())
        finally:
            release.set()
            child.join(5)
            if child.is_alive(): child.terminate(); child.join()
        self.assertEqual(child.exitcode, 0)
        self.assertEqual(self.run_deploy(Outcome('ok', 'complete', True))['status'], 'ok')

    def test_crash_after_claim_blocks_replay(self):
        child = multiprocessing.get_context('fork').Process(
            target=crash_after_marker_before_ticket_consumption, args=(str(self.bridge),))
        child.start(); child.join(5)
        self.assertEqual(child.exitcode, 24)
        self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
        self.assertTrue((self.bridge/'approval-ticket.json').exists())
        with self.assertRaises(FileExistsError):
            runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock', adapter_factory=Mock())

    def test_signed_approval_to_claim_to_complete(self):
        key = b'k'*32
        keyfile = self.bridge/'owner-approval-key'
        keyfile.write_bytes(key); keyfile.chmod(0o600)
        nonce, expires = '2'*32, int(time.time())+60
        request = {'nonce':nonce, 'expires':expires,
                   'mac':hmac.new(key, owner.message(SHA,nonce,expires), hashlib.sha256).hexdigest()}
        owner.approve(self.bridge, self.bridge/'test-lock', SHA, request)
        result = runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock',
                            adapter_factory=Mock(), deploy=lambda *_: Outcome('ok','complete',True),
                            prepare=lambda *_: None)
        self.assertEqual(result['status'], 'ok')
        self.assertFalse((self.bridge/'approval-ticket.json').exists())
        with self.assertRaises(FileExistsError):
            owner.approve(self.bridge, self.bridge/'test-lock', SHA, request)
        with self.assertRaises(FileNotFoundError):
            runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock', adapter_factory=Mock())

    def test_client_payload_to_runner_is_sha_bound_end_to_end(self):
        key = bytes.fromhex('ab'*32)
        keyfile = self.bridge/'owner-approval-key'
        keyfile.write_bytes(key); keyfile.chmod(0o600)
        env = {'ESCAPE_RELEASE_SHA': SHA, 'ESCAPE_CPANEL_API_TOKEN': TOKEN,
               'ESCAPE_DEPLOY_AUTHORIZED':'1', 'ESCAPE_OWNER_APPROVAL_KEY':'ab'*32,
               'SSH_AUTH_SOCK':'/tmp/agent', 'NORDICWAY_KNOWN_HOST':'hostkey',
               'NORDICWAY_VERIFIED_FINGERPRINT':'fingerprint'}
        real_run = runner.run
        def run_in_test(sha, token, owner_request):
            return real_run(sha, token, bridge=self.bridge, authorization_lock=self.bridge/'test-lock',
                            owner_request=owner_request, adapter_factory=Mock(),
                            deploy=lambda *_: Outcome('ok','complete',True), prepare=lambda *_: None)
        def transport(command, **kwargs):
            self.assertEqual(command[-1], 'escape-deploy-v1 deploy '+SHA)
            with patch.object(runner, 'run', side_effect=run_in_test):
                result = runner.run_request(SHA, io.BytesIO(kwargs['input']))
            return SimpleNamespace(returncode=0, stdout=json.dumps(result).encode())
        with patch.object(client, 'verify', return_value='host key\n'):
            self.assertEqual(client.run(env, transport)['status'], 'ok')
        self.assertFalse((self.bridge/'approval-ticket.json').exists())

    def test_ticket_consumed_and_cannot_replay(self):
        result = runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock',
                            adapter_factory=Mock(), deploy=lambda *_: Outcome('ok', 'complete', True),
                            prepare=lambda *_: None)
        self.assertEqual(result['status'], 'ok')
        self.assertFalse((self.bridge/'approval-ticket.json').exists())
        with self.assertRaises(FileNotFoundError):
            runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock', adapter_factory=Mock())

    def test_ticket_for_other_sha_is_rejected_before_claim(self):
        self.ticket('b'*40)
        with self.assertRaisesRegex(ValueError, 'invalid_approval_ticket'):
            runner.run(SHA, TOKEN, bridge=self.bridge, authorization_lock=self.bridge/'test-lock', adapter_factory=Mock())
        self.assertFalse((self.bridge/'deployment-incomplete.json').exists())

    def test_request_is_bounded_and_has_only_token(self):
        with patch.object(runner, 'run', return_value={'status': 'ok'}) as call:
            self.assertEqual(runner.run_request(SHA, io.BytesIO(b'{"cpanel_token":"test_token_12345","approval":{}}'))['status'], 'ok')
            call.assert_called_once_with(SHA, TOKEN, owner_request={})
        for data in (b'{}', b'{"cpanel_token":"x", "cmd":"id"}', b'x' * 4097):
            with self.assertRaises(ValueError):
                runner.run_request(SHA, io.BytesIO(data))
