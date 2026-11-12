import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import nordicway_deploy_client as client


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.env = {'ESCAPE_RELEASE_SHA': 'a' * 40, 'ESCAPE_CPANEL_API_TOKEN': 'test_token_12345',
                    'ESCAPE_DEPLOY_AUTHORIZED': '1', 'ESCAPE_OWNER_APPROVAL_PROOF': json.dumps({'nonce':'1'*32,'expires':2000,'mac':'a'*64}), 'SSH_AUTH_SOCK': '/tmp/agent',
                    'NORDICWAY_KNOWN_HOST': 'hostkey', 'NORDICWAY_VERIFIED_FINGERPRINT': 'fingerprint'}
        self.reply = {'operation': 'deploy', 'status': 'ok', 'stage': 'complete',
                      'service_restored': True, 'recovery_required': False, 'backup_cleanup': 'ok'}

    def test_fixed_command_and_secret_on_stdin(self):
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            result = client.run(self.env, send)
        self.assertEqual(result, self.reply)
        args, kwargs = send.call_args
        self.assertEqual(args[0][-1], 'escape-deploy-v1 deploy ' + 'a' * 40)
        self.assertNotIn(self.env['ESCAPE_CPANEL_API_TOKEN'], repr(args))
        payload = json.loads(kwargs['input'])
        self.assertEqual(payload['cpanel_token'], self.env['ESCAPE_CPANEL_API_TOKEN'])
        self.assertEqual(set(payload['approval']), {'nonce','expires','mac'})

    def test_app_deploy_sends_summary_and_token_only_on_stdin(self):
        self.env.update(ESCAPE_DEPLOY_OPERATION='app-deploy',ESCAPE_RELEASE_SUMMARY='Mobil og data')
        reply={'operation':'app-deploy','status':'completed','sha':'a'*40}
        send=Mock(return_value=SimpleNamespace(returncode=0,stdout=json.dumps(reply).encode()))
        with patch.object(client,'verify',return_value='host key\n'):
            result=client.run(self.env,send)
        self.assertEqual(result['status'],'ok')
        args,kwargs=send.call_args
        self.assertEqual(args[0][-1],'escape-deploy-v1 app-deploy '+'a'*40)
        self.assertEqual(json.loads(kwargs['input']),{'cpanel_token':'test_token_12345','summary':'Mobil og data'})
        self.assertNotIn('test_token_12345',repr(args))
        self.assertEqual(kwargs['timeout'],1740)
        for state in ('expired','unavailable','recovery','failed'):
            reply['status']=state;send.return_value=SimpleNamespace(returncode=1,stdout=json.dumps(reply).encode())
            with patch.object(client,'verify',return_value='host key\n'):
                self.assertEqual(client.run(self.env,send)['status'],state)

    def test_cleanup_warning_is_reported_without_mislabeling_release(self):
        self.reply['backup_cleanup'] = 'failed'
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            result = client.run(self.env, send)
        self.assertEqual((result['status'], result['backup_cleanup']), ('ok', 'failed'))

    def test_unknown_cleanup_status_is_rejected(self):
        self.reply['backup_cleanup'] = 'unknown-value'
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            result = client.run(self.env, send)
        self.assertEqual(result['status'], 'unknown')

    def test_completed_stopped_release_is_successful_but_remains_stopped(self):
        self.reply.update(status='updated_stopped', service_restored=False)
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            result = client.run(self.env, send)
        self.assertEqual(result['status'], 'updated_stopped')
        self.assertEqual(client.exit_code(result), 0)
        self.assertFalse(result['service_restored'])

    def test_incomplete_or_failed_stopped_reply_is_never_success(self):
        for changed in ({'stage': 'verify_install'}, {'recovery_required': True}):
            with self.subTest(changed=changed):
                self.reply.update(status='updated_stopped', stage='complete', recovery_required=False)
                self.reply.update(changed)
                send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.reply).encode()))
                with patch.object(client, 'verify', return_value='host key\n'):
                    result = client.run(self.env, send)
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(client.exit_code(result), 1)
        self.reply.update(status='updated_stopped', stage='complete', recovery_required=False)
        send = Mock(return_value=SimpleNamespace(returncode=1, stdout=json.dumps(self.reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            self.assertEqual(client.run(self.env, send)['status'], 'unknown')

    def test_legacy_reply_marks_cleanup_unknown(self):
        del self.reply['backup_cleanup']
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            result = client.run(self.env, send)
        self.assertEqual(result['backup_cleanup'], 'unknown')

    def test_invalid_sha_never_connects(self):
        transport = Mock()
        self.env['ESCAPE_RELEASE_SHA'] = 'a' * 40 + ';id'
        self.assertEqual(client.run(self.env, transport)['status'], 'blocked')
        transport.assert_not_called()

    def test_resume_has_no_token_or_arbitrary_command(self):
        self.env['ESCAPE_DEPLOY_OPERATION'] = 'resume'
        self.env.pop('ESCAPE_CPANEL_API_TOKEN')
        reply = {'operation': 'resume', 'status': 'ok', 'recovery_required': False, 'backup_cleanup': 'ok'}
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            self.assertEqual(client.run(self.env, send), reply)
        args, kwargs = send.call_args
        self.assertEqual(args[0][-1], 'escape-deploy-v1 resume ' + 'a' * 40)
        self.assertEqual(kwargs['input'], b'')

    def test_app_resume_is_fixed_and_sends_no_token(self):
        self.env['ESCAPE_DEPLOY_OPERATION']='app-resume'
        reply={'operation':'resume','status':'ok','recovery_required':False,'backup_cleanup':'ok'}
        send=Mock(return_value=SimpleNamespace(returncode=0,stdout=json.dumps(reply).encode()))
        with patch.object(client,'verify',return_value='host key\n'):
            self.assertEqual(client.run(self.env,send),reply)
        args,kwargs=send.call_args
        self.assertEqual(args[0][-1],'escape-deploy-v1 app-resume '+'a'*40)
        self.assertEqual(kwargs['input'],b'')

    def test_write_probe_is_fixed_and_needs_no_release_or_token(self):
        self.env['ESCAPE_DEPLOY_OPERATION'] = 'write-probe'
        self.env['ESCAPE_WRITE_PROBE_AUTHORIZED'] = '1'
        self.env.pop('ESCAPE_DEPLOY_AUTHORIZED')
        self.env.pop('ESCAPE_RELEASE_SHA')
        self.env.pop('ESCAPE_CPANEL_API_TOKEN')
        reply = {'operation': 'write_probe', 'status': 'ok'}
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            self.assertEqual(client.run(self.env, send), reply)
        args, kwargs = send.call_args
        self.assertEqual(args[0][-1], 'escape-deploy-v1 write-probe')
        self.assertEqual(kwargs['input'], b'')

    def test_probe_never_inherits_full_deploy_permission(self):
        transport = Mock()
        self.env['ESCAPE_DEPLOY_OPERATION'] = 'write-probe'
        self.env.pop('ESCAPE_RELEASE_SHA')
        self.assertEqual(client.run(self.env, transport)['status'], 'blocked')
        transport.assert_not_called()
        self.env.pop('ESCAPE_DEPLOY_AUTHORIZED')
        self.env['ESCAPE_WRITE_PROBE_AUTHORIZED'] = '1'
        self.env['ESCAPE_DEPLOY_OPERATION'] = 'deploy'
        self.env['ESCAPE_RELEASE_SHA'] = 'a' * 40
        self.assertEqual(client.run(self.env, transport)['status'], 'blocked')
        transport.assert_not_called()

    def test_timeout_and_untrusted_reply_are_unknown(self):
        for transport in (Mock(side_effect=subprocess.TimeoutExpired('ssh', 1)),
                          Mock(return_value=SimpleNamespace(returncode=0, stdout=b'{"status":"ok"}'))):
            with patch.object(client, 'verify', return_value='host key\n'):
                result = client.run(self.env, transport)
            self.assertEqual(result['status'], 'unknown')
            self.assertTrue(result['recovery_required'])

    def test_only_fixed_service_state_reasons_are_accepted(self):
        reply = dict(self.reply, status='failed', stage='service_state',
                     service_restored=False, backup_cleanup='not_run', reason='selector_failed')
        send = Mock(return_value=SimpleNamespace(returncode=1, stdout=json.dumps(reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            self.assertEqual(client.run(self.env, send)['reason'], 'selector_failed')
            reply['reason'] = 'selector_exit_nonzero'
            send.return_value.stdout = json.dumps(reply).encode()
            self.assertEqual(client.run(self.env, send)['reason'], 'selector_exit_nonzero')
            for value in ('secret content', 'other'):
                reply['reason'] = value
                send.return_value.stdout = json.dumps(reply).encode()
                self.assertEqual(client.run(self.env, send)['status'], 'unknown')

    def test_drain_reason_requires_fixed_value_and_failed_drain(self):
        reply = dict(self.reply, status='failed', stage='drain', service_restored=True,
                     recovery_required=True, backup_cleanup='not_run', reason='database_in_use')
        send = Mock(return_value=SimpleNamespace(returncode=1, stdout=json.dumps(reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            self.assertEqual(client.run(self.env, send)['reason'], 'database_in_use')
            reply['reason'] = 'private command line'
            send.return_value.stdout = json.dumps(reply).encode()
            self.assertEqual(client.run(self.env, send)['status'], 'unknown')
