import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import nordicway_deploy_guard as guard


class GuardTests(unittest.TestCase):
    def test_only_ping_or_exact_sha_deploy(self):
        call = Mock()
        self.assertEqual(guard.dispatch('escape-deploy-v1 ping', execute=call)['status'], 'ok')
        for cmd in ('', 'id', 'escape-deploy-v1 deploy HEAD',
                    'escape-deploy-v1 deploy ' + 'a' * 40 + ';id',
                    'escape-deploy-v1 deploy ' + 'A' * 40, 'escape-deploy-v1 ping\nid'):
            with self.assertRaises(ValueError):
                guard.dispatch(cmd, execute=call)
        call.assert_not_called()

    def test_missing_symlink_or_writable_runner_denied(self):
        with tempfile.TemporaryDirectory() as root:
            runner = Path(root) / 'runner.py'
            with self.assertRaises(ValueError):
                guard.dispatch('escape-deploy-v1 deploy ' + 'a' * 40, runner=runner)
            runner.write_text(''); runner.chmod(0o666)
            with self.assertRaises(ValueError):
                guard.dispatch('escape-deploy-v1 deploy ' + 'a' * 40, runner=runner)
            runner.unlink(); runner.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                guard.dispatch('escape-deploy-v1 deploy ' + 'a' * 40, runner=runner)

    def test_fixed_argv_and_no_output_leak(self):
        with tempfile.TemporaryDirectory() as root:
            runner = Path(root) / 'runner.py'; runner.write_text(''); runner.chmod(0o600)
            execute = Mock(return_value=SimpleNamespace(returncode=1))
            result = guard.dispatch('escape-deploy-v1 deploy ' + 'b' * 40, runner=runner, python='/bin/python', execute=execute)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(execute.call_args.args[0], ['/bin/python', '-I', '-S', str(runner), 'b' * 40])


if __name__ == '__main__':
    unittest.main()
