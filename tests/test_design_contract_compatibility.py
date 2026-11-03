"""Cross-end schema compatibility and safety of new read projections."""
import copy,json,unittest
from datetime import timedelta
import app,portfolio_data,report_ingest,report_validation,dashboard_projection,journal_projection
import test_design_v1_acceptance as fixtures

class DisplayContract(unittest.TestCase):
 def setUp(self):self.fixture=fixtures.DesignAcceptance();self.fixture.setUp()
 def tearDown(self):self.fixture.tearDown()
 def test_optional_broker_reference_old_and_new_sender_valid(self):
  old=copy.deepcopy(self.fixture.report);old['report_id']='old-sender'
  for p in old['portfolios']:p.pop('broker_reference',None)
  self.assertTrue(report_ingest.validation(app.connect,1,old)['valid'])
  new=copy.deepcopy(self.fixture.report);new['report_id']='new-sender';self.assertTrue(report_ingest.validation(app.connect,1,new)['valid'])
  new['portfolios'][0]['broker_reference']['unknown_field']='not allowed';self.assertFalse(report_ingest.validation(app.connect,1,new)['valid'])
 def test_partial_snapshot_preserves_complete_positions_with_old_time(self):
  with app.connect() as c:
   data=portfolio_data.snapshots(c,1)[str(self.fixture.root['id'])]['data'];data.update(observed=(fixtures.NOW+timedelta(minutes=10)).isoformat(),positions_complete=False,positions=[]);portfolio_data.save(c,1,self.fixture.root['id'],data)
  d=self.fixture.model(fixtures.NOW+timedelta(minutes=10));rows=[r for r in d['positions'] if r['portfolio_id']==self.fixture.root['id']];self.assertEqual(len(rows),7);self.assertTrue(all(r['snapshot_at']==fixtures.NOW.isoformat() and r['verification']=='last_known' for r in rows))
 def test_future_market_time_does_not_create_comparisons(self):
  with app.connect() as c:
   data=portfolio_data.snapshots(c,1)[str(self.fixture.root['id'])]['data'];data['positions'][0]['price_time']=(fixtures.NOW+timedelta(days=1)).isoformat();portfolio_data.save(c,1,self.fixture.root['id'],data)
  r=next(r for r in self.fixture.model()['positions'] if r['ticker']=='TSLA');self.assertIsNone(r['daily']);self.assertIsNone(r['since_last']);self.assertEqual(r['price_freshness']['reason'],'FUTURE_TIMESTAMP')
 def test_owner_isolation_no_report_link_by_ticker(self):
  d=dashboard_projection.build(app.connect,999,[],{},fixtures.NOW);self.assertEqual(d['positions'],[]);self.assertEqual(journal_projection.read(app.connect,999,fixtures.NOW)['events'],[])
  with app.connect() as c:
   data=portfolio_data.snapshots(c,1)[str(self.fixture.root['id'])]['data'];data['positions'][0]['asset_id']='synthetic-other-asset-same-ticker';portfolio_data.save(c,1,self.fixture.root['id'],data)
  r=next(r for r in self.fixture.model()['positions'] if r['ticker']=='TSLA');self.assertIsNone(r['assessment'])
 def test_journal_is_read_only_with_validated_cursor_and_filters(self):
  with app.connect() as c:before=list(c.iterdump())
  journal_projection.read(app.connect,1,fixtures.NOW)
  with app.connect() as c:self.assertEqual(before,list(c.iterdump()))
  for kw in [{'before':'nan|x'},{'before':'invalid'},{'source':'another user'},{'limit':10000},{'days':0}]:
   with self.subTest(kw=kw):
    with self.assertRaises(ValueError):journal_projection.read(app.connect,1,fixtures.NOW,**kw)

 def test_current_session_view_not_buried_by_history_and_history_paginates(self):
  import hotwatch_engine as engine
  from test_hotwatch_engine import request
  r=request(False,'synthetic-current-view');r.update(report_id=self.fixture.report['report_id'],ticker=self.fixture.report['candidates'][0]['ticker'],candidate_id=self.fixture.report['candidates'][0]['candidate_id'],provider='report_inbox')
  engine.create(app.connect,1,r)
  for i in range(4):
   old=copy.deepcopy(r);old.update(watch_id='synthetic-past-'+str(i),purpose='SYNTHETIC past '+str(i));engine.create(app.connect,1,old);engine.control(app.connect,1,old['watch_id'],False,'stop')
  current=dashboard_projection.engine_session_view(app.connect,1,False,'current',2);self.assertEqual([s['watch_id'] for s in current['sessions']],[r['watch_id']])
  first=dashboard_projection.engine_session_view(app.connect,1,False,'history',2);self.assertIsNotNone(first['next_cursor']);second=dashboard_projection.engine_session_view(app.connect,1,False,'history',2,first['next_cursor']);self.assertIsNone(second['next_cursor']);self.assertEqual(len({s['watch_id'] for s in first['sessions']+second['sessions']}),4)

if __name__=='__main__':unittest.main()
