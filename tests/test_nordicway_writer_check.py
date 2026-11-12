import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import nordicway_writer_check as check


class WriterTests(unittest.TestCase):
    def test_only_identified_orphan_is_signalled_after_service_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'escape_app'
            app.mkdir()
            proc = root / 'proc'
            exe = root / 'lswsgi'
            exe.touch()
            def make(pid, parent, command, cwd=app):
                process = proc / str(pid)
                process.mkdir(parents=True)
                (process / 'cmdline').write_bytes(command)
                (process / 'cwd').symlink_to(cwd)
                (process / 'exe').symlink_to(exe)
                (process / 'stat').write_text(f'{pid} (lswsgi) S {parent} ' + '0 ' * 17 + '12345 0')
            cmd = os.fsencode(str(app / 'passenger_wsgi.py'))
            make(1234, 1, cmd)
            make(1235, 99, cmd)
            make(1236, 1, b'/other/passenger_wsgi.py')
            service = Mock()
            service.status.return_value = 'stopped'
            with patch.object(os, 'pidfd_open', return_value=51) as opened, \
                 patch.object(os, 'close') as closed, \
                 patch.object(signal, 'pidfd_send_signal') as sent:
                self.assertEqual(check.stop_orphaned_lswsgi(app, service, proc), 1)
            opened.assert_called_once_with(1234, 0)
            sent.assert_called_once_with(51, signal.SIGTERM)
            closed.assert_called_once_with(51)

    def test_running_service_never_signals_orphan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'escape_app'
            app.mkdir()
            process = root / 'proc/1234'
            process.mkdir(parents=True)
            exe = root / 'lswsgi'
            exe.touch()
            (process / 'cmdline').write_bytes(os.fsencode(str(app / 'passenger_wsgi.py')))
            (process / 'cwd').symlink_to(app)
            (process / 'exe').symlink_to(exe)
            (process / 'stat').write_text('1234 (lswsgi) S 1 ' + '0 ' * 17 + '12345 0')
            service = Mock()
            service.status.return_value = 'started'
            with patch.object(os, 'pidfd_open', return_value=51), \
                 patch.object(os, 'close'), \
                 patch.object(signal, 'pidfd_send_signal') as sent:
                with self.assertRaisesRegex(ValueError, 'service_not_stopped'):
                    check.stop_orphaned_lswsgi(app, service, root / 'proc')
            sent.assert_not_called()
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

    def test_wait_for_passenger_exit_rechecks_all_gates_and_times_out(self):
        with patch.object(check, 'failure_reason', side_effect=['passenger_active', None]) as gate:
            self.assertIsNone(check.wait_for_quiescence('/database', clock=lambda: 0, sleep=lambda _: None))
            self.assertEqual(gate.call_count, 2)
        with patch.object(check, 'failure_reason', side_effect=['passenger_active', 'database_in_use']):
            self.assertEqual(check.wait_for_quiescence('/database', clock=lambda: 0, sleep=lambda _: None),
                             'database_in_use')
        with patch.object(check, 'failure_reason', return_value='passenger_active'):
            ticks = iter([0, 1])
            self.assertEqual(check.wait_for_quiescence('/database', timeout=1, clock=lambda: next(ticks),
                                                      sleep=lambda _: None), 'passenger_active')


if __name__ == '__main__': unittest.main()

