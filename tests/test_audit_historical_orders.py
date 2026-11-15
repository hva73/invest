"""Synthetic SQLite fixtures only; never opens a production database."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from tools.audit_historical_orders import inspect, open_database


class HistoricalAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'sample.db'
        self.order = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE candidate_execution_events(id INTEGER PRIMARY KEY, user_id INTEGER, is_test INTEGER, order_id TEXT, status TEXT, occurred_at TEXT, verification TEXT, payload TEXT)')
            db.execute('CREATE TABLE ingested_reports(id INTEGER PRIMARY KEY, user_id INTEGER, is_test INTEGER, report_id TEXT, received TEXT, payload TEXT)')
            db.execute('CREATE TABLE broker_proposals(id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, created REAL, response TEXT)')
            payload = {'status_time': '2026-11-11T20:25:00Z', 'filled_quantity': '2', 'secret': 'do-not-return'}
            db.execute('INSERT INTO candidate_execution_events VALUES(1,1,0,?,?,?,?,?)',
                       (self.order, 'FILLED', '2026-11-11T20:30:00Z', 'pluto', json.dumps(payload)))
            order = {'order_id': self.order, 'created_at': '2026-11-11T20:00:00Z',
                     'as_of': '2026-11-11T20:35:00Z', 'execution_source': 'pluto'}
            db.execute('INSERT INTO ingested_reports VALUES(1,1,0,?,?,?)', ('r1', '2026-11-11T20:36:00Z', json.dumps({'orders': [order]})))

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_and_observation_are_separate_and_sensitive_fields_excluded(self):
        db = open_database(self.path)
        try:
            result = inspect(db, [self.order], 1); row = result['orders'][self.order]
            self.assertEqual(row['execution_observations'][0]['provider_status_time'], '2026-11-11T20:25:00Z')
            self.assertEqual(row['execution_observations'][0]['observed_at'], '2026-11-11T20:30:00Z')
            self.assertEqual(row['report_observations'][0]['reported_created_at'], '2026-11-11T20:00:00Z')
            self.assertEqual(row['report_observations'][0]['reported_as_of'], '2026-11-11T20:35:00Z')
            self.assertNotIn('do-not-return', json.dumps(result))
            self.assertEqual(result['coverage'], 'bounded_not_complete')
            with self.assertRaises(sqlite3.OperationalError): db.execute('DELETE FROM ingested_reports')
        finally:
            db.close()

    def test_test_data_and_unrelated_orders_excluded(self):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO candidate_execution_events VALUES(2,1,1,?,?,?,?,?)',
                       (self.order, 'FILLED', 'fake', 'synthetic', '{}'))
        db = open_database(self.path)
        try:
            result = inspect(db, [self.order], 1)
            self.assertEqual(len(result['orders'][self.order]['execution_observations']), 1)
            with self.assertRaises(ValueError): inspect(db, ['not-an-order-id'], 1)
        finally:
            db.close()

    def test_proposal_reference_requires_exact_explicit_order_id(self):
        response = {'orderIntentId': self.order, 'filledAt': 'not-an-order-fill'}
        matched = {'orders': [{'orderId': self.order, 'source': 'synthetic', 'filledAt': '2026-11-11T20:22:00Z', 'token': 'do-not-return'}]}
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO broker_proposals VALUES(1,1,?,?,?)', ('sent', 1, json.dumps(response)))
            db.execute('INSERT INTO broker_proposals VALUES(2,1,?,?,?)', ('sent', 2, json.dumps(matched)))
        db = open_database(self.path)
        try:
            result = inspect(db, [self.order], 1); refs = result['orders'][self.order]['proposal_references']
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]['provider_order_fields']['filledAt'], '2026-11-11T20:22:00Z')
            self.assertNotIn('do-not-return', json.dumps(result))
        finally:
            db.close()

    def test_other_owner_is_excluded_even_for_same_order_id(self):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO candidate_execution_events VALUES(3,2,0,?,?,?,?,?)',
                       (self.order, 'FILLED', 'other-user', 'pluto', '{}'))
            db.execute('INSERT INTO broker_proposals VALUES(3,2,?,?,?)',
                       ('sent', 3, json.dumps({'orderId': self.order, 'source': 'other-user'})))
        db = open_database(self.path)
        try:
            result = inspect(db, [self.order], 1)
            self.assertNotIn('other-user', json.dumps(result))
        finally:
            db.close()

    def test_refuses_live_journal(self):
        Path(str(self.path) + '-journal').touch()
        with self.assertRaisesRegex(ValueError, 'journal'): open_database(self.path)

    def test_against_real_app_schema(self):
        import app
        previous = app.DB
        try:
            app.DB = str(Path(self.tmp.name) / 'initialized.db')
            app.init()
            app.create_user('synthetic-password-long-enough')
            db = open_database(app.DB)
            try:
                user_id = db.execute('SELECT id FROM users WHERE active=1').fetchone()[0]
                result = inspect(db, [self.order], user_id)
                self.assertEqual(result['orders'][self.order], {
                    'execution_observations': [], 'report_observations': [], 'proposal_references': []})
            finally:
                db.close()
        finally:
            app.DB = previous


if __name__ == '__main__':
    unittest.main()
