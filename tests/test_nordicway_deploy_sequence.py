import contextlib
import unittest
from unittest.mock import Mock
import nordicway_deploy_sequence as seq


class Adapter:
    def __init__(self, state='started', fail=None):
        self.events = []
        self.state = state
        self.fail = fail

    @contextlib.contextmanager
    def lock(self):
        self.events.append('lock')
        try:
            yield
        finally:
            self.events.append('unlock')

    def _step(self, name, value=None):
        self.events.append(name)
        if self.fail == name:
            raise RuntimeError(name)
        return value

    def authorize(self, sha): return self._step('authorize')
    def preflight(self, sha): return self._step('preflight')
    def check_quota(self): return self._step('quota')
    def stage(self, sha): return self._step('stage', 'release')
    def service_status(self): return self._step('status', self.state)
    def stop_service(self): return self._step('stop')
    def wait_for_quiescence(self): return self._step('drain')
    def backup_and_apply(self, release): return self._step('backup_and_apply', 'backup')
    def verify_backup(self, backup): return self._step('verify_backup')
    def verify_installed(self, sha): return self._step('verify_install')
    def start_service(self): return self._step('start')
    def verify_health(self, sha): return self._step('health')


class SequenceTests(unittest.TestCase):
    def test_complete_order(self):
        a = Adapter()
        self.assertEqual(seq.deploy(a, 'a' * 40).status, 'ok')
        self.assertEqual(a.events, ['lock', 'authorize', 'preflight', 'quota', 'stage',
                        'status', 'stop', 'drain', 'backup_and_apply', 'verify_backup',
                        'verify_install', 'start', 'health', 'unlock'])

    def test_missing_quota_never_stops_service(self):
        a = Adapter(fail='quota')
        result = seq.deploy(a, 'a' * 40)
        self.assertEqual((result.status, result.stage), ('failed', 'quota'))
        self.assertNotIn('stop', a.events)

    def test_failure_before_apply_restores_previously_running_service(self):
        for step in ('stop', 'drain'):
            with self.subTest(step=step):
                a = Adapter(fail=step)
                result = seq.deploy(a, 'a' * 40)
                self.assertTrue(result.service_restored)
                self.assertNotIn('backup_and_apply', a.events)
                self.assertEqual(a.events.count('start'), 1)
                self.assertLess(a.events.index('start'), a.events.index('unlock'))

    def test_failed_apply_or_installed_check_does_not_restart(self):
        for step in ('backup_and_apply', 'verify_backup', 'verify_install'):
            with self.subTest(step=step):
                a = Adapter(fail=step)
                result = seq.deploy(a, 'a' * 40)
                self.assertEqual(result.status, 'failed')
                self.assertNotIn('start', a.events)

    def test_stopped_service_is_not_started(self):
        a = Adapter(state='stopped')
        self.assertEqual(seq.deploy(a, 'a' * 40).status, 'updated_stopped')
        self.assertNotIn('start', a.events)
        self.assertNotIn('stop', a.events)
        self.assertNotIn('health', a.events)

    def test_unknown_service_never_applies(self):
        a = Adapter(state='unknown')
        self.assertEqual(seq.deploy(a, 'a' * 40).status, 'failed')
        self.assertNotIn('backup_and_apply', a.events)


if __name__ == '__main__':
    unittest.main()

class RealUpdaterIntegration(unittest.TestCase):
    def test_one_real_backup_and_update_in_a_temporary_app(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import apply_update
        import nordicway_autostart
        import nordicway_release_backup

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'escape_app'
            (app / 'var').mkdir(parents=True)
            stage = app / 'opdatering' / 'release'
            stage.mkdir(parents=True)
            (app / 'app.py').write_text('old')
            (stage / 'app.py').write_text('new')
            with sqlite3.connect(app / 'var' / 'escape.db') as db:
                db.execute('CREATE TABLE holdings(value TEXT)')
                db.execute("INSERT INTO holdings VALUES ('preserve')")

            class RealUpdaterAdapter(Adapter):
                def backup_and_apply(self, release):
                    self._step('backup_and_apply')
                    self.expected = nordicway_release_backup.inventory(app, ('app.py',))
                    with nordicway_autostart.preserve(app / 'var'):
                        return apply_update.apply(stage, app)

                def verify_backup(self, backup):
                    self._step('verify_backup')
                    nordicway_release_backup.verify_backup(backup, self.expected)

                def verify_installed(self, sha):
                    self._step('verify_install')
                    if (app / 'app.py').read_text() != 'new':
                        raise ValueError('bad_install')

            adapter = RealUpdaterAdapter()
            with patch.object(apply_update, 'FILES', ('app.py',)):
                result = seq.deploy(adapter, 'a' * 40)
            self.assertEqual(result.status, 'ok')
            self.assertEqual((app / 'app.py').read_text(), 'new')
            self.assertFalse((app / 'var' / 'hotwatch-autostart.enabled').exists())
            with sqlite3.connect(result.backup + '/escape.db') as db:
                self.assertEqual(db.execute('SELECT value FROM holdings').fetchone(), ('preserve',))
            self.assertEqual(len(list((root / '.escape_backups').iterdir())), 1)
