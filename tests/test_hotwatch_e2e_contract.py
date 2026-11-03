"""Synthetic Radar -> actual MCP -> persistence -> engine -> signal -> stop/history.
No live provider, broker write, scheduler change or algorithm mock.
"""
import copy,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,hotwatch_engine as engine,report_ingest
import test_mcp_reports
from test_intel_workflows import merc_report
from test_hotwatch_engine import request,tick

class EngineContract(unittest.TestCase):
 def setUp(self):
  self.http=test_mcp_reports.McpReports();self.http.setUp();_,tokens,_=self.http.granted('reports:read reports:write hotwatch:read hotwatch:manage');self.token=tokens['access_token'];self.base=datetime.now(timezone.utc).replace(microsecond=0)-timedelta(minutes=40);self.report=merc_report(True);self.report['generated_at']=self.base.isoformat();self.req=request();self.auth=self.http.login()
  self.assertTrue(self.call('validate_report',self.report)['valid']);self.assertTrue(self.call('send_report',self.report)['ok'])
  with patch('hotwatch_engine.utc',return_value=self.base):self.call('start_hot_watch',self.req)
 def tearDown(self):self.http.tearDown()
 def call(self,name,args):
  result=self.http.call(self.token,name,args)[1]['result'];self.assertFalse(result.get('isError'),result);return result['structuredContent']
 def session(self):return self.call('get_hot_watch_engine',{'watch_id':self.req['watch_id'],'is_test':True})['session']
 def feed(self):
  prices=['100' if i%2==0 else '100.5' for i in range(34)]+['100.55','100.70','100.90','101.15','101.45','101.80']
  for i,price in enumerate(prices):
   at=self.base+timedelta(minutes=i);sample=tick(at,i,price);sample['volume']=str(100 if i<34 else 1000*2**(i-34))
   with patch('hotwatch_engine.utc',return_value=at):status,result,_=self.http.request('/api/v1/hotwatch/sessions/'+self.req['watch_id']+'/samples?is_test=true',sample,self.auth)
   self.assertEqual(status,200,result)
  return at,result
 def test_H01_full_chain_signal_reassessment_stop_and_history(self):
  at,last=self.feed();self.assertEqual(last['calculation']['signal'],'BUY');self.assertEqual(last['calculation']['strategy_version'],'1.0.0');checksum=last['calculation']['strategy_checksum']
  changed=copy.deepcopy(self.report);changed.update(report_id='synthetic-radar-reassessment',generated_at=(at+timedelta(seconds=1)).isoformat());candidate=changed['candidates'][0];candidate['lifecycle']={'status':'WAITING_TRIGGER','changed_at':changed['generated_at'],'reason':'SYNTHETIC revurdering, ikke en motorstyring','source_ids':['synthetic-source'],'trade_cycle_id':'synthetic-review-cycle'}
  before=self.session();self.call('send_report',changed);after=self.session();self.assertEqual(before['status'],after['status']);self.assertEqual(before['next_due_at'],after['next_due_at']);self.assertEqual(after['strategy_checksum'],checksum)
  self.call('control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'stop'});stopped=self.session();self.assertEqual(stopped['status'],'COMPLETED')
  self.assertIsNone(engine.claim(app.connect,at+timedelta(hours=1)))
  samples=self.call('get_hot_watch_engine',{'watch_id':self.req['watch_id'],'is_test':True,'kind':'samples'})['items'];self.assertEqual(len(samples),40)
  journal=self.call('get_hot_watch',{'candidate_id':candidate['candidate_id'],'is_test':True});self.assertTrue(journal['lifecycle_history']['events']);self.assertIsNotNone(journal['candidate'])
  signals=self.call('get_hot_watch_engine',{'watch_id':self.req['watch_id'],'is_test':True,'kind':'signals'})['items'];self.assertTrue(any(x['data']['signal']=='BUY' and x['data']['strategy_checksum']==checksum for x in signals))
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_H02_source_error_is_not_candidate_reject(self):
  engine.fault(app.connect,1,self.req['watch_id'],True,'SYNTHETIC_SOURCE_ERROR',self.base);s=self.session();self.assertEqual(s['status'],'DEGRADED');self.assertEqual(s['signal'],'NO_DATA');r=self.call('get_hot_watch',{'candidate_id':self.req['candidate_id'],'is_test':True});self.assertEqual(r['candidate']['normalized_decision'],'WAIT');self.assertNotEqual(r['candidate']['lifecycle']['status'],'ARCHIVED')
 def test_H03_explicit_pause_resume_stop_control_resource_claims(self):
  self.call('control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'pause'});self.assertIsNone(engine.claim(app.connect,self.base+timedelta(days=1)))
  self.call('control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'resume'});job=engine.claim(app.connect,self.base+timedelta(days=1));self.assertIsNotNone(job)
  self.call('control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'stop'});self.assertIsNone(engine.claim(app.connect,self.base+timedelta(days=2)))
 def test_H04_candidate_display_change_does_not_control_polling(self):
  before=self.session();d=copy.deepcopy(self.report);d.update(report_id='synthetic-archive-only',generated_at=(self.base+timedelta(seconds=1)).isoformat());d['candidates'][0]['lifecycle']={'status':'ARCHIVED','changed_at':d['generated_at'],'reason':'SYNTHETIC display/lifecycle change only','source_ids':['synthetic-source'],'trade_cycle_id':None};self.call('send_report',d);after=self.session();self.assertEqual(before['status'],after['status']);self.assertEqual(before['next_due_at'],after['next_due_at']);self.assertIsNotNone(engine.claim(app.connect,self.base+timedelta(minutes=2)))
 def test_H05_duplicate_quote_cannot_add_mathematical_confirmations(self):
  t=tick(self.base);a=engine.ingest(app.connect,1,self.req['watch_id'],True,t,self.base);self.assertTrue(engine.ingest(app.connect,1,self.req['watch_id'],True,t,self.base)['duplicate'])
  samples=self.call('get_hot_watch_engine',{'watch_id':self.req['watch_id'],'is_test':True,'kind':'samples'})['items'];self.assertEqual(len(samples),1)
 def test_H06_unsupported_trigger_fields_rejected_not_silently_evaluated(self):
  r=copy.deepcopy(self.req);r.update(watch_id='unknown-trigger',purpose='unsupported trigger',triggers={'arbitrary_news_rule':True})
  result=self.http.call(self.token,'start_hot_watch',r)[1]['result'];self.assertTrue(result['isError']);self.assertEqual(self.session()['request']['watch_id'],self.req['watch_id'])
 def test_H07_inflight_ingestion_after_stop_cannot_restart_session(self):
  job=engine.claim(app.connect,self.base);self.assertIsNotNone(job);self.call('control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'stop'})
  with self.assertRaises(engine.EngineError):engine.ingest(app.connect,1,self.req['watch_id'],True,tick(self.base),self.base,lease=job['lease_owner'])
  self.assertEqual(self.session()['status'],'COMPLETED')
 def test_H08_read_filters_are_read_only_and_cannot_start_polling(self):
  before=self.session()
  with app.connect() as c:dump=[line for line in c.iterdump() if 'mcp_limits' not in line]
  for name,args in [('get_hot_watch',{'candidate_id':self.req['candidate_id'],'is_test':True}),('get_hot_watch_engine',{'is_test':True,'kind':'events','watch_id':self.req['watch_id']})]:self.call(name,args)
  with app.connect() as c:self.assertEqual(dump,[line for line in c.iterdump() if 'mcp_limits' not in line])
  after=self.session();self.assertEqual(before['status'],after['status']);self.assertEqual(before['next_due_at'],after['next_due_at'])

if __name__=='__main__':unittest.main()
