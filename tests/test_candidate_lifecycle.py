"""Permanent lifecycle, recommendation and broker-confirmed execution, separately."""
import copy,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
import app,report_ingest,intel_workflows,candidate_lifecycle as model
from test_intel_workflows import merc_report,decision
from test_hotwatch_engine import tick

class CandidateStatus(unittest.TestCase):
 def setUp(self):
  self.old=app.DB;self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/db';app.init();app.create_user('test-password-long-enough');self.d=merc_report(True);self.cid=self.d['candidates'][0]['candidate_id'];self.at=datetime(2026,11,3,10,tzinfo=timezone.utc)
 def tearDown(self):app.DB=self.old;self.tmp.cleanup()
 def report(self,status,minute,cycle='synthetic-cycle-1',reactivation=None):
  d=copy.deepcopy(self.d);at=(self.at+timedelta(minutes=minute)).isoformat();d.update(report_id='status-report-'+str(minute),generated_at=at);c=d['candidates'][0];c['lifecycle']={'status':status,'changed_at':at,'reason':'Syntetisk begrundelse '+status,'source_ids':['synthetic-source'],'trade_cycle_id':cycle};c['reactivation_reason']=reactivation;return d
 def state(self):
  with app.connect() as c:return intel_workflows.candidates(c,1,True,self.cid)[0]
 def test_full_report_status_journal_readback_without_mutating_history(self):
  for i,status in enumerate(['DISCOVERED','ANALYZING','HOT_WATCH','WAITING_TRIGGER','BUY_SIGNAL','ORDER_PENDING']):
   d=self.report(status,i);report_ingest.save(app.connect,1,d);read=report_ingest.item(app.connect,1,d['report_id'],True)['report']['data'];self.assertEqual(read,d);self.assertEqual(self.state()['lifecycle']['status'],status)
  history=model.history(app.connect,1,self.cid,True)['events'];self.assertTrue(set(['DISCOVERED','ANALYZING','HOT_WATCH','WAITING_TRIGGER','BUY_SIGNAL','ORDER_PENDING'])<={e['status'] for e in history});self.assertEqual(len(self.state()['trade_cycles']),1)
  old=report_ingest.item(app.connect,1,'status-report-0',True)['report']['data'];self.assertEqual(old['candidates'][0]['lifecycle']['status'],'DISCOVERED');self.assertTrue(report_ingest.save(app.connect,1,old)[1]['duplicate'])
 def test_omission_never_removes_candidate_and_retry_never_duplicates(self):
  d=self.report('HOT_WATCH',0);report_ingest.save(app.connect,1,d);before=model.history(app.connect,1,self.cid,True);report_ingest.save(app.connect,1,d);self.assertEqual(before,model.history(app.connect,1,self.cid,True));new=copy.deepcopy(d);new.update(report_id='without-candidate',generated_at='2026-11-03T12:00:00Z');new['candidates']=[];report_ingest.save(app.connect,1,new);self.assertEqual(self.state()['candidate']['candidate_id'],self.cid);self.assertEqual(self.state()['lifecycle']['status'],'HOT_WATCH')
 def test_report_cannot_self_confirm_position_or_execution(self):
  d=self.report('POSITION_OPEN',0);d['orders'][0].update(status='FILLED',lifecycle='filled',filled_quantity='10',execution_source='pluto');receipt=report_ingest.save(app.connect,1,d)[1];self.assertTrue(any(w['code']=='pluto_confirmation_required' for w in receipt['warnings']));state=self.state();self.assertFalse(state['has_confirmed_position']);self.assertEqual(state['execution'],[]);self.assertEqual(state['lifecycle']['reported_status'],'POSITION_OPEN');self.assertNotEqual(state['lifecycle']['status'],'POSITION_OPEN')
 def test_reject_for_new_buys_can_coexist_with_open_position(self):
  d=self.report('HOT_WATCH',0);d['candidates'][0]['decision']=decision('FRAVÆLG',d['generated_at']);report_ingest.save(app.connect,1,d);at=self.at+timedelta(minutes=1);ctx=tick(at,held=True)['context']
  with app.connect() as c:model.observe_pluto(c,1,True,self.cid,ctx,at.isoformat(),'synthetic-provider','synthetic-cycle-1',synthetic=True)
  state=self.state();self.assertEqual(state['normalized_decision'],'REJECT');self.assertTrue(state['has_confirmed_position']);self.assertEqual(state['lifecycle']['status'],'POSITION_OPEN');self.assertFalse(state['active'])
 def test_accepted_partial_full_order_and_zero_position_close_separately(self):
  report_ingest.save(app.connect,1,self.report('ORDER_PENDING',0));at=self.at+timedelta(minutes=1)
  ctx=tick(at,held=True)['context'];ctx['orders']=[{'order_id':'synthetic-sell','status':'ACCEPTED','requested_quantity':'10','filled_quantity':'0','side':'SELL'}]
  with app.connect() as c:model.observe_pluto(c,1,True,self.cid,ctx,at.isoformat(),'synthetic-provider','synthetic-cycle-1','SELL',synthetic=True)
  self.assertEqual(self.state()['execution'][0]['status'],'SUBMITTED');self.assertEqual(self.state()['lifecycle']['status'],'EXIT_WATCH')
  for i,quantity in enumerate(['4','10'],2):
   at=self.at+timedelta(minutes=i);ctx['as_of']=at.isoformat();ctx['orders'][0].update(status='PARTIAL' if quantity=='4' else 'FILLED',filled_quantity=quantity)
   if quantity=='10':ctx.update(position='none',quantity='0')
   with app.connect() as c:model.observe_pluto(c,1,True,self.cid,ctx,at.isoformat(),'synthetic-provider','synthetic-cycle-1','SELL',synthetic=True)
   self.assertEqual(self.state()['execution'][0]['status'],'PARTIALLY_FILLED' if quantity=='4' else 'FILLED')
  self.assertEqual(self.state()['lifecycle']['status'],'CLOSED');self.assertFalse(self.state()['has_confirmed_position'])
 def test_reactivation_preserves_identity_and_creates_distinct_cycle(self):
  report_ingest.save(app.connect,1,self.report('ARCHIVED',0));d=self.report('HOT_WATCH',1,'synthetic-cycle-2')
  with self.assertRaises(ValueError):report_ingest.save(app.connect,1,d)
  d['candidates'][0]['reactivation_reason']='Syntetisk ny væsentlig katalysator';report_ingest.save(app.connect,1,d);self.assertEqual(self.state()['candidate']['candidate_id'],self.cid);self.assertEqual({c['cycle_id'] for c in self.state()['trade_cycles']},{'synthetic-cycle-1','synthetic-cycle-2'});self.assertTrue(any(e['status']=='ARCHIVED' for e in model.history(app.connect,1,self.cid,True)['events']))
 def test_cycle_references_owner_mode_and_unknown_source_rejected(self):
  d=self.report('ORDER_PENDING',0);d['orders'][0]['trade_cycle_id']='synthetic-cycle-1';report_ingest.save(app.connect,1,d);bad=copy.deepcopy(d);bad.update(report_id='bad-cycle',generated_at='2026-11-03T11:00:00Z');bad['orders'][0]['trade_cycle_id']='missing';errors=report_ingest.validation(app.connect,1,bad)['errors'];self.assertIn('orders[0].trade_cycle_id',{e['path'] for e in errors});self.assertEqual(model.history(app.connect,2,self.cid,True)['events'],[]);self.assertEqual(model.history(app.connect,1,self.cid,False)['events'],[])
 def test_status_timestamp_conflicts_and_unknown_enum_have_exact_paths(self):
  report_ingest.save(app.connect,1,self.report('HOT_WATCH',0));bad=self.report('ANALYZING',0);bad['report_id']='conflicting-state';self.assertIn('lifecycle_time_conflict',{e['code'] for e in report_ingest.validation(app.connect,1,bad)['errors']});bad=self.report('WRONG',1);self.assertIn('candidates[0].lifecycle.status',{e['path'] for e in report_ingest.validation(app.connect,1,bad)['errors']})
