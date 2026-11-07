import copy,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch

import app,report_ingest,hotwatch_engine as engine,intel_workflows,hotwatch_service
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
   self.assertEqual(intel_workflows.candidate_currentness(c,1,True,self.cid,self.now+timedelta(hours=24))['status'],'REVIEW_DUE')
   self.assertEqual(intel_workflows.candidate_currentness(c,1,True,self.cid,self.now+timedelta(hours=48))['status'],'COLD')
  later=self.now+timedelta(hours=1);self.assess(deadline=(self.now+timedelta(hours=72)).isoformat(),at=later)
  with app.connect() as c:self.assertEqual(intel_workflows.candidate_currentness(c,1,True,self.cid,self.now+timedelta(hours=48))['status'],'CURRENT')
 def test_report_presence_does_not_fabricate_assessment_or_expire_watch(self):
  report=copy.deepcopy(self.report);report['report_id']='report-only-test';report['generated_at']=self.now.isoformat()
  candidate=report['candidates'][0];candidate['candidate_id']='report-only-candidate';candidate['decision']=None
  self.assertTrue(report_ingest.save(app.connect,1,report)[1]['ok'])
  req=request(wid='report-only-watch');req.update(candidate_id=candidate['candidate_id'],report_id=report['report_id'],purpose='automatic discovery',watch_mode='entry')
  engine.create(app.connect,1,req,self.now)
  from test_hotwatch_engine import tick
  engine.ingest(app.connect,1,req['watch_id'],True,tick(self.now),self.now)
  self.assertFalse(engine.item(app.connect,1,req['watch_id'],True)['session']['latest_calculation']['risk_parameters']['entry_allowed'])
  with app.connect() as c:
   review=intel_workflows.candidate_currentness(c,1,True,candidate['candidate_id'],self.now+timedelta(days=3),report_fallback=True)
  self.assertEqual(review['status'],'REPORT_ONLY');self.assertIsNone(review['assessed_at']);self.assertIsNone(review['deadline'])
  self.assertEqual(engine.reconcile_candidates(app.connect,self.now+timedelta(days=3)),0)
  self.assertIn(engine.item(app.connect,1,req['watch_id'],True)['session']['status'],('ACTIVE','DEGRADED'))
  summary=engine.sync(app.connect,1,True,summary_only=True)['open_sessions'][0]
  self.assertEqual(summary['candidate_review']['status'],'REPORT_ONLY')
 def test_entry_expiry_and_exit_retention_are_independent_of_data(self):
  self.assess(deadline=(self.now+timedelta(minutes=1)).isoformat())
  entry=request(wid='entry');entry.update(watch_mode='entry',purpose='entry test')
  exit=request(wid='exit');exit.update(watch_mode='exit',purpose='exit test')
  both=request(wid='both');both.update(watch_mode='both',purpose='mixed test')
  for req in (entry,exit,both):engine.create(app.connect,1,req,self.now)
  engine.control(app.connect,1,'entry',True,'pause',self.now)
  self.assertEqual(engine.reconcile_candidates(app.connect,self.now+timedelta(minutes=2)),0)
  self.assertEqual(engine.reconcile_candidates(app.connect,self.now+timedelta(hours=24,minutes=2)),2)
  self.assertEqual(engine.item(app.connect,1,'entry',True)['session']['status'],'EXPIRED')
  self.assertEqual(engine.item(app.connect,1,'exit',True)['session']['status'],'CREATED')
  with app.connect() as c:
   row=c.execute("SELECT status FROM hw_sessions WHERE watch_id='both'").fetchone();self.assertEqual(row['status'],'EXPIRED')
   self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE json_extract(request,'$.watch_mode')='exit'").fetchone()[0],1)
  self.assertEqual(engine.reconcile_candidates(app.connect,self.now+timedelta(hours=24,minutes=3)),0)
 def test_combined_watch_splits_when_exit_not_already_covered(self):
  self.assess(deadline=(self.now+timedelta(minutes=1)).isoformat())
  both=request(wid='both');both.update(watch_mode='both',purpose='mixed test');engine.create(app.connect,1,both,self.now)
  engine.reconcile_candidates(app.connect,self.now+timedelta(hours=24,minutes=2))
  with app.connect() as c:
   child=c.execute("SELECT request,status FROM hw_sessions WHERE purpose='retained exit both'").fetchone()
   self.assertEqual(json.loads(child['request'])['watch_mode'],'exit');self.assertEqual(child['status'],'VALIDATING')
 def test_sync_paginates_events_and_separates_test_data(self):
  self.assess();req=request();req['watch_mode']='entry';engine.create(app.connect,1,req,self.now)
  engine.control(app.connect,1,req['watch_id'],True,'pause',self.now)
  page=engine.sync(app.connect,1,True,0,1);self.assertTrue(page['has_more']);self.assertTrue(page['open_sessions_complete']);self.assertEqual(len(page['open_sessions']),1)
  page2=engine.sync(app.connect,1,True,page['next_cursor'],1);self.assertFalse(page2['has_more']);self.assertNotEqual(page['events'][0]['event_id'],page2['events'][0]['event_id'])
  self.assertEqual(engine.sync(app.connect,1,False)['open_sessions'],[])
 def test_radar_candidate_to_verified_cxe_session_readback(self):
  report=merc_report(False);report.update(report_id='synthetic-scho-radar',generated_at=self.now.isoformat(),positions=[],orders=[])
  candidate=report['candidates'][0];candidate.update(candidate_id='synthetic-scho',ticker='SCHO',company_name='Schouw & Co A/S',asset_id='synthetic-scho',exchange='CHIX')
  candidate['decision'].update(decided_at=self.now.isoformat(),data_as_of=self.now.isoformat(),deadline=(self.now+timedelta(hours=24)).isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,report)[1]['ok'])
  instrument={'asset_id':'synthetic-scho','ticker':'SCHO','name':'Schouw & Co A/S','exchange':'CHIX','currency':'DKK','type':'CS','isin':None}
  choices={'choices':[{'symbol':'SCHO.CO','exchange':'CO','currency':'DKK','isin':'DK0010253921'}]}
  reference={'created_at':self.now.isoformat(),'rows':[{'symbol':'SCHOc','primary_ticker':'SCHO','name':'Schouw & Co A/S','isin':'DK0010253921','currency':'DKK','instrument_type':'EQTY','mic':'XCSE'}]}
  with patch.dict('os.environ',{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(self.now-timedelta(minutes=1)).isoformat(),'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.verified_discovery_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',return_value=reference):
   hotwatch_service.auto_discover(app.connect)
   self.assertEqual(hotwatch_service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute("SELECT * FROM hw_sessions WHERE candidate_id='synthetic-scho'").fetchone();self.assertIsNotNone(row);watch=row['watch_id']
  from test_hotwatch_engine import tick
  sample=tick(self.now,1);sample.update(source='eodhd',ticker='SCHO',asset_id='synthetic-scho',currency='DKK',venue='EODHD:CO',market_status='UNKNOWN',feed_type='synthetic EODHD quote',bid=None,ask=None)
  engine.ingest(app.connect,1,watch,False,sample,self.now)
  session=engine.sync(app.connect,1,False,summary_only=True)['open_sessions'][0]
  self.assertEqual((session['candidate_id'],session['ticker'],session['provider']),('synthetic-scho','SCHO','eodhd'))
  self.assertTrue(session['instrument_match_verified']);self.assertTrue(session['quote_feed_verified']);self.assertEqual(session['quote_freshness'],'FRESH')
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_tsla_radar_candidate_to_us_catalog_session_readback(self):
  report=merc_report(False);report.update(report_id='synthetic-tsla-radar',generated_at=self.now.isoformat(),positions=[],orders=[])
  candidate=report['candidates'][0];candidate.update(candidate_id='synthetic-tsla',ticker='TSLA',company_name='Tesla Inc.',asset_id='synthetic-tsla',exchange='NASDAQ')
  candidate['decision'].update(decided_at=self.now.isoformat(),data_as_of=self.now.isoformat(),deadline=(self.now+timedelta(hours=24)).isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,report)[1]['ok'])
  instrument={'asset_id':'synthetic-tsla','ticker':'TSLA','name':'Tesla Inc.','exchange':'NASDAQ','currency':'USD','type':'CS','isin':None}
  choices={'choices':[{'symbol':'TSLA.US','exchange':'US','currency':'USD','isin':'US88160R1014'}]}
  reference={'created_at':self.now.isoformat(),'rows':[{'symbol':'TL0d','name':'Tesla Inc','isin':'US88160R1014','currency':'EUR','instrument_type':'EQTY','mic':'XETR'}]}
  catalog={'received_at':self.now.isoformat(),'rows':[{'Code':'TSLA','Name':'Tesla Inc','Country':'USA','Exchange':'NASDAQ','Currency':'USD','Type':'Common Stock','Isin':'US88160R1014'}]}
  with patch.dict('os.environ',{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(self.now-timedelta(minutes=1)).isoformat(),'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.verified_discovery_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',side_effect=AssertionError('US listing must not depend on Cboe')),patch('eodhd_us_reference.get_reference',return_value=catalog):
   hotwatch_service.auto_discover(app.connect)
   self.assertEqual(hotwatch_service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:watch=c.execute("SELECT watch_id FROM hw_sessions WHERE candidate_id='synthetic-tsla'").fetchone()['watch_id']
  from test_hotwatch_engine import tick
  sample=tick(self.now,1);sample.update(source='eodhd',ticker='TSLA',asset_id='synthetic-tsla',currency='USD',venue='EODHD:US',market_status='UNKNOWN',feed_type='synthetic EODHD quote',bid=None,ask=None)
  engine.ingest(app.connect,1,watch,False,sample,self.now)
  session=engine.sync(app.connect,1,False,summary_only=True)['open_sessions'][0]
  self.assertEqual((session['candidate_id'],session['ticker'],session['provider']),('synthetic-tsla','TSLA','eodhd'))
  self.assertTrue(session['instrument_match_verified']);self.assertEqual(session['instrument_match_evidence']['catalog_exchange'],'NASDAQ');self.assertTrue(session['quote_feed_verified'])
 def test_explicit_reset_preserves_exit_and_requires_new_dated_assessment(self):
  initial=self.now-timedelta(seconds=3);cutoff=self.now-timedelta(seconds=2)
  report=merc_report(False);report.update(report_id='reset-source',generated_at=initial.isoformat(),positions=[],orders=[])
  candidate=report['candidates'][0];candidate.update(candidate_id='reset-candidate',ticker='SCHO',company_name='Schouw & Co A/S',asset_id='reset-asset',exchange='CHIX')
  candidate['decision'].update(decided_at=initial.isoformat(),data_as_of=initial.isoformat(),deadline=(self.now+timedelta(hours=24)).isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,report)[1]['ok'])
  instrument={'asset_id':'reset-asset','ticker':'SCHO','name':'Schouw & Co A/S','exchange':'CHIX','currency':'DKK','type':'CS','isin':None}
  with patch('hotwatch_engine.utc',return_value=initial):created=hotwatch_service.auto_activate_candidate(app.connect,1,False,report,candidate,verify=lambda *_:instrument)
  self.assertEqual(created['status'],'CREATED');old=created['watch_id']
  exit_req=engine.item(app.connect,1,old,False)['session']['request'];exit_req.update(watch_id='preserved-exit',purpose='manual exit protection',watch_mode='exit')
  engine.create(app.connect,1,exit_req,initial)
  test_req=request(True,'preserved-test');test_req.update(purpose='automatic discovery',watch_mode='entry');engine.create(app.connect,1,test_req,initial)
  result=engine.reset_automatic_candidates(app.connect,1,cutoff)
  self.assertEqual([x['watch_id'] for x in result['closed']],[old]);self.assertEqual(engine.item(app.connect,1,old,False)['session']['status'],'COMPLETED');self.assertEqual(engine.item(app.connect,1,'preserved-exit',False)['session']['status'],'CREATED')
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertEqual(hotwatch_service.auto_activate_candidate(app.connect,1,False,report,candidate,verify=lambda *_:self.fail('old report cannot restart'))['status'],'NOT_NEW')
  updated=copy.deepcopy(report);updated.update(report_id='reset-new-assessment',generated_at=self.now.isoformat());updated['candidates'][0]['decision'].update(decided_at=self.now.isoformat(),data_as_of=self.now.isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,updated)[1]['ok'])
  with patch('hotwatch_engine.utc',return_value=self.now):restarted=hotwatch_service.auto_activate_candidate(app.connect,1,False,updated,updated['candidates'][0],verify=lambda *_:instrument)
  self.assertEqual(restarted['status'],'CREATED');self.assertNotEqual(restarted['watch_id'],old)
  self.assertEqual(engine.item(app.connect,1,'preserved-exit',False)['session']['status'],'CREATED')
  self.assertEqual(engine.item(app.connect,1,'preserved-test',True)['session']['status'],'CREATED')
  engine.control(app.connect,1,restarted['watch_id'],False,'pause',self.now)
  second=engine.reset_automatic_candidates(app.connect,1,self.now+timedelta(seconds=1))
  self.assertEqual(second['paused_preserved'],1);self.assertTrue(second['duplicate']);self.assertEqual(second['reset_at'],cutoff.isoformat());self.assertEqual(engine.item(app.connect,1,restarted['watch_id'],False)['session']['status'],'PAUSED')
  engine.control(app.connect,1,restarted['watch_id'],False,'stop',self.now+timedelta(seconds=2))
  self.assertEqual(hotwatch_service.auto_activate_candidate(app.connect,1,False,updated,updated['candidates'][0],verify=lambda *_:self.fail('manual stop must be respected'))['status'],'NOT_NEW')
  with app.connect() as c:self.assertTrue(c.execute("SELECT 1 FROM hw_events WHERE event_type='WATCH_RESET'").fetchone())
 def test_inflight_discovery_cannot_recreate_old_candidate_after_reset(self):
  initial=self.now-timedelta(seconds=3);cutoff=self.now-timedelta(seconds=2)
  report=merc_report(False);report.update(report_id='reset-race-source',generated_at=initial.isoformat(),positions=[],orders=[])
  candidate=report['candidates'][0];candidate.update(candidate_id='reset-race',ticker='SCHO',company_name='Schouw & Co A/S',asset_id='reset-race-asset',exchange='CHIX')
  candidate['decision'].update(decided_at=initial.isoformat(),data_as_of=initial.isoformat(),deadline=(self.now+timedelta(hours=24)).isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,report)[1]['ok'])
  instrument={'asset_id':'reset-race-asset','ticker':'SCHO','name':'Schouw & Co A/S','exchange':'CHIX','currency':'DKK','type':'CS','isin':None}
  def verify(*_):engine.reset_automatic_candidates(app.connect,1,cutoff);return instrument
  with patch('hotwatch_engine.utc',return_value=self.now):result=hotwatch_service.auto_activate_candidate(app.connect,1,False,report,candidate,verify=verify)
  self.assertEqual(result['status'],'candidate_not_current')
  with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE candidate_id='reset-race'").fetchone()[0],0)
 def test_explicit_reset_command_exits_without_starting_a_worker(self):
  import os,subprocess,sys
  env=dict(os.environ,ESCAPE_DB=app.DB)
  result=subprocess.run([sys.executable,'hotwatch_service.py','--reset-candidates-for-user','1'],env=env,capture_output=True,text=True,timeout=15)
  self.assertEqual(result.returncode,0,result.stderr)
  data=json.loads(result.stdout);self.assertEqual(data['closed'],[]);self.assertTrue(data['new_assessment_required'])
  with app.connect() as c:self.assertIsNone(c.execute('SELECT * FROM hw_heartbeat').fetchone())
 def test_status_sync_paginates_sessions_without_sensitive_engine_payload(self):
  self.assess();first=request(wid='sync-one');first['watch_mode']='entry';second=request(wid='sync-two');second.update(watch_mode='exit',purpose='separate exit')
  engine.create(app.connect,1,first,self.now);engine.create(app.connect,1,second,self.now);engine.control(app.connect,1,'sync-two',True,'pause',self.now)
  with app.connect() as c:before=list(c.iterdump())
  one=engine.sync(app.connect,1,True,0,1,0,1,True);self.assertFalse(one['open_sessions_complete']);self.assertTrue(one['sessions_have_more']);self.assertEqual(one['open_sessions'][0]['watch_kind'],'candidate');self.assertNotIn('request',one['open_sessions'][0]);self.assertNotIn('data',one['events'][0])
  two=engine.sync(app.connect,1,True,one['next_cursor'],1,one['next_sessions_cursor'],1,True);self.assertFalse(two['sessions_have_more']);self.assertFalse(two['open_sessions_complete']);self.assertEqual(two['open_sessions'][0]['watch_kind'],'holding');self.assertEqual(two['open_sessions'][0]['status'],'PAUSED')
  self.assertEqual(engine.sync(app.connect,2,True,summary_only=True)['open_sessions'],[]);self.assertEqual(engine.sync(app.connect,1,False,summary_only=True)['open_sessions'],[])
  with app.connect() as c:self.assertEqual(before,list(c.iterdump()))
 def test_candidate_lifecycle_is_not_proof_of_running_engine(self):
  self.assess();req=request();req['watch_mode']='entry';engine.create(app.connect,1,req,self.now)
  engine.control(app.connect,1,req['watch_id'],True,'stop',self.now)
  report=intel_workflows.watch(app.connect,1,True);self.assertFalse(report['engine_sessions_checked']);self.assertIn('bekræfter ikke',report['candidate_status_note'])
  result=engine.sync(app.connect,1,True);self.assertTrue(result['open_sessions_complete']);self.assertEqual(result['open_sessions'],[]);self.assertFalse(result['worker_heartbeat_fresh'])
  with app.connect() as c:c.execute('INSERT INTO hw_heartbeat VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status',(engine.utc().isoformat(),'running'))
  self.assertTrue(engine.sync(app.connect,1,True)['worker_heartbeat_fresh'])
  import mcp_reports
  description=next(t['description'] for t in mcp_reports.tools('reports:read') if t['name']=='get_hot_watch');self.assertIn('bekræfter ikke',description);self.assertIn('sync_hot_watch',description)
 def test_rejection_closes_entry_and_preserves_history(self):
  self.assess();req=request();req['watch_mode']='entry';engine.create(app.connect,1,req,self.now)
  self.assess('FRAVÆLG',at=self.now+timedelta(seconds=1))
  engine.reconcile_candidates(app.connect,self.now+timedelta(seconds=2))
  self.assertEqual(engine.item(app.connect,1,req['watch_id'],True)['session']['status'],'EXPIRED')
  events=engine.sync(app.connect,1,True)['events'];self.assertTrue(any(e['event_type']=='CANDIDATE_WATCH_EXPIRED' for e in events))
  with self.assertRaises(engine.EngineError):engine.create(app.connect,1,dict(req,watch_id='new'),self.now+timedelta(seconds=3))
 def test_report_rejection_closes_session_in_same_transaction(self):
  req=request();req['watch_mode']='entry';engine.create(app.connect,1,req,self.now)
  rejected=copy.deepcopy(self.report);rejected['report_id']='new-rejection';rejected['generated_at']=self.now.isoformat()
  rejected['candidates'][0]['decision'].update(status='FRAVÆLG',decided_at=self.now.isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,rejected)[1]['ok'])
  self.assertEqual(engine.item(app.connect,1,req['watch_id'],True)['session']['status'],'EXPIRED')
 def test_manual_stop_requires_new_assessment_and_reason(self):
  self.assess();req=request();req['watch_mode']='entry';engine.create(app.connect,1,req,self.now)
  engine.control(app.connect,1,req['watch_id'],True,'stop',self.now+timedelta(seconds=1))
  new=dict(req,watch_id='new',reactivation_reason='Ny analyse')
  with self.assertRaises(engine.EngineError):engine.create(app.connect,1,new,self.now+timedelta(seconds=2))
  self.assess(at=self.now+timedelta(seconds=3))
  self.assertTrue(engine.create(app.connect,1,new,self.now+timedelta(seconds=4))['ok'])
 def test_live_activation_requires_matching_pluto_instrument(self):
  req=request(False)
  with patch.object(hotwatch_service,'verified_discovery_instrument',return_value=None):
   with self.assertRaises(engine.EngineError):hotwatch_service.verify_requested_instruments(app.connect,1,[req])
  instrument={'asset_id':req['asset_id'],'ticker':req['ticker'],'exchange':req['exchange'],'currency':req['quote_currency']}
  with patch.object(hotwatch_service,'verified_discovery_instrument',return_value=instrument):hotwatch_service.verify_requested_instruments(app.connect,1,[req])
