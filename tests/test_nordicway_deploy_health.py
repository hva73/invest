import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import nordicway_deploy_health as health


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'var').mkdir()
        self.sha = 'a' * 40
        (self.root / 'BUILD_COMMIT').write_text(self.sha + '\n')
        self.now = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
        self.started = self.now - timedelta(seconds=20)
        self.data = {'database': {'status': 'ok', 'worker': {'status': 'running', 'age_seconds': 5},
                                  'supervisor': {'status': 'running', 'age_seconds': 6}}}
        self.inspect = Mock(return_value=self.data)
        self.web = Mock(return_value=True)

    def tearDown(self): self.tmp.cleanup()

    def verify(self):
        return health.verify(self.root, self.sha, self.started, web=self.web,
                             inspect=self.inspect, now=lambda: self.now)

    def test_enabled_requires_heartbeats_newer_than_restart(self):
        (self.root / 'var' / 'hotwatch-autostart.enabled').touch()
        self.assertTrue(self.verify())
        self.data['database']['worker']['age_seconds'] = 21
        self.assertFalse(self.verify())
        self.data['database']['worker']['age_seconds'] = 1
        self.data['database']['supervisor']['status'] = 'stopped'
        self.assertFalse(self.verify())

    def test_disabled_motor_does_not_require_heartbeat(self):
        (self.root / 'var' / 'hotwatch-autostart.disabled').touch()
        self.data['database'] = {'status': 'ok'}
        self.assertTrue(self.verify())

    def test_bad_web_database_or_marker_fails(self):
        self.web.return_value = False
        self.assertFalse(self.verify())
        self.web.return_value = True
        self.data['database']['status'] = 'unavailable'
        self.assertFalse(self.verify())
        self.data['database']['status'] = 'ok'
        (self.root / 'BUILD_COMMIT').write_text('b' * 40)
        self.assertFalse(self.verify())

    def test_unexpected_marker_type_fails(self):
        (self.root / 'var' / 'hotwatch-autostart.disabled').mkdir()
        self.assertFalse(self.verify())

    def test_bounded_retry(self):
        ticks = iter([0, 0, 2, 4, 6])
        verifier = Mock(return_value=False)
        self.assertFalse(health.wait(self.root, self.sha, self.started, timeout=5,
                                     verify_fn=verifier, clock=lambda: next(ticks), sleep=lambda _: None))
        self.assertGreaterEqual(verifier.call_count, 2)


if __name__ == '__main__': unittest.main()
