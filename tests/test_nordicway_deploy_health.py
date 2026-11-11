import tempfile
import unittest
import json
import sqlite3
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_recovery_wakes_web_and_requires_fresh_enabled_motor(self):
        (self.root / 'var' / 'hotwatch-autostart.enabled').touch()
        web = Mock(return_value=True)
        self.assertTrue(health.verify_recovery(self.root, self.started, web=web,
                                              inspect=self.inspect, now=lambda: self.now))
        web.assert_called_once()
        self.data['database']['worker']['age_seconds'] = 21
        self.assertFalse(health.verify_recovery(self.root, self.started, web=web,
                                               inspect=self.inspect, now=lambda: self.now))
        web.return_value = False
        self.assertFalse(health.verify_recovery(self.root, self.started, web=web,
                                               inspect=self.inspect, now=lambda: self.now))

    def test_recovery_web_supports_old_health_without_build_commit(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.geturl.return_value = health.HEALTH_URL
        response.read.return_value = json.dumps({'status': 'ok', 'database': True}).encode()
        with patch.object(health.urllib.request, 'urlopen', return_value=response):
            self.assertTrue(health.web_recovery_health())
            self.assertFalse(health.web_health(self.sha))

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

    def test_web_health_requires_running_process_version(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.geturl.return_value = health.HEALTH_URL
        with patch.object(health.urllib.request, 'urlopen', return_value=response):
            for version, expected in ((self.sha, True), ('b' * 40, False), (None, False)):
                response.read.return_value = json.dumps({'status': 'ok', 'database': True,
                                                          'build_commit': version}).encode()
                self.assertEqual(health.web_health(self.sha), expected)

    def test_health_endpoint_reports_startup_version_after_marker_changes(self):
        import app
        marker = self.root / 'BUILD_COMMIT'
        with patch.object(app, 'ROOT', self.root):
            startup = app._startup_build_commit()
            marker.write_text('b' * 40)
            self.assertNotEqual(startup, app._startup_build_commit())
        handler = Mock()
        handler.path = '/api/health'
        with patch.object(app, 'STARTUP_BUILD_COMMIT', startup), \
             patch.object(app, 'connect', side_effect=lambda: sqlite3.connect(':memory:')), \
             patch.dict(sys.modules, {'hotwatch_api': SimpleNamespace(handle=lambda *args: False),
                                      'mcp_reports': SimpleNamespace(handle=lambda *args: False)}):
            app.Handler._get(handler)
        self.assertEqual(handler.send.call_args.args[1]['build_commit'], self.sha)


if __name__ == '__main__': unittest.main()
