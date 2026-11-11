import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import nordicway_writer_check as check


class WriterTests(unittest.TestCase):
    def test_cron_detection(self):
        def run(text, code=0, err=''):
            return Mock(return_value=subprocess.CompletedProcess([], code, text, err))
        self.assertTrue(check.no_cron(run('# comment\nPATH=/usr/bin\n')))
        self.assertTrue(check.no_cron(run('', 1, 'no crontab for user')))
        self.assertFalse(check.no_cron(run('* * * * * python task.py\n')))
        self.assertFalse(check.no_cron(run('', 1, 'permission denied')))
        self.assertFalse(check.no_cron(Mock(side_effect=OSError())))

    def test_open_database_file_and_passenger_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / 'escape.db'
            db.write_bytes(b'test')
            proc = root / 'proc'
            process = proc / '1234'
            (process / 'fd').mkdir(parents=True)
            (process / 'cmdline').write_bytes(b'python\0test.py\0')
            self.assertTrue(check.no_open_database_users(db, proc, self_pid=4321))
            (process / 'fd' / '8').symlink_to(db)
            self.assertFalse(check.no_open_database_users(db, proc, self_pid=4321))
            (process / 'fd' / '8').unlink()
            (process / 'cmdline').write_bytes(b'Passenger AppPreloader: /home/u/escape_app\0')
            self.assertFalse(check.no_open_database_users(db, proc, self_pid=4321))

    def test_missing_or_symlink_database_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            proc = root / 'proc'
            proc.mkdir()
            db = root / 'escape.db'
            self.assertFalse(check.no_open_database_users(db, proc))
            real = root / 'real'
            real.touch()
            db.symlink_to(real)
            self.assertFalse(check.no_open_database_users(db, proc))

    def test_incomplete_process_view_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / 'escape.db'
            db.touch()
            proc = root / 'proc'
            (proc / '1234').mkdir(parents=True)
            self.assertFalse(check.no_open_database_users(db, proc, self_pid=4321))


if __name__ == '__main__': unittest.main()
