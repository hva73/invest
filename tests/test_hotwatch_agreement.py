import json,tempfile,unittest
from datetime import datetime,timezone,timedelta

import app,report_ingest,hotwatch_engine as engine,intel_workflows
from test_intel_workflows import merc_report
from test_hotwatch_engine import request

class Agreement(unittest.TestCase):
 def setUp(self):
  self.old=app.DB;self.temp=tempfile.TemporaryDirectory();app.DB=self.temp.name+'/db';app.init();app.create_user('test-password-long-enough')
  self.now=datetime.now(timezone.utc).replace(microsecond=0);self.report=merc_report(True)
  self.assertTrue(report_ingest.save(app.connect,1,self.report)[1]['ok'])
  self.cid=self.report['candidates'][0]['candidate_id']
 def tearDown(self):app.DB=self.old;self.temp.cleanup()
 def assess(self,status='AFVENT',deadline=None,at=None):
  at=at or self.now
  data=dict(self.report['candidates'][0]['decision'],status=status,decided_at=at.isoformat(),deadline=deadline)
  with app.connect() as c:intel_workflows.index_decision(c,1,True,self.cid,data,'test')
 def test_default_and_explicit_deadline_and_renewal(self):
  self.assess()
  with app.connect() as c:
   self.assertEqual(intel_workflows.candidate_currentness(c,1,True,self.cid,self.now+timedelta(hours=23))['status'],'CURRENT')
   self.assertEqual(intel_workflows.candidate_currentness(c,1,True,self.cid,self.now+timedelta(hours=24))['status'],'COLD')
  later=self.now+timedelta(hours=1);self.assess(deadline=(self.now+timedelta(hours=72)).isoformat(),at=later)
  with app.connect() as c:self.assertEqual(intel_workflows.candidate_currentness(c,1,True,self.cid,self.now+timedelta(hours=48))['status'],'CURRENT')
 def test_entry_expiry_and_exit_retention_are_independent_of_data(self):
  self.assess(deadline=(self.now+timedelta(minutes=1)).isoformat())
  entry=request(wid='entry');entry.update(watch_mode='entry',purpose='entry test')
  exit=request(wid='exit');exit.update(watch_mode='exit',purpose='exit test')
  both=request(wid='both');both.update(watch_mode='both',purpose='mixed test')
  for req in (entry,exit,both):engine.create(app.connect,1,req,self.now)
  engine.control(app.connect,1,'entry',True,'pause',self.now)
  self.assertEqual(engine.reconcile_candidates(app.connect,self.now+timedelta(minutes=2)),2)
  self.assertEqual(engine.item(app.connect,1,'entry',True)['session']['status'],'EXPIRED')
  self.assertEqual(engine.item(app.connect,1,'exit',True)['session']['status'],'CREATED')
  with app.connect() as c:
   row=c.execute("SELECT status FROM hw_sessions WHERE watch_id='both'").fetchone();self.assertEqual(row['status'],'EXPIRED')
   self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE json_extract(request,'$.watch_mode')='exit'").fetchone()[0],1)
  self.assertEqual(engine.reconcile_candidates(app.connect,self.now+timedelta(minutes=3)),0)
 def test_combined_watch_splits_when_exit_not_already_covered(self):
  self.assess(deadline=(self.now+timedelta(minutes=1)).isoformat())
  both=request(wid='both');both.update(watch_mode='both',purpose='mixed test');engine.create(app.connect,1,both,self.now)
  engine.reconcile_candidates(app.connect,self.now+timedelta(minutes=2))
  with app.connect() as c:
   child=c.execute("SELECT request,status FROM hw_sessions WHERE purpose='retained exit both'").fetchone()
   self.assertEqual(json.loads(child['request'])['watch_mode'],'exit');self.assertEqual(child['status'],'VALIDATING')
 def test_sync_paginates_events_and_separates_test_data(self):
  self.assess();req=request();req['watch_mode']='entry';engine.create(app.connect,1,req,self.now)
  engine.control(app.connect,1,req['watch_id'],True,'pause',self.now)
  page=engine.sync(app.connect,1,True,0,1);self.assertTrue(page['has_more']);self.assertTrue(page['open_sessions_complete']);self.assertEqual(len(page['open_sessions']),1)
  page2=engine.sync(app.connect,1,True,page['next_cursor'],1);self.assertFalse(page2['has_more']);self.assertNotEqual(page['events'][0]['event_id'],page2['events'][0]['event_id'])
  self.assertEqual(engine.sync(app.connect,1,False)['open_sessions'],[])
 def test_rejection_closes_entry_and_preserves_history(self):
  self.assess();req=request();req['watch_mode']='entry';engine.create(app.connect,1,req,self.now)
  self.assess('FRAVÆLG',at=self.now+timedelta(seconds=1))
  engine.reconcile_candidates(app.connect,self.now+timedelta(seconds=2))
  self.assertEqual(engine.item(app.connect,1,req['watch_id'],True)['session']['status'],'EXPIRED')
  events=engine.sync(app.connect,1,True)['events'];self.assertTrue(any(e['event_type']=='CANDIDATE_WATCH_EXPIRED' for e in events))
  with self.assertRaises(engine.EngineError):engine.create(app.connect,1,dict(req,watch_id='new'),self.now+timedelta(seconds=3))
 def test_manual_stop_requires_new_assessment_and_reason(self):
  self.assess();req=request();req['watch_mode']='entry';engine.create(app.connect,1,req,self.now)
  engine.control(app.connect,1,req['watch_id'],True,'stop',self.now+timedelta(seconds=1))
  new=dict(req,watch_id='new',reactivation_reason='Ny analyse')
  with self.assertRaises(engine.EngineError):engine.create(app.connect,1,new,self.now+timedelta(seconds=2))
  self.assess(at=self.now+timedelta(seconds=3))
  self.assertTrue(engine.create(app.connect,1,new,self.now+timedelta(seconds=4))['ok'])
