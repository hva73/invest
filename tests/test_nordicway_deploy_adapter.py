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
import nordicway_quota
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
        with patch.object(nordicway_release_stage, 'APPROVED_SHA', self.sha), \
             patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')), \
             patch.object(nordicway_quota, 'verify_space',
                          side_effect=None if quota_ok else ValueError('quota_unavailable')):
            return sequence.deploy(adapter, self.sha)

    def test_actual_stage_updater_backup_and_installed_content(self):
        result = self.run_test()
        self.assertEqual(result.status, 'ok')
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'new')
        self.assertEqual((self.app / 'BUILD_COMMIT').read_text().strip(), self.sha)
        with sqlite3.connect(str(Path(result.backup) / 'escape.db')) as db:
            self.assertEqual(db.execute('SELECT x FROM positions').fetchone(), ('kept',))

    def test_unknown_quota_never_stops_or_modifies(self):
        result = self.run_test(quota_ok=False)
        self.assertEqual((result.status, result.stage), ('failed', 'quota'))
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')

    def test_no_quiescence_no_update_and_service_restored(self):
        result = self.run_test(quiescent=False)
        self.assertEqual((result.status, result.stage), ('failed', 'drain'))
        self.assertTrue(result.service_restored)
        self.assertEqual(self.service.state, 'started')
        self.assertEqual((self.app / 'app.py').read_text(), 'old')


if __name__ == '__main__': unittest.main()
