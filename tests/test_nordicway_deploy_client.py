import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import nordicway_deploy_client as client


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.env = {'ESCAPE_RELEASE_SHA': 'a' * 40, 'ESCAPE_CPANEL_API_TOKEN': 'test_token_12345',
                    'ESCAPE_DEPLOY_AUTHORIZED': '1', 'SSH_AUTH_SOCK': '/tmp/agent',
                    'NORDICWAY_KNOWN_HOST': 'hostkey', 'NORDICWAY_VERIFIED_FINGERPRINT': 'fingerprint'}
        self.reply = {'operation': 'deploy', 'status': 'ok', 'stage': 'complete',
                      'service_restored': True, 'recovery_required': False}

    def test_fixed_command_and_secret_on_stdin(self):
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            result = client.run(self.env, send)
        self.assertEqual(result, self.reply)
        args, kwargs = send.call_args
        self.assertEqual(args[0][-1], 'escape-deploy-v1 deploy ' + 'a' * 40)
        self.assertNotIn(self.env['ESCAPE_CPANEL_API_TOKEN'], repr(args))
        self.assertEqual(json.loads(kwargs['input']), {'cpanel_token': self.env['ESCAPE_CPANEL_API_TOKEN']})

    def test_invalid_sha_never_connects(self):
        transport = Mock()
        self.env['ESCAPE_RELEASE_SHA'] = 'a' * 40 + ';id'
        self.assertEqual(client.run(self.env, transport)['status'], 'blocked')
        transport.assert_not_called()

    def test_resume_has_no_token_or_arbitrary_command(self):
        self.env['ESCAPE_DEPLOY_OPERATION'] = 'resume'
        self.env.pop('ESCAPE_CPANEL_API_TOKEN')
        reply = {'operation': 'resume', 'status': 'ok', 'recovery_required': False}
        send = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(reply).encode()))
        with patch.object(client, 'verify', return_value='host key\n'):
            self.assertEqual(client.run(self.env, send), reply)
        args, kwargs = send.call_args
        self.assertEqual(args[0][-1], 'escape-deploy-v1 resume ' + 'a' * 40)
        self.assertEqual(kwargs['input'], b'')

    def test_timeout_and_untrusted_reply_are_unknown(self):
        for transport in (Mock(side_effect=subprocess.TimeoutExpired('ssh', 1)),
                          Mock(return_value=SimpleNamespace(returncode=0, stdout=b'{"status":"ok"}'))):
            with patch.object(client, 'verify', return_value='host key\n'):
                result = client.run(self.env, transport)
            self.assertEqual(result['status'], 'unknown')
            self.assertTrue(result['recovery_required'])
