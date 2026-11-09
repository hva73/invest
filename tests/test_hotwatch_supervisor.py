import os
import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

import app
import hotwatch_supervisor as supervisor


class WatchdogTests(unittest.TestCase):
    def test_diagnostics_are_bounded_structured_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / 'diagnostics.db')
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE hw_supervisor_events(id INTEGER PRIMARY KEY,created TEXT NOT NULL,event TEXT NOT NULL,code INTEGER)')
            with patch.object(app, 'connect', side_effect=lambda: sqlite3.connect(db)):
                for _ in range(205):
                    supervisor.diagnostic('worker_exited', -15)
                with self.assertRaises(ValueError):
                    supervisor.diagnostic('private-token')
            with sqlite3.connect(db) as c:
                rows = c.execute('SELECT event,code FROM hw_supervisor_events').fetchall()
            self.assertEqual(len(rows), 200)
            self.assertEqual(set(rows), {('worker_exited', -15)})

    def test_lock_prevents_a_second_worker(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app, 'DB', str(Path(d) / 'escape.db')):
            first = supervisor.lock('worker')
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(supervisor.lock('worker'))
            finally:
                os.close(first)
            second = supervisor.lock('worker')
            self.assertIsNotNone(second)
            os.close(second)

    def test_start_requires_marker_and_keeps_secrets_out_of_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            var = Path(d)
            with patch.object(supervisor, 'VAR', var), patch.object(supervisor, 'ENABLED', var/'enabled'), patch.object(supervisor, 'DISABLED', var/'disabled'), patch.object(supervisor.subprocess, 'Popen') as popen, patch.dict(os.environ, {'ESCAPE_EODHD_API_KEY': 'private-token'}, clear=True):
                self.assertFalse(supervisor.start_if_enabled())
                supervisor.marker(supervisor.ENABLED)
                self.assertTrue(supervisor.start_if_enabled())
                self.assertNotIn('private-token', str(popen.call_args.args))
                supervisor.marker(supervisor.DISABLED)
                self.assertFalse(supervisor.start_if_enabled())
                self.assertEqual(popen.call_count, 1)

    def test_settings_respect_operator_overrides(self):
        with patch.dict(os.environ, {'ESCAPE_EODHD_API_KEY': 'private-token', 'ESCAPE_HW_EODHD_WS_TRADES_ENABLED': '0'}, clear=True):
            env = supervisor.environment()
            self.assertEqual(env['ESCAPE_HW_EODHD_WS_TRADES_ENABLED'], '0')
            self.assertEqual(env['ESCAPE_HW_EODHD_REST_ENABLED'], '1')
            self.assertEqual(env['ESCAPE_HW_EODHD_WS_EU_EXCHANGES'], 'CO')

    def test_restart_timeout_is_reported(self):
        clock = iter([1, 4, 9, 18])
        with patch.object(supervisor, 'lock', return_value=os.open(os.devnull, os.O_RDONLY)), patch.object(supervisor, 'enabled', return_value=True), patch.object(supervisor, 'heartbeat', return_value=False), patch.object(supervisor, 'report') as report, patch.object(supervisor.time, 'monotonic', side_effect=lambda: next(clock)), patch.object(supervisor.time, 'sleep'), patch.object(supervisor.subprocess, 'Popen', side_effect=OSError), patch.object(supervisor.signal, 'signal'):
            supervisor.run(timeout=5)
        self.assertEqual(report.call_args.args[:2], ('timeout', 'restart_timeout'))
