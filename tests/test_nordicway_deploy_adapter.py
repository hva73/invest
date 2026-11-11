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


if __name__ == '__main__': unittest.main()
