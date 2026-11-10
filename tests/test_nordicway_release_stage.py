import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_release_stage as release
import apply_update


class Stage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.checkout = root / 'checkout'; self.checkout.mkdir()
        self.target = root / 'app'; (self.target / 'var').mkdir(parents=True)
        (self.target / 'opdatering').mkdir()
        with sqlite3.connect(self.target / 'var/escape.db') as db:
            db.execute('CREATE TABLE preserved(value)'); db.execute("INSERT INTO preserved VALUES('keep')")
        self.git('init', '-q'); self.git('config', 'user.name', 'Test'); self.git('config', 'user.email', 'test@example.invalid')
        (self.checkout / 'apply_update.py').write_text("FILES=('app.py','BUILD_COMMIT')\n")
        (self.checkout / 'app.py').write_text('new app\n')
        (self.checkout / 'BUILD_COMMIT').write_text('$Format:%H$\n')
        (self.target / 'app.py').write_text('old app\n')
        self.git('add', '.'); self.git('commit', '-qm', 'synthetic')
        self.sha = self.git('rev-parse', 'HEAD').strip()

    def tearDown(self): self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.checkout), *args], capture_output=True,
                              text=True, check=True, env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1'}).stdout

    def test_exact_git_release_stages_and_feeds_existing_updater(self):
        before = (self.target / 'var/escape.db').read_bytes()
        with patch.object(release, 'APPROVED_SHA', self.sha):
            staged = release.stage(self.checkout, self.target, self.sha)
        self.assertEqual((staged['path'] / 'BUILD_COMMIT').read_text(), self.sha + '\n')
        self.assertEqual((staged['path'] / 'app.py').read_text(), 'new app\n')
        self.assertEqual((self.target / 'app.py').read_text(), 'old app\n')
        self.assertEqual((self.target / 'var/escape.db').read_bytes(), before)
        # Only synthetic temporary files are installed in this integration test.
        with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
            backup = apply_update.apply(staged['path'], self.target)
        self.assertEqual((self.target / 'app.py').read_text(), 'new app\n')
        self.assertEqual((backup / 'code/app.py').read_text(), 'old app\n')
        with sqlite3.connect(backup / 'escape.db') as db:
            self.assertEqual(db.execute('SELECT value FROM preserved').fetchone()[0], 'keep')

    def test_wrong_sha_and_unsafe_or_dirty_checkout_fail_without_staging(self):
        with patch.object(release, 'APPROVED_SHA', self.sha):
            with self.assertRaisesRegex(ValueError, 'unapproved_release'):
                release.stage(self.checkout, self.target, 'a' * 40)
            (self.checkout / 'app.py').write_text('tampered\n')
            with self.assertRaisesRegex(ValueError, 'preflight_failed'):
                release.stage(self.checkout, self.target, self.sha)
        self.assertEqual(list((self.target / 'opdatering').iterdir()), [])
        self.assertEqual((self.target / 'app.py').read_text(), 'old app\n')

    def test_staging_failure_removes_only_temporary_stage(self):
        with patch.object(release, 'APPROVED_SHA', self.sha), patch.object(release, 'MAX_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'manifest_too_large'):
                release.stage(self.checkout, self.target, self.sha)
        self.assertEqual(list((self.target / 'opdatering').iterdir()), [])
        self.assertEqual((self.target / 'app.py').read_text(), 'old app\n')


if __name__ == '__main__': unittest.main()
