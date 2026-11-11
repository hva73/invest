import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_prepare_drain_retry as recovery


class PrepareRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.bridge = root / 'bridge'
        self.bridge.mkdir(mode=0o700)
        self.app = root / 'app'
        (self.app / 'var').mkdir(parents=True)
        (self.app / 'var' / 'escape.db').write_bytes(b'holdings and new writes')
        self.repo = root / 'repo'
        self.repo.mkdir()
        self.marker = self.bridge / 'deployment-incomplete.json'
        self.record = {'format': 1, 'sha': recovery.RELEASE, 'state': 'started',
                       'motor_enabled': True, 'motor_disabled': False}
        self.write_private('approved-sha', (recovery.RELEASE + '\n').encode())
        self.write_private('deploy-enabled', b'1\n')
        self.write_private('deployment-incomplete.json', (json.dumps(self.record) + '\n').encode())
        self.files = Mock()
        self.runtime = Mock()
        self.install = Mock()
        bridge_check = patch.object(recovery, '_verify_bridge_modules')
        bridge_check.start()
        self.addCleanup(bridge_check.stop)

    def write_private(self, name, data):
        path = self.bridge / name
        path.write_bytes(data)
        path.chmod(0o600)

    def run_prepare(self):
        return recovery.prepare(self.repo, self.bridge, self.app,
                                verify_runtime=self.runtime, verify_files=self.files, install=self.install)

    def test_success_archives_marker_only_after_install_and_checks(self):
        original = self.marker.read_bytes()
        def install(repo, bridge, bundle):
            self.assertFalse((bridge / 'deploy-enabled').exists())
            self.assertEqual(self.marker.read_bytes(), original)
            self.assertEqual(bundle, recovery.BUNDLE)
        self.install.side_effect = install
        self.assertEqual(self.run_prepare()['status'], 'ready')
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.bridge / 'deploy-enabled').read_bytes(), b'1\n')
        archives = list(self.bridge.glob('recovery-reviewed-*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), original)
        self.assertEqual((self.app / 'var' / 'escape.db').read_bytes(), b'holdings and new writes')
        self.assertEqual(self.files.call_count, 2)
        self.assertEqual(self.runtime.call_count, 2)

    def test_backup_or_changed_state_refuses_before_mutation(self):
        for change in ({'backup': 'example'}, {'state': 'stopped'}, {'motor_enabled': False}, {'format': True}):
            record = dict(self.record, **change)
            self.write_private('deployment-incomplete.json', json.dumps(record).encode())
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_prepare()
            self.assertTrue(self.marker.exists())
            self.assertTrue((self.bridge / 'deploy-enabled').exists())
            self.install.assert_not_called()

    def test_install_or_post_install_health_failure_preserves_marker_and_closes_gate(self):
        for failure in ('install', 'post_health'):
            with self.subTest(failure=failure):
                self.write_private('deploy-enabled', b'1\n')
                self.install.reset_mock(side_effect=True)
                self.runtime.reset_mock(side_effect=True)
                if failure == 'install':
                    self.install.side_effect = ValueError('bridge_install_failed')
                else:
                    self.runtime.side_effect = [None, ValueError('motor_unavailable')]
                with self.assertRaises(ValueError):
                    self.run_prepare()
                self.assertTrue(self.marker.exists())
                self.assertFalse((self.bridge / 'deploy-enabled').exists())

    def test_first_verification_failure_leaves_gate_closed_and_marker_intact(self):
        original = self.marker.read_bytes()
        def check_files(repo, app):
            self.assertFalse((self.bridge / 'deploy-enabled').exists())
            raise ValueError('installed_file_mismatch')
        self.files.side_effect = check_files
        with self.assertRaisesRegex(ValueError, 'installed_file_mismatch'):
            self.run_prepare()
        self.assertEqual(self.marker.read_bytes(), original)
        self.assertFalse((self.bridge / 'deploy-enabled').exists())
        self.install.assert_not_called()

    def test_concurrent_marker_change_never_clears_recovery(self):
        def install(repo, bridge, bundle):
            self.marker.write_text('changed')
        self.install.side_effect = install
        with self.assertRaisesRegex(ValueError, 'recovery_changed'):
            self.run_prepare()
        self.assertEqual(self.marker.read_text(), 'changed')
        self.assertFalse((self.bridge / 'deploy-enabled').exists())

    def test_verify_files_rejects_changed_or_symlinked_application_file(self):
        (self.app / 'BUILD_COMMIT').write_text(recovery.INSTALLED + '\n')
        (self.app / 'app.py').write_bytes(b'expected')
        with patch.object(recovery, '_manifest', return_value=('BUILD_COMMIT', 'app.py')), \
             patch.object(recovery, '_git', return_value=b'expected'):
            recovery._verify_files(self.repo, self.app)
            (self.app / 'app.py').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'installed_file_mismatch'):
                recovery._verify_files(self.repo, self.app)
            (self.app / 'app.py').unlink()
            (self.app / 'app.py').symlink_to(self.app / 'BUILD_COMMIT')
            with self.assertRaisesRegex(ValueError, 'unsafe_app_file'):
                recovery._verify_files(self.repo, self.app)

    def test_real_git_manifest_comparison_and_prebackup_recovery(self):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL)
        git('init', '-q')
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@example.invalid')
        (self.repo / 'apply_update.py').write_text("FILES=('BUILD_COMMIT','app.py')\n")
        (self.repo / 'BUILD_COMMIT').write_text('$Format:%H$\n')
        (self.repo / 'app.py').write_bytes(b'original code')
        git('add', '.')
        git('commit', '-qm', 'fixture')
        sha = git('rev-parse', 'HEAD').decode().strip()
        (self.app / 'BUILD_COMMIT').write_text(sha + '\n')
        (self.app / 'app.py').write_bytes(b'original code')
        with patch.object(recovery, 'INSTALLED', sha):
            outcome = recovery.prepare(self.repo, self.bridge, self.app,
                                       verify_runtime=self.runtime, install=self.install)
        self.assertEqual(outcome['status'], 'ready')
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.app / 'var' / 'escape.db').read_bytes(), b'holdings and new writes')

    def test_runtime_requires_actual_processes_and_fresh_heartbeats(self):
        import sys
        enabled = self.app / 'var' / 'hotwatch-autostart.enabled'
        enabled.touch()
        report = {'installation': {'declared_commit': recovery.INSTALLED},
                  'database': {'status': 'ok', 'worker': {'status': 'running', 'age_seconds': 1},
                               'supervisor': {'status': 'running', 'age_seconds': 2}},
                  'processes': {'status': 'ok', 'counts': {'worker': 1, 'supervisor': 1}}}
        modules = {'nordicway_autostart': SimpleNamespace(_present=lambda path: path.exists()),
                   'nordicway_readonly_diagnostics': SimpleNamespace(inspect=lambda **kw: report),
                   'nordicway_release_service': SimpleNamespace(status=lambda: 'started')}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.geturl.return_value = recovery.HEALTH
        response.read.return_value = b'{"status":"ok","database":true}'
        with patch.dict(sys.modules, modules), patch.object(recovery, 'urlopen', return_value=response):
            recovery._verify_runtime(self.app, self.bridge)
            report['processes']['counts']['worker'] = 0
            with self.assertRaisesRegex(ValueError, 'motor_unavailable'):
                recovery._verify_runtime(self.app, self.bridge)


if __name__ == '__main__':
    unittest.main()
