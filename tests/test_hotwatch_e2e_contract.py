"""Synthetic Radar -> actual MCP -> persistence -> engine -> signal -> stop/history.
No live provider, broker write, scheduler change or algorithm mock.
"""
import copy,unittest,time
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,hotwatch_engine as engine,report_ingest
import os
import test_mcp_reports
from test_intel_workflows import merc_report
from test_hotwatch_engine import request,tick

class EngineContract(unittest.TestCase):
 def setUp(self):
  self.http=test_mcp_reports.McpReports();self.http.setUp();_,tokens,_=self.http.granted('reports:read reports:write hotwatch:read hotwatch:manage');self.token=tokens['access_token'];self.base=datetime.now(timezone.utc).replace(microsecond=0)-timedelta(minutes=40);self.report=merc_report(True);self.report['generated_at']=self.base.isoformat();self.req=request();self.req['trade_cycle_id']='synthetic-radar-cycle';self.report['candidates'][0]['lifecycle']={'status':'HOT_WATCH','changed_at':self.report['generated_at'],'reason':'SYNTHETIC Radar activation','source_ids':['synthetic-source'],'trade_cycle_id':self.req['trade_cycle_id']};self.auth=self.http.login()
  self.assertTrue(self.call('validate_report',self.report)['valid']);self.assertTrue(self.call('send_report',self.report)['ok'])
  with patch('hotwatch_engine.utc',return_value=self.base):self.call('start_hot_watch',self.req)
 def tearDown(self):self.http.tearDown()
 def call(self,name,args):
  status,response,_=self.http.call(self.token,name,args)
  if 'result' not in response:self.fail(f'{name} returned JSON-RPC error: {response}')
  result=response['result'];self.assertFalse(result.get('isError'),result);return result['structuredContent']
 def batch_request(self,request_id='batch-test-1'):
  report=copy.deepcopy(self.report);report['candidates']=report['candidates'][:1]+[copy.deepcopy(report['candidates'][0]) for _ in range(19)];report['report_id']='batch-source-report';report['generated_at']=(self.base+timedelta(seconds=21)).isoformat();sessions=[]
  for index,candidate in enumerate(report['candidates']):
   cid=f'batch-candidate-{index:02d}';ticker='MERC' if index==0 else f'X{index:02d}';candidate['candidate_id']=cid;candidate['ticker']=ticker;candidate['lifecycle']=copy.deepcopy(candidate.get('lifecycle') or {'status':'HOT_WATCH','changed_at':self.base.isoformat(),'reason':'SYNTHETIC explicit test candidate','source_ids':['synthetic-source'],'trade_cycle_id':None});candidate['lifecycle']['changed_at']=(self.base+timedelta(seconds=index+1)).isoformat()
   item=copy.deepcopy(self.req);item.update(watch_id=f'batch-watch-{index:02d}',candidate_id=cid,ticker=ticker,purpose=f'batch-{index:02d}',report_id=report['report_id']);sessions.append(item)
  self.call('send_report',report)
  return {'request_id':request_id,'is_test':True,'sessions':sessions}
 def test_H09_twenty_candidate_batch_is_fast_idempotent_and_explicit(self):
  engine.control(app.connect,1,self.req['watch_id'],True,'stop',self.base)
  with patch.dict(os.environ,{'ESCAPE_HW_CAPACITY':'20'}):
   req=self.batch_request();started=time.perf_counter();created=engine.create_batch(app.connect,1,req)
   measured=(time.perf_counter()-started)*1000;self.assertEqual(len(created['results']),20);self.assertEqual([x['outcome'] for x in created['results']],['created']*20);self.assertEqual(created['created_count'],20);self.assertLess(measured,5000)
   retry=engine.create_batch(app.connect,1,req);self.assertTrue(retry['duplicate']);self.assertEqual(len(retry['results']),20)
   mcp_retry=self.call('activate_hot_watch_batch',req)
   self.assertTrue(mcp_retry['duplicate']);self.assertEqual(len(mcp_retry['results']),20)
  with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE user_id=1 AND watch_id LIKE 'batch-watch-%'").fetchone()[0],20)
  print(f'BATCH_METRICS candidates=20 elapsed_ms={measured:.2f} internal_ms={created["batch_elapsed_ms"]:.3f} retries=1 provider_scans=0')
  changed=copy.deepcopy(self.report);changed['report_id']='ordinary-hot-watch-report';changed['generated_at']=(self.base+timedelta(seconds=5)).isoformat();changed['candidates']=[];self.call('send_report',changed)
  with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE user_id=1 AND watch_id LIKE 'batch-watch-%'").fetchone()[0],20)
  conflict=copy.deepcopy(req);conflict['sessions'][0]['activation_reason']='different payload'
  with self.assertRaises(engine.EngineError):engine.create_batch(app.connect,1,conflict)
 def session(self):return self.call('get_hot_watch_engine',{'watch_id':self.req['watch_id'],'is_test':True})['session']
 def test_radar_session_readback_and_complete_sync(self):
  report=self.call('get_latest_report',{'is_test':True})['report'];self.assertEqual(report['data']['report_id'],self.report['report_id'])
  with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM report_delivery_evidence WHERE report_row_id=? AND kind='readback_verified'",(report['id'],)).fetchone()[0],1)
  with patch('hotwatch_engine.utc',return_value=self.base):engine.ingest(app.connect,1,self.req['watch_id'],True,tick(self.base),self.base)
  synced=self.call('sync_hot_watch',{'is_test':True,'limit':1});self.assertTrue(synced['open_sessions_complete']);self.assertTrue(any(s['watch_id']==self.req['watch_id'] and s['status'] in ('ACTIVE','DEGRADED') for s in synced['open_sessions']))
  seen=[]
  while True:
   seen.extend(synced['events'])
   if not synced['has_more']:break
   synced=self.call('sync_hot_watch',{'is_test':True,'limit':1,'after':synced['next_cursor']})
  self.assertTrue(any(e['event_type']=='WATCH_STARTED' for e in seen))
 def feed(self):
  prices=['100' if i%2==0 else '100.5' for i in range(34)]+['100.55','100.70','100.90','101.15','101.45','101.80']
  for i,price in enumerate(prices):
   at=self.base+timedelta(minutes=i);sample=tick(at,i,price);sample['volume']=str(100 if i<34 else 1000*2**(i-34))
   with patch('hotwatch_engine.utc',return_value=at):status,result,_=self.http.request('/api/v1/hotwatch/sessions/'+self.req['watch_id']+'/samples?is_test=true',sample,self.auth)
   self.assertEqual(status,200,result)
  return at,result
 def test_H01_full_chain_signal_reassessment_stop_and_history(self):
  at,last=self.feed();self.assertEqual(last['calculation']['signal'],'BUY');self.assertEqual(last['calculation']['strategy_version'],'1.0.0');checksum=last['calculation']['strategy_checksum']
  changed=copy.deepcopy(self.report);changed.update(report_id='synthetic-radar-reassessment',generated_at=(at+timedelta(seconds=1)).isoformat());candidate=changed['candidates'][0];candidate['lifecycle']={'status':'WAITING_TRIGGER','changed_at':changed['generated_at'],'reason':'SYNTHETIC revurdering, ikke en motorstyring','source_ids':['synthetic-source'],'trade_cycle_id':self.req['trade_cycle_id']}
  before=self.session();self.call('send_report',changed);after=self.session();self.assertEqual(before['status'],after['status']);self.assertEqual(before['next_due_at'],after['next_due_at']);self.assertEqual(after['strategy_checksum'],checksum)
  self.call('control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'stop'});stopped=self.session();self.assertEqual(stopped['status'],'COMPLETED')
  self.assertIsNone(engine.claim(app.connect,at+timedelta(hours=1)))
  samples=self.call('get_hot_watch_engine',{'watch_id':self.req['watch_id'],'is_test':True,'kind':'samples'})['items'];self.assertEqual(len(samples),40)
  journal=self.call('get_hot_watch',{'candidate_id':candidate['candidate_id'],'is_test':True});self.assertTrue(journal['lifecycle_history']['events']);self.assertIsNotNone(journal['candidate']);self.assertEqual({c['cycle_id'] for c in journal['candidate']['trade_cycles']},{self.req['trade_cycle_id']})
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
  for view in ['current','history']:
   status,body,_=self.http.request('/api/v1/hotwatch/sessions?is_test=true&view='+view,None,self.auth);self.assertEqual(status,200);self.assertEqual(body['view'],view)
  with app.connect() as c:self.assertEqual(dump,[line for line in c.iterdump() if 'mcp_limits' not in line])
  after=self.session();self.assertEqual(before['status'],after['status']);self.assertEqual(before['next_due_at'],after['next_due_at'])

if __name__=='__main__':unittest.main()
