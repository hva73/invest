import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import apply_update
import nordicway_release_backup as check


class Backup(unittest.TestCase):
    def test_real_synthetic_backup_is_complete_and_changed_data_blocks_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'app'; source = target / 'opdatering/release'; source.mkdir(parents=True)
            (target / 'var/keys').mkdir(parents=True)
            (target / 'app.py').write_text('old code')
            (target / 'var/keys/token.key').write_bytes(b'synthetic-key')
            for name in ('app.py', 'BUILD_COMMIT'): (source / name).write_text('new code')
            database = target / 'var/escape.db'
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE items(value TEXT)'); db.execute("INSERT INTO items VALUES('before')")
            expected = check.inventory(target, ('app.py', 'BUILD_COMMIT'))
            with patch.object(apply_update, 'FILES', ('app.py', 'BUILD_COMMIT')):
                backup = apply_update.apply(source, target)
            self.assertTrue(check.verify_backup(backup, expected))
            baseline = check.database_digest(database)
            self.assertTrue(check.ensure_database_unchanged(database, baseline))
            with sqlite3.connect(database) as db: db.execute("INSERT INTO items VALUES('new user data')")
            with self.assertRaisesRegex(ValueError, 'database_changed_since_baseline'):
                check.ensure_database_unchanged(database, baseline)
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM items').fetchone()[0], 2)
            (backup / 'code/app.py').write_text('damaged')
            with self.assertRaisesRegex(ValueError, 'backup_mismatch'): check.verify_backup(backup, expected)

    def test_symlinks_and_live_journals_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'var').mkdir(); (root / 'app.py').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError, 'unsafe_path'): check.inventory(root, ('app.py',))
            database = root / 'var/escape.db'; database.write_bytes(b'not a real db')
            Path(str(database) + '-wal').write_bytes(b'test')
            with self.assertRaisesRegex(ValueError, 'database_not_quiescent'): check.database_digest(database)


if __name__ == '__main__': unittest.main()
