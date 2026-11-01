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
