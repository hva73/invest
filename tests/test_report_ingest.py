import copy,json,unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch
import portfolio_data,portfolios
import report_ingest
class Schema(unittest.TestCase):
 def setUp(self):self.data=json.loads((Path(__file__).resolve().parents[1]/'examples/report-ingest-test.json').read_text())
 def test_valid_example(self):self.assertEqual(report_ingest.validate(self.data),self.data)
 def test_bad_inputs(self):
  changes=[{'schema_version':True},{'is_test':'yes'},{'generated_at':'2026-01-01T00:00:00'},{'user_id':2},{'report_id':'bad/id'},{'orders':[{'reference':'a','status':'b','note':'c','execute':True}]}]
  for change in changes:
   with self.subTest(change=change),self.assertRaises(ValueError):report_ingest.validate(dict(self.data,**change))
 def test_money_is_finite_decimal_string(self):
  for amount in [100,float('nan'),'NaN','Infinity','1,25','1e100']:
   data=copy.deepcopy(self.data);data['portfolio_values'][0]['amount']=amount
   with self.assertRaises(ValueError):report_ingest.validate(data)


class OverviewChanges(unittest.TestCase):
    def test_incomparable_timestamp_only_withholds_affected_portfolio(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/report-v2-test.json'
        previous = {'data': json.loads(fixture.read_text())}
        current = copy.deepcopy(previous)
        current['data']['report_id'] = 'next-report'
        old_main, old_child = previous['data']['portfolios']
        new_main, new_child = current['data']['portfolios']
        start = '2026-01-02T12:00:00+02:00'
        end = '2026-01-02T11:01:00+01:00'
        old_main['as_of'], new_main['as_of'] = start, end
        old_child['as_of'], new_child['as_of'] = start, end
        old_child['value']['amount'] = '9007199254740992.01'
        new_child['value']['amount'] = '9007199254740992.02'
        old_child['cash'] = [{'currency': 'EUR', 'amount': '2.30'}]
        new_child['cash'] = [{'currency': 'EUR', 'amount': '2.10'}]
        provenance = {'from': start, 'to': end, 'report_id': previous['data']['report_id']}
        expected = {new_child['portfolio_id']: {
            'value': {**provenance, 'currency': 'DKK', 'amount': '0.01',
                      'previous_amount': '9007199254740992.01'},
            'cash': {'EUR': {**provenance, 'currency': 'EUR', 'amount': '-0.20',
                             'previous_amount': '2.30'}},
            'earmarked': {},
        }}
        for invalid in ('0001-01-01T00:00:00+00:01', '9999-12-31T23:59:59-00:01',
                        '2026-01-02T11:00:00', None):
            for side, portfolio, original in [('previous', old_main, start), ('current', new_main, end)]:
                with self.subTest(invalid=invalid, side=side):
                    portfolio['as_of'] = invalid
                    self.assertEqual(report_ingest.overview_changes(current, previous), expected)
                portfolio['as_of'] = original


class DeskProjection(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect('')  # Private temporary SQLite database.
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        with self.db as c:
            c.execute('PRAGMA foreign_keys=ON')
            c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
            c.execute('INSERT INTO users VALUES(1),(2)')
            c.execute('CREATE TABLE proposals(user_id INTEGER, portfolio TEXT)')
            portfolios.init(c)
            portfolio_data.init(c)
            report_ingest.init(c)
        examples = Path(__file__).resolve().parents[1] / 'examples'
        self.legacy = dict(json.loads((examples / 'report-ingest-test.json').read_text()),
                           is_test=False, generated_at='2026-01-01T12:00:00Z')
        self.modern = dict(json.loads((examples / 'report-v2-test.json').read_text()), is_test=False)

    def connect(self):
        return self.db

    def save(self, data, user=1):
        status, receipt = report_ingest.save(self.connect, user, data)
        self.assertEqual(status, 201, receipt)
        return receipt['id']

    def test_v1_list_and_reset_cutoff(self):
        cutoff = self.save(self.legacy)
        view = report_ingest.desk(self.connect, 1)
        candidate, = self.legacy['candidates']
        entry = dict(candidate=candidate, report_id=self.legacy['report_id'],
                     generated_at=self.legacy['generated_at'], received=view['main_report']['received'],
                     schema_version=1, quality='unknown', index=0)
        self.assertEqual(view['candidates'], [entry])
        with self.connect() as c:
            c.execute('INSERT INTO radar_resets VALUES(?,?,?)', (1, cutoff, self.legacy['generated_at']))
        self.assertEqual(report_ingest.desk(self.connect, 1)['candidates'], [])
        fresh = dict(candidate, symbol='NEW')
        updated = dict(self.legacy, report_id='updated-legacy', generated_at='2026-01-03T12:00:00Z',
                       candidates=[dict(candidate, symbol=candidate['symbol'].lower()), fresh])
        self.save(updated)
        view = report_ingest.desk(self.connect, 1)
        self.assertEqual(view['candidates'], [dict(entry, candidate=fresh, index=1,
                                                   report_id=updated['report_id'], generated_at=updated['generated_at'],
                                                   received=view['main_report']['received'])])

    def test_v2_registry_projection_avoids_discarded_report_reads(self):
        self.save(self.legacy)
        template, = self.modern['candidates']
        self.save(self.modern)  # Still active even though omitted from the next main report.
        main = dict(self.modern, report_id='main', generated_at='2026-01-03T12:00:00Z',
                    candidates=[dict(template, candidate_id=f'candidate-{i:02}', ticker=f'T{i}')
                                for i in reversed(range(60))])
        self.save(main)
        for index in (0, 1):
            candidate = dict(main['candidates'][index], assessment=f'Deep assessment {index}')
            at = f'2026-01-04T12:0{index}:00Z'
            if index == 1:
                candidate['lifecycle'] = dict(status='ARCHIVED', changed_at=at, reason='Archived in deep report',
                                              source_ids=candidate['source_ids'], trade_cycle_id=None)
            self.save(dict(main, report_type='deep_analysis', report_id=f'deep-{index}', generated_at=at,
                           analysis_for=dict(candidate_id=candidate['candidate_id'], report_id='main'),
                           candidates=[candidate]))

        view = report_ingest.desk(self.connect, 1)
        active = view['candidates']
        self.assertEqual([e['candidate']['candidate_id'] for e in active],
                         [c['candidate_id'] for c in main['candidates'] if c != main['candidates'][1]]
                         + [template['candidate_id']])
        self.assertEqual((active[0]['report_id'], active[0]['candidate']['assessment']),
                         ('deep-0', 'Deep assessment 0'))
        dormant, = view['dormant_candidates']
        self.assertEqual((dormant['report_id'], dormant['candidate']['candidate_id']),
                         ('deep-1', main['candidates'][1]['candidate_id']))
        self.assertEqual(view['main_report']['data'], main)
        self.assertEqual(view['report']['data']['report_id'], 'deep-1')
        self.assertEqual(view['delivery']['status'], 'stored')
        self.assertEqual([e['report_id'] for e in view['journal_events']], ['deep-1'])

        # Newer rows sharing a candidate ID must not affect any field of the owner's desk.
        for name, user, mode in [('other-owner', 2, False), ('test-inbox', 1, True)]:
            self.save(dict(self.modern, report_id=name, generated_at='2026-01-05T12:00:00Z', is_test=mode,
                           candidates=[template, dict(main['candidates'][0], assessment=name)]), user)
        statements = []

        self.db.set_trace_callback(statements.append)
        with patch.object(report_ingest, 'row_view', wraps=report_ingest.row_view) as decode:
            self.assertEqual(report_ingest.desk(self.connect, 1), view)
        # Main, previous, five journal rows, and the most recent report.
        self.assertEqual(decode.call_count, 8)
        self.assertFalse(any('SELECT r.id,r.received,r.payload FROM report_candidate_links' in sql
                             for sql in statements))
