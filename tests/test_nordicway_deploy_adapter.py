import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apply_update
import nordicway_deploy_adapter as concrete
import nordicway_deploy_sequence as sequence
import nordicway_uapi_quota
import nordicway_release_stage
import nordicway_writer_check


class FakeService:
    def __init__(self): self.state = 'started'
    def status(self): return self.state
    def transition(self, operation):
        self.state = 'started' if operation == 'start' else 'stopped'
        return self.state


class AdapterIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.checkout = self.root / 'checkout'
        self.checkout.mkdir()
        self.app = self.root / 'escape_app'
        (self.app / 'var').mkdir(parents=True)
        (self.app / 'opdatering').mkdir()
        with sqlite3.connect(self.app / 'var' / 'escape.db') as db:
            db.execute('CREATE TABLE positions(x TEXT)')
            db.execute("INSERT INTO positions VALUES ('kept')")
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.checkout / 'apply_update.py').write_text("FILES=('app.py','BUILD_COMMIT')\n")
        (self.checkout / 'app.py').write_text('new')
        (self.checkout / 'BUILD_COMMIT').write_text('$Format:%H$\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'test')
        self.sha = self.git('rev-parse', 'HEAD').strip()
        (self.app / 'app.py').write_text('old')
        (self.app / 'BUILD_COMMIT').write_text('0' * 40 + '\n')
        self.service = FakeService()

    def tearDown(self): self.temp.cleanup()
    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.checkout), *args],
                              check=True, capture_output=True, text=True,
                              env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1'}).stdout

    def run_test(self, quiescent=True, quota_ok=True):
        adapter = concrete.Adapter(self.checkout, self.app, self.sha, 1000,
                                   lambda: quiescent, lambda sha: sha == self.sha,
                                   self.service)
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')), \
             patch.object(nordicway_uapi_quota, 'verify_space',
                          side_effect=(lambda path, required, token: {
                              'required_bytes': required, 'account_free_lower_bytes': required + 1,
                              'filesystem_free_bytes': required + 1}) if quota_ok else ValueError('quota_unavailable')):
            return sequence.deploy(adapter, self.sha)

    def test_actual_stage_updater_backup_and_installed_content(self):
        result = self.run_test()
        self.assertEqual(result.status, 'ok')
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'new')
        self.assertEqual((self.app / 'BUILD_COMMIT').read_text().strip(), self.sha)
        with sqlite3.connect(str(Path(result.backup) / 'escape.db')) as db:
            self.assertEqual(db.execute('SELECT x FROM positions').fetchone(), ('kept',))

    def test_restricted_runner_reaches_real_backup_and_update(self):
        import nordicway_deploy_guard
        import nordicway_deploy_runner
        bridge = self.root / 'bridge'
        bridge.mkdir(mode=0o700)
        approval = bridge / 'approved-sha'
        approval.write_text(self.sha + '\n')
        approval.chmod(0o600)
        def factory(checkout, target, approved, required, quiescence, health, cpanel_token):
            self.assertEqual(cpanel_token, 'test_token_12345')
            return concrete.Adapter(checkout, target, approved, required,
                 lambda: True, lambda sha: sha == self.sha, self.service,
                 quota_reader=lambda path, required: {'required_bytes': required,
                   'account_free_lower_bytes': required + 1, 'filesystem_free_bytes': required + 1})
        def restricted(sha):
            return nordicway_deploy_runner.run(sha, 'test_token_12345', bridge=bridge,
                   checkout=self.checkout, target=self.app, adapter_factory=factory)
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
            result = nordicway_deploy_guard.dispatch('escape-deploy-v1 deploy ' + self.sha, restricted)
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(result['recovery_required'])
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'new')
        with sqlite3.connect(self.app / 'var' / 'escape.db') as db:
            self.assertEqual(db.execute('SELECT x FROM positions').fetchone(), ('kept',))

    def test_prepare_checkout_pins_commit_and_preserves_dirty_checkout(self):
        import nordicway_deploy_runner
        first = self.sha
        (self.checkout / 'app.py').write_text('later')
        self.git('add', 'app.py')
        self.git('commit', '-qm', 'later')
        later = self.git('rev-parse', 'HEAD').strip()
        nordicway_deploy_runner.prepare_checkout(self.checkout, first)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), first)
        (self.checkout / 'app.py').write_text('unsaved work')
        with self.assertRaisesRegex(ValueError, 'checkout_not_clean'):
            nordicway_deploy_runner.prepare_checkout(self.checkout, later)
        self.assertEqual((self.checkout / 'app.py').read_text(), 'unsaved work')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), first)

    def test_interrupted_runner_records_verified_backup_before_replacement(self):
        import json
        import nordicway_deploy_runner
        bridge = self.root / 'bridge'
        bridge.mkdir(mode=0o700)
        approval = bridge / 'approved-sha'
        approval.write_text(self.sha + '\n')
        approval.chmod(0o600)
        def factory(checkout, target, approved, required, quiescence, health, cpanel_token):
            return concrete.Adapter(checkout, target, approved, required,
                lambda: True, lambda sha: True, self.service,
                quota_reader=lambda path, required: {'required_bytes': required,
                    'account_free_lower_bytes': required + 1, 'filesystem_free_bytes': required + 1})
        replace = os.replace
        def fail_code_replace(source, destination):
            if Path(destination) == self.app / 'app.py':
                raise OSError('simulated failure')
            return replace(source, destination)
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')), \
             patch.object(os, 'replace', side_effect=fail_code_replace):
            result = nordicway_deploy_runner.run(self.sha, 'test_token_12345', bridge=bridge,
                       checkout=self.checkout, target=self.app, adapter_factory=factory)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['recovery_required'])
        record = json.loads((bridge / 'deployment-incomplete.json').read_text())
        self.assertEqual(record['sha'], self.sha)
        backup = self.root / '.escape_backups' / record['backup']
        self.assertEqual((backup / 'code/app.py').read_text(), 'old')
        with sqlite3.connect(backup / 'escape.db') as db:
            self.assertEqual(db.execute('SELECT x FROM positions').fetchone(), ('kept',))

    def test_resume_restarts_only_complete_verified_install(self):
        import nordicway_deploy_runner
        bridge = self.root / 'bridge'
        bridge.mkdir(mode=0o700)
        approval = bridge / 'approved-sha'
        approval.write_text(self.sha + '\n')
        approval.chmod(0o600)
        healthy = [False]
        def factory(checkout, target, approved, required, quiescence, health, cpanel_token=None):
            return concrete.Adapter(checkout, target, approved, required,
                lambda: True, lambda sha: healthy[0], self.service,
                quota_reader=lambda path, required: {'required_bytes': required,
                    'account_free_lower_bytes': required + 1, 'filesystem_free_bytes': required + 1})
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
            result = nordicway_deploy_runner.run(self.sha, 'test_token_12345', bridge=bridge,
                       checkout=self.checkout, target=self.app, adapter_factory=factory)
            self.assertEqual((result['status'], result['stage']), ('failed', 'health'))
            self.assertTrue(result['recovery_required'])
            # An incomplete or damaged installed tree cannot be resumed.
            self.service.state = 'stopped'
            (self.app / 'app.py').write_text('partial')
            failed = nordicway_deploy_runner.resume(self.sha, bridge=bridge,
                       checkout=self.checkout, target=self.app, adapter_factory=factory)
            self.assertEqual(failed['status'], 'failed')
            self.assertEqual(self.service.state, 'stopped')
            (self.app / 'app.py').write_text('new')
            healthy[0] = True
            disabled = self.app / 'var' / 'hotwatch-autostart.disabled'
            disabled.touch()
            refused = nordicway_deploy_runner.resume(self.sha, bridge=bridge,
                       checkout=self.checkout, target=self.app, adapter_factory=factory)
            self.assertEqual(refused['status'], 'failed')
            self.assertEqual(self.service.state, 'stopped')
            disabled.unlink()
            resumed = nordicway_deploy_runner.resume(self.sha, bridge=bridge,
                       checkout=self.checkout, target=self.app, adapter_factory=factory)
        self.assertEqual(resumed['status'], 'ok')
        self.assertEqual(self.service.state, 'started')
        self.assertFalse((bridge / 'deployment-incomplete.json').exists())
        with sqlite3.connect(self.app / 'var' / 'escape.db') as db:
            self.assertEqual(db.execute('SELECT x FROM positions').fetchone(), ('kept',))

    def test_process_death_after_first_code_replace_is_not_resumed(self):
        import multiprocessing
        import nordicway_deploy_runner
        bridge = self.root / 'bridge'
        bridge.mkdir(mode=0o700)
        approval = bridge / 'approved-sha'
        approval.write_text(self.sha + '\n')
        approval.chmod(0o600)
        def factory(checkout, target, approved, required, quiescence, health, cpanel_token=None):
            return concrete.Adapter(checkout, target, approved, required,
                lambda: True, lambda sha: True, self.service,
                quota_reader=lambda path, required: {'required_bytes': required,
                    'account_free_lower_bytes': required + 1, 'filesystem_free_bytes': required + 1})
        def killed_update():
            replace = os.replace
            def replace_then_die(source, destination):
                replace(source, destination)
                if Path(destination) == self.app / 'app.py':
                    os._exit(23)
            with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')), \
                 patch.object(os, 'replace', side_effect=replace_then_die):
                nordicway_deploy_runner.run(self.sha, 'test_token_12345', bridge=bridge,
                    checkout=self.checkout, target=self.app, adapter_factory=factory)
        child = multiprocessing.get_context('fork').Process(target=killed_update)
        child.start()
        child.join(15)
        self.assertEqual(child.exitcode, 23)
        self.assertEqual((self.app / 'app.py').read_text(), 'new')
        self.assertNotEqual((self.app / 'BUILD_COMMIT').read_text().strip(), self.sha)
        self.service.state = 'stopped'
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
            result = nordicway_deploy_runner.resume(self.sha, bridge=bridge,
                       checkout=self.checkout, target=self.app, adapter_factory=factory)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.service.state, 'stopped')
        self.assertTrue((bridge / 'deployment-incomplete.json').exists())
        with sqlite3.connect(self.app / 'var' / 'escape.db') as db:
            self.assertEqual(db.execute('SELECT x FROM positions').fetchone(), ('kept',))
    def test_failed_backup_verification_prevents_any_code_replacement(self):
        adapter = concrete.Adapter(self.checkout, self.app, self.sha, 1000,
                                   lambda: True, lambda sha: True, self.service)
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')), \
             patch.object(adapter, 'verify_backup', side_effect=ValueError('invalid_backup')):
            release = nordicway_release_stage.stage(self.checkout, self.app, self.sha,
                                                    approved_sha=self.sha)
            with self.assertRaisesRegex(sequence.BackupVerificationFailure, 'backup_unverified'):
                adapter.backup_and_apply(release)
        self.assertEqual((self.app / 'app.py').read_text(), 'old')
        self.assertEqual((self.app / 'BUILD_COMMIT').read_text().strip(), '0' * 40)

    def test_failed_prewrite_backup_restarts_unchanged_service(self):
        adapter = concrete.Adapter(self.checkout, self.app, self.sha, 1000,
                                   lambda: True, lambda sha: True, self.service,
                                   quota_reader=lambda path, required: {
                                       'required_bytes': required,
                                       'account_free_lower_bytes': required + 1,
                                       'filesystem_free_bytes': required + 1})
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')), \
             patch.object(adapter, 'verify_backup', side_effect=ValueError('invalid_backup')):
            result = sequence.deploy(adapter, self.sha)
        self.assertEqual((result.status, result.stage), ('failed', 'backup_and_apply'))
        self.assertTrue(result.service_restored)
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')

    def test_interrupted_file_replacement_restores_original_code_and_database(self):
        adapter = concrete.Adapter(self.checkout, self.app, self.sha, 1000,
                                   lambda: True, lambda sha: True, self.service)
        real_replace = os.replace
        calls = []
        def fail_second(source, destination):
            calls.append(str(destination))
            if len(calls) == 2:
                raise OSError('simulated replacement failure')
            return real_replace(source, destination)
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
            release = nordicway_release_stage.stage(self.checkout, self.app, self.sha,
                                                    approved_sha=self.sha)
            with patch.object(apply_update.os, 'replace', side_effect=fail_second):
                with self.assertRaisesRegex(OSError, 'simulated replacement failure'):
                    adapter.backup_and_apply(release)
        self.assertEqual(len(calls), 2)
        self.assertEqual((self.app / 'app.py').read_text(), 'old')
        self.assertEqual((self.app / 'BUILD_COMMIT').read_text().strip(), '0' * 40)
        with sqlite3.connect(self.app / 'var' / 'escape.db') as db:
            self.assertEqual(db.execute('SELECT x FROM positions').fetchone(), ('kept',))

    def test_uapi_reader_feeds_real_deploy_sequence(self):
        import io, json
        from types import SimpleNamespace
        from unittest.mock import Mock
        class Response(io.BytesIO):
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        payload = {'result': {'status': 1, 'data': [{'id':'diskusage', '_count':'10',
                    '_max':'1000', 'units':'MB', 'normalized':1}]}}
        opener = Mock(); opener.open.return_value = Response(json.dumps(payload).encode())
        fs = lambda path: SimpleNamespace(f_bavail=10_000_000_000, f_frsize=1)
        reader = lambda path, required: nordicway_uapi_quota.verify_space(
                 path, required, 'a'*40, opener=opener, statvfs=fs)
        adapter = concrete.Adapter(self.checkout, self.app, self.sha, 1000,
                                   lambda: True, lambda sha: True, self.service,
                                   quota_reader=reader)
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
            result = sequence.deploy(adapter, self.sha)
        self.assertEqual(result.status, 'ok')
        self.assertEqual((self.app / 'app.py').read_text(), 'new')
        self.assertNotIn('a' * 40, repr(result))

    def test_invalid_quota_reader_cannot_authorize_release(self):
        adapter = concrete.Adapter(self.checkout, self.app, self.sha, 1000,
                                   lambda: True, lambda sha: True, self.service,
                                   quota_reader=lambda path, required: {'status':'ok'})
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
            result = sequence.deploy(adapter, self.sha)
        self.assertEqual((result.status, result.stage), ('failed', 'quota'))
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')

    def test_space_estimate_covers_database_staging_backup_and_margin(self):
        db_size = (self.app / 'var' / 'escape.db').stat().st_size
        estimate = concrete.estimate_required_bytes(self.checkout, self.app)
        self.assertGreaterEqual(estimate, 2 * db_size + 256 * 1024 * 1024)

    def test_space_estimate_rejects_unsafe_source(self):
        (self.checkout / 'app.py').unlink()
        (self.checkout / 'app.py').symlink_to(self.app / 'app.py')
        with self.assertRaisesRegex(ValueError, 'unsafe_manifest_file'):
            concrete.estimate_required_bytes(self.checkout, self.app)

    def test_unknown_quota_never_stops_or_modifies(self):
        result = self.run_test(quota_ok=False)
        self.assertEqual((result.status, result.stage), ('failed', 'quota'))
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')

    def test_mismatched_bridge_manifest_fails_before_service_stop(self):
        adapter = concrete.Adapter(self.checkout, self.app, self.sha, 1000,
                                   lambda: True, lambda sha: True, self.service,
                                   quota_reader=lambda path, required: {
                                       'required_bytes': required,
                                       'account_free_lower_bytes': required + 1,
                                       'filesystem_free_bytes': required + 1})
        # Same number of entries must not conceal different paths.
        with patch.object(apply_update, 'FILES', ('other.py', 'BUILD_COMMIT')):
            result = sequence.deploy(adapter, self.sha)
        self.assertEqual((result.status, result.stage), ('failed', 'preflight'))
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')
        self.assertFalse((self.root / '.escape_backups').exists())

    def test_quota_rejection_via_runner_allows_later_retry(self):
        import nordicway_deploy_runner
        bridge = self.root / 'bridge'
        bridge.mkdir(mode=0o700)
        approval = bridge / 'approved-sha'
        approval.write_text(self.sha + '\n')
        approval.chmod(0o600)
        allowed = [False]
        def factory(checkout, target, approved, required, quiescence, health, cpanel_token):
            def quota(path, amount):
                if not allowed[0]:
                    raise ValueError('quota_unavailable')
                return {'required_bytes': amount, 'account_free_lower_bytes': amount + 1,
                        'filesystem_free_bytes': amount + 1}
            return concrete.Adapter(checkout, target, approved, required,
                                    lambda: True, lambda sha: True, self.service,
                                    quota_reader=quota)
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
            rejected = nordicway_deploy_runner.run(self.sha, 'test_token_12345', bridge=bridge,
                        checkout=self.checkout, target=self.app, adapter_factory=factory)
            self.assertEqual((rejected['status'], rejected['stage']), ('failed', 'quota'))
            self.assertFalse(rejected['recovery_required'])
            self.assertEqual(self.service.state, 'started')
            allowed[0] = True
            accepted = nordicway_deploy_runner.run(self.sha, 'test_token_12345', bridge=bridge,
                        checkout=self.checkout, target=self.app, adapter_factory=factory)
        self.assertEqual(accepted['status'], 'ok')
        with sqlite3.connect(self.app / 'var' / 'escape.db') as db:
            self.assertEqual(db.execute('SELECT x FROM positions').fetchone(), ('kept',))

    def test_unapproved_sha_never_stops_or_modifies(self):
        adapter = concrete.Adapter(self.checkout, self.app, 'b' * 40, 1000,
                                   lambda: True, lambda sha: True, self.service)
        result = sequence.deploy(adapter, self.sha)
        self.assertEqual((result.status, result.stage), ('failed', 'authorization'))
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')

    def test_already_installed_version_is_not_reinstalled(self):
        (self.app / 'BUILD_COMMIT').write_text(self.sha + '\n')
        result = self.run_test()
        self.assertEqual((result.status, result.stage), ('failed', 'authorization'))
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')

    def test_no_quiescence_no_update_and_service_restored(self):
        result = self.run_test(quiescent=False)
        self.assertEqual((result.status, result.stage), ('failed', 'drain'))
        self.assertTrue(result.service_restored)
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')

    def test_default_writer_check_refuses_release_before_update(self):
        adapter = concrete.Adapter(self.checkout, self.app, self.sha, 1000,
                                   None, lambda sha: True, self.service,
                                   quota_reader=lambda path, required: {
                                       'required_bytes': required,
                                       'account_free_lower_bytes': required + 1,
                                       'filesystem_free_bytes': required + 1})
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')), \
             patch.object(nordicway_writer_check, 'verify', return_value=False) as verify:
            result = sequence.deploy(adapter, self.sha)
        verify.assert_called_once_with(self.app / 'var' / 'escape.db')
        self.assertEqual((result.status, result.stage), ('failed', 'drain'))
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')


if __name__ == '__main__': unittest.main()
