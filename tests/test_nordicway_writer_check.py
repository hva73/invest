import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_cron_check_uses_local_environment_without_ssh_metadata(self):
        def run(args, **kwargs):
            self.assertEqual(args, ['crontab', '-l'])
            self.assertNotIn('SSH_ORIGINAL_COMMAND', kwargs['env'])
            self.assertNotIn('SSH_CONNECTION', kwargs['env'])
            self.assertEqual(kwargs['env']['ESCAPE_TEST_PRESERVED'], 'yes')
            return subprocess.CompletedProcess(args, 1, '', 'no crontab for user')
        with patch.dict(os.environ, {'SSH_ORIGINAL_COMMAND': 'escape-deploy-v1 deploy ' + 'a' * 40,
                                     'SSH_CONNECTION': '127.0.0.1 12345 127.0.0.1 33',
                                     'ESCAPE_TEST_PRESERVED': 'yes'}):
            self.assertTrue(check.no_cron(run))
            self.assertIn('SSH_ORIGINAL_COMMAND', os.environ)
            self.assertIn('SSH_CONNECTION', os.environ)

    def test_real_crontab_subprocess_preserves_cron_veto_under_ssh(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / 'crontab'
            fake.write_text('#!/bin/sh\n'
                'if [ -n "$SSH_ORIGINAL_COMMAND" ] || [ -n "$SSH_CONNECTION" ]; then exit 2; fi\n'
                'echo "no crontab for user" >&2\nexit 1\n')
            fake.chmod(0o700)
            with patch.dict(os.environ, {'PATH': temp, 'SSH_ORIGINAL_COMMAND': 'remote command',
                                         'SSH_CONNECTION': 'remote connection'}):
                self.assertTrue(check.no_cron())
                fake.write_text('#!/bin/sh\nprintf "* * * * * task\\n"\n')
                self.assertFalse(check.no_cron())

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
            self.assertEqual(check.database_user_failure(db, proc, self_pid=4321), 'database_in_use')
            (process / 'fd' / '8').unlink()
            (process / 'cmdline').write_bytes(b'Passenger AppPreloader: /home/u/escape_app\0')
            self.assertFalse(check.no_open_database_users(db, proc, self_pid=4321))
            self.assertEqual(check.database_user_failure(db, proc, self_pid=4321), 'passenger_active')

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

    def test_failure_reason_identifies_only_the_gate(self):
        with patch.object(check, 'no_cron', return_value=False), \
             patch.object(check, 'database_user_failure') as processes:
            self.assertEqual(check.failure_reason('/database'), 'cron_unverified')
            processes.assert_not_called()
        with patch.object(check, 'no_cron', return_value=True), \
             patch.object(check, 'database_user_failure', return_value='database_in_use'):
            self.assertEqual(check.failure_reason('/database'), 'database_in_use')
        with patch.object(check, 'no_cron', return_value=True), \
             patch.object(check, 'database_user_failure', return_value=None):
            self.assertIsNone(check.failure_reason('/database'))


if __name__ == '__main__': unittest.main()
