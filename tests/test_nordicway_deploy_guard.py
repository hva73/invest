import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import unittest
import os
import tempfile
from unittest.mock import patch
import nordicway_deploy_guard as guard

class GuardTests(unittest.TestCase):
    def test_deploy_activation_is_explicit_private_and_not_a_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / 'enabled'
            self.assertFalse(guard.deployment_enabled(marker))
            marker.write_text('1\n')
            marker.chmod(0o600)
            self.assertTrue(guard.deployment_enabled(marker))
            marker.chmod(0o644)
            self.assertFalse(guard.deployment_enabled(marker))
            marker.unlink()
            marker.symlink_to('/dev/null')
            self.assertFalse(guard.deployment_enabled(marker))

    def test_write_probe_creates_verifies_and_removes_only_fixed_marker(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(guard.write_probe(root), {'status': 'ok', 'operation': 'write_probe'})
            self.assertEqual(os.listdir(root), [])
            self.assertEqual(guard.dispatch('escape-deploy-v1 write-probe',
                                            probe=lambda: guard.write_probe(root))['status'], 'ok')

    def test_write_probe_rejects_existing_file_without_modification(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / guard.PROBE_FILENAME
            marker.write_text('existing')
            with self.assertRaises(FileExistsError):
                guard.write_probe(root)
            self.assertEqual(marker.read_text(), 'existing')

    def test_write_probe_rejects_symlink_directory_and_extra_commands(self):
        with tempfile.TemporaryDirectory() as root:
            actual = Path(root) / 'actual'
            actual.mkdir()
            link = Path(root) / 'link'
            link.symlink_to(actual, target_is_directory=True)
            with self.assertRaises(OSError):
                guard.write_probe(link)
            self.assertEqual(os.listdir(actual), [])
        for command in ('escape-deploy-v1 write-probe x', 'escape-deploy-v1 write-probe;id',
                        'escape-deploy-v1 write-probe\n'):
            with self.assertRaises(ValueError):
                guard.dispatch(command, probe=lambda: {'status': 'ok'})

    def test_completed_stopped_release_has_success_exit_code(self):
        self.assertEqual(guard.exit_code({
            'operation': 'deploy', 'status': 'updated_stopped',
            'stage': 'complete', 'recovery_required': False}), 0)
        # A partial or uncertain install must never be reported as success.
        for response in (
            {'operation': 'deploy', 'status': 'updated_stopped',
             'stage': 'verify_install', 'recovery_required': True},
            {'operation': 'deploy', 'status': 'updated_stopped',
             'stage': 'complete', 'recovery_required': True},
            {'operation': 'deploy', 'status': 'updated_stopped',
             'stage': 'complete'},
            {'operation': 'resume', 'status': 'updated_stopped',
             'stage': 'complete', 'recovery_required': False},
            {'operation': 'deploy', 'status': 'failed',
             'stage': 'complete', 'recovery_required': False},
        ):
            self.assertEqual(guard.exit_code(response), 1)
        self.assertEqual(guard.exit_code({'status': 'ok', 'operation': 'ping'}), 0)

    def test_ping_and_deploy_blocked(self):
        self.assertEqual(guard.dispatch('escape-deploy-v1 ping')['status'], 'ok')
        self.assertEqual(guard.dispatch('escape-deploy-v1 deploy ' + 'a' * 40)['status'], 'blocked')

    def test_app_deploy_uses_only_exact_sha_and_explicit_handler(self):
        sha='a'*40;seen=[]
        self.assertEqual(guard.dispatch('escape-deploy-v1 app-deploy '+sha)['status'],'blocked')
        reply=guard.dispatch('escape-deploy-v1 app-deploy '+sha,app_runner=lambda value:seen.append(value) or {'operation':'app-deploy','status':'completed'})
        self.assertEqual(guard.exit_code(reply),0);self.assertEqual(seen,[sha])
        with self.assertRaises(ValueError):guard.dispatch('escape-deploy-v1 app-deploy '+sha+';id')

    def test_app_deploy_enters_fixed_venv_only_when_enabled(self):
        sha='a'*40
        with patch.dict(os.environ,{'SSH_ORIGINAL_COMMAND':'escape-deploy-v1 app-deploy '+sha}), \
             patch.object(guard,'deployment_enabled',return_value=True), \
             patch.object(guard.os,'execv',side_effect=OSError('synthetic')) as execute:
            self.assertEqual(guard.main(),1)
            execute.assert_called_once_with(guard.APP_PYTHON,[guard.APP_PYTHON,'-I',guard.APP_ENTRY,sha])
        with patch.dict(os.environ,{'SSH_ORIGINAL_COMMAND':'escape-deploy-v1 app-deploy '+sha}), \
             patch.object(guard,'deployment_enabled',return_value=False), \
             patch.object(guard.os,'execv') as execute:
            self.assertEqual(guard.main(),1);execute.assert_not_called()

    def test_app_resume_enters_fixed_venv_only_when_enabled(self):
        sha='a'*40
        with patch.dict(os.environ,{'SSH_ORIGINAL_COMMAND':'escape-deploy-v1 app-resume '+sha}), \
             patch.object(guard,'deployment_enabled',return_value=True), \
             patch.object(guard.os,'execv',side_effect=OSError('synthetic')) as execute:
            self.assertEqual(guard.main(),1)
            execute.assert_called_once_with(guard.APP_PYTHON,[guard.APP_PYTHON,'-I',guard.APP_ENTRY,sha,'resume'])
        with patch.dict(os.environ,{'SSH_ORIGINAL_COMMAND':'escape-deploy-v1 app-resume '+sha}), \
             patch.object(guard,'deployment_enabled',return_value=False), patch.object(guard.os,'execv') as execute:
            self.assertEqual(guard.main(),1);execute.assert_not_called()

    def test_rejects_arbitrary_commands(self):
        for cmd in ('', 'id', 'escape-deploy-v1 deploy HEAD',
                    'escape-deploy-v1 deploy ' + 'a' * 40 + ';id',
                    'escape-deploy-v1 deploy ' + 'A' * 40, 'escape-deploy-v1 ping\nid'):
            with self.assertRaises(ValueError):
                guard.dispatch(cmd)

    def test_only_exact_deploy_command_reaches_runner(self):
        seen = []
        def runner(sha):
            seen.append(sha)
            return {'status': 'ok', 'operation': 'deploy'}
        sha = 'b' * 40
        self.assertEqual(guard.dispatch('escape-deploy-v1 deploy ' + sha, runner)['status'], 'ok')
        self.assertEqual(seen, [sha])
        with self.assertRaises(ValueError):
            guard.dispatch('escape-deploy-v1 deploy ' + sha + ';id', runner)
        self.assertEqual(seen, [sha])

    def test_resume_requires_exact_sha_and_fixed_handler(self):
        seen = []
        self.assertEqual(guard.dispatch('escape-deploy-v1 resume ' + 'a' * 40)['status'], 'blocked')
        result = guard.dispatch('escape-deploy-v1 resume ' + 'a' * 40,
                                recovery=lambda sha: seen.append(sha) or {'status': 'ok'})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(seen, ['a' * 40])
        with self.assertRaises(ValueError):
            guard.dispatch('escape-deploy-v1 resume ' + 'a' * 40 + ';id', recovery=lambda sha: None)

if __name__ == '__main__':
    unittest.main()
