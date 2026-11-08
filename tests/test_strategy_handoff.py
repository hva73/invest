"""Synthetic end-to-end report -> strategy handoff; no broker or network writes."""
import copy,tempfile,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import app,mcp_reports,report_ingest,hotwatch_engine as engine,hotwatch_service,strategy_center
from hotwatch_contract import EngineError
from test_intel_workflows import merc_report
from test_hotwatch_engine import request

class StrategyHandoff(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=app.DB;app.DB=self.temp.name+'/db';app.init();app.create_user('test-password-long-enough')
  with app.connect() as c:c.execute("INSERT INTO users(username,salt,hash,role,active) VALUES('other','00','00','member',1)")
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.report=merc_report(False);self.report.update(report_id='strategy-handoff',generated_at=self.now.isoformat(),positions=[],orders=[])
  self.candidate=self.report['candidates'][0];self.cid=self.candidate['candidate_id'];self.candidate.update(asset_id='synthetic-MERC',exchange='NASDAQ')
  self.candidate['decision'].update(decided_at=self.now.isoformat(),data_as_of=self.now.isoformat(),deadline=(self.now+timedelta(hours=4)).isoformat())
  self.candidate['strategy_proposal']={'strategy_id':'escape_momentum','version':'1.0.0','reason':'Syntetisk momentum','proposed_at':self.now.isoformat(),'source_ids':['synthetic-source']}
 def tearDown(self):app.DB=self.old;self.temp.cleanup()
 def rpc(self,name,args,uid=1,scope='reports:read reports:write'):
  return mcp_reports.rpc(app.connect,{'user_id':uid,'scope':scope},{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})[1]['result']
 def instrument(self,*args,**kwargs):return {'asset_id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ','currency':'USD','type':'CS','isin':None}
 def test_report_receipt_discovery_and_readback(self):
  self.assertTrue(self.rpc('validate_report',self.report)['structuredContent']['valid'])
  catalog=self.rpc('get_strategy_catalog',{})['structuredContent']['strategies'];self.assertTrue(any(x['strategy_id']=='escape_momentum' and x['validation_status']=='baseline_tested' for x in catalog))
  receipt=self.rpc('send_report',self.report)['structuredContent'];self.assertEqual(receipt['strategy_proposals'][0]['qualification'],'QUALIFIED');self.assertEqual(receipt['strategy_proposals'][0]['session_status'],'NOT_CONFIRMED')
  self.assertTrue(self.rpc('send_report',self.report)['structuredContent']['duplicate'])
  pre=self.rpc('get_hot_watch',{'candidate_id':self.cid})['structuredContent']['strategy_handoff'];self.assertEqual(pre['handoff_status'],'AWAITING_DISCOVERY');self.assertIsNone(pre['session'])
  with patch('hotwatch_engine.utc',return_value=self.now),patch('trade_service.client',side_effect=AssertionError('No broker write')):
   started=hotwatch_service.auto_activate_candidate(app.connect,1,False,self.report,self.candidate,verify=self.instrument,lookup=lambda *x:{'choices':[]})
  self.assertEqual(started['status'],'CREATED')
  result=self.rpc('get_hot_watch',{'candidate_id':self.cid})['structuredContent']['strategy_handoff'];self.assertEqual(result['handoff_status'],'SESSION_PRESENT');self.assertEqual(result['session']['strategy_id'],'escape_momentum');self.assertEqual(result['session']['version'],'1.0.0')
  self.assertEqual(strategy_center.handoff(app.connect,2,self.cid)['delivery'],'NOT_FOUND')
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_discovery_worker_records_selected_strategy_and_attempt(self):
  report_ingest.save(app.connect,1,self.report)
  import os
  with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(self.now-timedelta(minutes=1)).isoformat(),'ESCAPE_HW_EODHD_REST_ENABLED':'0'}),patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_service.verified_discovery_instrument',side_effect=self.instrument):
   hotwatch_service.auto_discover(app.connect)
  handoff=strategy_center.handoff(app.connect,1,self.cid)
  self.assertEqual(handoff['handoff_status'],'SESSION_PRESENT');self.assertEqual(handoff['discovery_attempt']['status'],'CREATED');self.assertEqual(handoff['session']['strategy_id'],'escape_momentum')
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_unqualified_and_unknown_are_stored_but_never_auto_started(self):
  for strategy,version in [('escape_early_catalyst','0.1.0'),('does-not-exist','1.0.0')]:
   self.report['report_id']='report-'+strategy;self.candidate['candidate_id']='candidate-'+strategy;self.candidate['strategy_proposal'].update(strategy_id=strategy,version=version)
   validation=self.rpc('validate_report',self.report)['structuredContent'];self.assertTrue(validation['valid']);self.assertTrue(any(x['code'].startswith('strategy_') for x in validation['warnings']))
   receipt=self.rpc('send_report',self.report)['structuredContent'];expected='UNQUALIFIED' if strategy.startswith('escape_') else 'NOT_FOUND';self.assertEqual(receipt['strategy_proposals'][0]['qualification'],expected)
   with patch('hotwatch_service.verified_discovery_instrument',side_effect=AssertionError('Should not verify instrument')):
    self.assertEqual(hotwatch_service.auto_activate_candidate(app.connect,1,False,self.report,self.candidate)['status'],'STRATEGY_'+expected)
   self.assertEqual(strategy_center.handoff(app.connect,1,self.candidate['candidate_id'])['handoff_status'],'STRATEGY_'+expected)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
 def test_causality_and_source_references(self):
  p=self.candidate['strategy_proposal'];p['source_ids']=['not-in-report'];self.assertFalse(report_ingest.validation(app.connect,1,self.report)['valid'])
  p['source_ids']=['synthetic-source'];p['catalyst']={'kind':'regnskab','published_at':self.now.isoformat(),'available_at':(self.now+timedelta(seconds=1)).isoformat(),'source_ids':['synthetic-source']}
  self.assertIn('future_information',{e['code'] for e in report_ingest.validation(app.connect,1,self.report)['errors']})
  p['catalyst']['available_at']=self.now.isoformat();self.assertTrue(report_ingest.validation(app.connect,1,self.report)['valid'])
 def test_superseded_request_and_existing_version_never_silently_changed(self):
  report_ingest.save(app.connect,1,self.report)
  req=request(False,'handoff-watch');req.update(report_id=self.report['report_id'],candidate_id=self.cid,purpose='automatic discovery',watch_mode='entry')
  bad={**req,'strategy_version':'0.1.0'}
  with self.assertRaises(EngineError) as e:engine.create(app.connect,1,bad,self.now)
  self.assertEqual(e.exception.code,'strategy_proposal_mismatch')
  newer=copy.deepcopy(self.report);newer['report_id']='newer-report';newer['generated_at']=(self.now+timedelta(seconds=1)).isoformat();newer['candidates'][0]['strategy_proposal']['strategy_id']='escape_early_catalyst';newer['candidates'][0]['strategy_proposal']['version']='0.1.0';report_ingest.save(app.connect,1,newer)
  with self.assertRaises(EngineError) as e:engine.create(app.connect,1,req,self.now+timedelta(seconds=1))
  self.assertEqual(e.exception.code,'candidate_report_superseded')
 def test_existing_session_reports_strategy_difference(self):
  report_ingest.save(app.connect,1,self.report)
  req=request(False,'existing-watch');req.update(report_id=self.report['report_id'],candidate_id=self.cid,purpose='automatic discovery',watch_mode='entry');engine.create(app.connect,1,req,self.now)
  newer=copy.deepcopy(self.report);newer['report_id']='updated-report';newer['generated_at']=(self.now+timedelta(seconds=1)).isoformat();newer['candidates'][0]['strategy_proposal'].update(strategy_id='escape_early_catalyst',version='0.1.0');report_ingest.save(app.connect,1,newer)
  result=strategy_center.handoff(app.connect,1,self.cid);self.assertEqual(result['handoff_status'],'EXISTING_DIFFERENT_STRATEGY');self.assertEqual(result['session']['strategy_id'],'escape_momentum')
if __name__=='__main__':unittest.main()
