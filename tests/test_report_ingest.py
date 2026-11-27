import copy,json,unittest
from pathlib import Path
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
