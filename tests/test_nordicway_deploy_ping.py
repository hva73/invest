import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import nordicway_deploy_ping as p

class PingTests(unittest.TestCase):
    def test_reject_without_gate_or_host_key(self):
        run = Mock()
        self.assertEqual(p.ping({}, run)['status'], 'blocked')
        self.assertEqual(p.ping({'NORDICWAY_DEPLOY_PING_AUTHORIZED':'1', 'SSH_AUTH_SOCK':'x'}, run)['status'], 'failed')
        run.assert_not_called()

    def test_only_fixed_ping_and_strict_reply(self):
        env = {'NORDICWAY_DEPLOY_PING_AUTHORIZED':'1', 'SSH_AUTH_SOCK':'x'}
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout=b'{"status":"ok","operation":"ping"}'))
        with patch.object(p, 'verify', return_value='test host key\n'):
            self.assertEqual(p.ping(env, run)['status'], 'ok')
            command = run.call_args.args[0]
            self.assertEqual(command[-1], 'escape-deploy-v1 ping')
            self.assertIn('StrictHostKeyChecking=yes', command)
            run.return_value.stdout = b'{"status":"ok","operation":"deploy"}'
            self.assertEqual(p.ping(env, run)['status'], 'failed')

if __name__ == '__main__':
    unittest.main()
