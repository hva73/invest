"""Exact balance differences; never fabricated daily returns or cash sums."""
import copy,json,tempfile,unittest
from pathlib import Path
import app,report_ingest

class Overview(unittest.TestCase):
 def setUp(self):
  self.previous=app.DB;self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/db';app.init();app.create_user('test-password-long-enough')
  self.old=json.loads((Path(__file__).resolve().parents[1]/'examples/report-v2-test.json').read_text());self.old.update(report_id='overview-old',is_test=False,generated_at='2026-01-02T12:00:00Z')
  self.new=copy.deepcopy(self.old);self.new.update(report_id='overview-new',generated_at='2026-01-03T12:00:00Z')
  self.new['portfolios'][0].update(as_of=self.new['generated_at'],value={'amount':'1025.25','currency':'DKK'},cash=[{'amount':'175.50','currency':'DKK'}])
 def tearDown(self):app.DB=self.previous;self.tmp.cleanup()
 def changes(self):return report_ingest.overview_changes({'data':self.new},{'data':self.old})
 def test_values_and_cash_use_exact_decimal_differences(self):
  changes=self.changes()['test-main'];self.assertEqual(changes['value']['amount'],'25.25');self.assertEqual(changes['cash']['DKK']['amount'],'-24.50');self.assertEqual(changes['earmarked']['DKK']['amount'],'0.00');self.assertEqual(changes['value']['from'],self.old['portfolios'][0]['as_of']);self.assertNotIn('daily_change',changes)
  self.old['portfolios'][0]['value']['amount']='999999999999999999.123456789012';self.new['portfolios'][0]['value']['amount']='999999999999999999.123456789013'
  self.assertEqual(self.changes()['test-main']['value']['amount'],'0.000000000001')
 def test_unknown_old_time_currency_and_overlap_are_not_compared(self):
  for field,value in [('as_of',None),('as_of',self.old['portfolios'][0]['as_of']),('includes_collections',False),('portfolio_id','new-id')]:
   saved=copy.deepcopy(self.new);self.new['portfolios'][0][field]=value;self.assertNotIn(self.new['portfolios'][0]['portfolio_id'],self.changes());self.new=saved
  self.new['portfolios'][0]['value']['currency']='EUR';self.assertIsNone(self.changes()['test-main']['value'])
  self.old['portfolios'][0]['value']=None;self.assertIsNone(self.changes()['test-main']['value'])
 def test_null_and_duplicate_money_entries_are_not_added(self):
  self.new['portfolios'][0]['cash']=[None,{'amount':'175','currency':'DKK'},{'amount':'20','currency':'DKK'}]
  self.assertEqual(self.changes()['test-main']['cash'],{})
 def test_desk_comparison_excludes_deep_test_and_late_receipt(self):
  report_ingest.save(app.connect,1,self.old);report_ingest.save(app.connect,1,self.new)
  deep=copy.deepcopy(self.new);deep.update(report_id='overview-deep',report_type='deep_analysis',generated_at='2026-01-04T12:00:00Z',analysis_for={'candidate_id':'test-candidate-alpha','report_id':'overview-new'});deep['portfolios'][0]['value']['amount']='999';report_ingest.save(app.connect,1,deep)
  hidden=copy.deepcopy(self.new);hidden.update(report_id='overview-test',is_test=True,generated_at='2026-01-05T12:00:00Z');report_ingest.save(app.connect,1,hidden)
  late=copy.deepcopy(self.old);late.update(report_id='overview-late',generated_at='2026-01-01T12:00:00Z');report_ingest.save(app.connect,1,late)
  with app.connect() as c:before=list(c.iterdump())
  desk=report_ingest.desk(app.connect,1);self.assertEqual(desk['overview_changes']['test-main']['value']['amount'],'25.25');self.assertEqual(desk['main_report']['data']['report_id'],'overview-new')
  with app.connect() as c:self.assertEqual(before,list(c.iterdump()))
