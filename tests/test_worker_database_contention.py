"""Real SQLite rollback-journal contention; disposable data, no provider calls."""
import copy
import json
import http.client
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import app
import hotwatch_engine as engine
import hotwatch_service as service
import report_ingest
from test_hotwatch_engine import request, tick
from test_intel_workflows import merc_report


class WorkerDatabaseContention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / 'test.db')
        self.setting = patch.object(app, 'DB', self.db)
        self.setting.start()
        app.init()
        app.create_user('test-password-long-enough')
        with app.connect() as c:
            c.execute('CREATE TABLE contention_test(value INTEGER)')
            c.executemany('INSERT INTO contention_test VALUES(?)', [(1,), (2,)])

    def tearDown(self):
        self.setting.stop()
        self.temp.cleanup()

    def short_connection(self):
        c = app.connect()
        c.execute('PRAGMA busy_timeout=25')
        return c

    def test_reader_and_writer_conflict_before_coordination(self):
        # A live reader prevents another thread's COMMIT in rollback-journal
        # mode even though BEGIN IMMEDIATE succeeded for the writer.
        with self.short_connection() as reader:
            cursor = reader.execute('SELECT * FROM contention_test')
            cursor.fetchone()
            def write():
                with self.short_connection() as writer:
                    writer.execute('INSERT INTO contention_test VALUES(3)')
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    pool.submit(write).result(timeout=2)
            self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM contention_test').fetchone()[0], 2)

    def test_worker_coordination_waits_before_opening_competing_connection(self):
        opened = threading.Event()
        def traced_connection():
            opened.set()
            return self.short_connection()
        connect = service.serialized_database(traced_connection)
        attempted = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with connect() as reader:
                cursor = reader.execute('SELECT * FROM contention_test')
                cursor.fetchone()
                opened.clear()
                def write():
                    attempted.set()
                    with connect() as writer:
                        writer.execute('INSERT INTO contention_test VALUES(3)')
                future = pool.submit(write)
                self.assertTrue(attempted.wait(2))
                # Hold the reader beyond the SQLite timeout. Coordination must
                # wait before opening the writer, not retry a failed commit.
                self.assertFalse(opened.wait(.1))
                self.assertFalse(future.done())
            future.result(timeout=2)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM contention_test').fetchone()[0], 3)
        metrics=connect.database_metrics()
        self.assertEqual(metrics['completed_scopes'],2)
        self.assertGreaterEqual(metrics['max_wait_ms'],90)
        self.assertGreaterEqual(metrics['max_scope_ms'],90)

    def test_rollback_releases_gate_and_child_runners_share_it(self):
        runner = service.Runner(self.short_connection)
        child = service.Runner(runner.connect)
        self.assertIs(child.connect, runner.connect)
        with self.assertRaises(ValueError):
            with runner.connect() as c:
                c.execute('INSERT INTO contention_test VALUES(3)')
                raise ValueError('abort')
        with ThreadPoolExecutor(max_workers=1) as pool:
            def read():
                with child.connect() as c:
                    return c.execute('SELECT count(*) FROM contention_test').fetchone()[0]
            self.assertEqual(pool.submit(read).result(timeout=2), 2)

    def test_error_location_identifies_caller_instead_of_generic_execute_wrapper(self):
        import hotwatch_supervisor
        with app.connect() as c:c.execute('DROP TABLE hw_heartbeat')
        try:
            service.Runner(app.connect).heartbeat('running')
        except sqlite3.OperationalError as error:
            self.assertTrue(service.processing_error_code(error).startswith('PROCESSING_DATABASE_ERROR_SERVICE_'))
            self.assertTrue(hotwatch_supervisor.application_error(app.connect,'site_state',error))
        else:self.fail('Expected actual SQLite error')
        with app.connect() as c:
            frames=[r[0] for r in c.execute("SELECT event FROM hw_supervisor_events WHERE event LIKE 'site_frame_%'")]
        self.assertEqual(frames,['site_frame_hotwatch_service'])

    def test_five_scans_heartbeat_and_status_reads_run_together(self):
        report_ingest.save(app.connect, 1, merc_report(True))
        now = datetime.now(timezone.utc).replace(microsecond=0)
        runner = service.Runner(app.connect)
        watches = []
        for i in range(5):
            req = request(wid='contention-watch-' + str(i))
            req['purpose'] = 'contention watch ' + str(i)
            req['watch_mode'] = 'exit' if i == 0 else 'entry'
            engine.create(app.connect, 1, req, now)
            watches.append(req['watch_id'])
        start = threading.Barrier(7)
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def http_request(path,body=None,cookie=''):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            try:
                connection.request('POST' if body else 'GET',path,json.dumps(body) if body else None,
                                   {'Content-Type':'application/json','Cookie':cookie})
                response=connection.getresponse()
                return response.status,json.loads(response.read()),response.getheader('Set-Cookie','').split(';')[0]
            finally:connection.close()
        code,_,cookie=http_request('/api/login',{'password':'test-password-long-enough'})
        self.assertEqual(code,200)
        def scan(index):
            start.wait(timeout=5)
            for step in range(12):
                at = now + timedelta(seconds=step)
                sample = tick(at, step, held=index == 0)
                sample['volume'] = None
                sample['volume_type'] = 'unknown'
                result = engine.ingest(runner.connect, 1, watches[index], True,
                                       sample, at, include_session=False)
                self.assertNotEqual(result['calculation']['signal'], 'BUY')
        def beat():
            start.wait(timeout=5)
            for _ in range(40):runner.heartbeat('running')
        def status():
            start.wait(timeout=5)
            for _ in range(20):
                # Independent app connection models the other server process.
                result = engine.sync(app.connect, 1, True, session_limit=10)
                self.assertEqual(len(result['open_sessions']), 5)
                self.assertEqual(http_request('/api/state',cookie=cookie)[0],200)
                self.assertEqual(http_request('/api/reports/hot-watch?is_test=true',cookie=cookie)[0],200)
        try:
            with ThreadPoolExecutor(max_workers=7) as pool:
                tasks = [pool.submit(scan, i) for i in range(5)] + [pool.submit(beat), pool.submit(status)]
                for task in tasks:task.result(timeout=20)
        finally:server.shutdown();server.server_close()
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0], 60)
            self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT status FROM hw_heartbeat WHERE id=1').fetchone()[0], 'running')
        exit_session = engine.item(app.connect, 1, watches[0], True)['session']
        self.assertEqual(exit_session['request']['watch_mode'], 'exit')
        self.assertEqual(exit_session['latest_context']['position'], 'held')
        job={'user_id':1,'is_test':True,'request_data':{'provider':'synthetic'}}
        runner.health(job,tick(now),None)
        diagnostic=engine.sync(app.connect,1,True,session_limit=1,summary_only=True)['open_sessions'][0]['provider_feed_diagnostics']['worker_database_timing']
        self.assertEqual(diagnostic['scope'],'worker_process')
        self.assertEqual(diagnostic['basis'],'high_water_since_worker_start')
        self.assertGreaterEqual(diagnostic['completed_scopes'],100)
        self.assertIn(diagnostic['slowest_module'],('hotwatch_engine','hotwatch_service'))
        self.assertIn(diagnostic['slowest_function'],('ingest','heartbeat'))


if __name__ == '__main__':
    unittest.main()
