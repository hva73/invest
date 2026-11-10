"""Regression of audited failures; all inputs synthetic, no broker/network calls."""
import copy,json,os,tempfile,unittest,logging
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,hotwatch_engine as engine,hotwatch_service as service
from hotwatch_features import features
from hotwatch_strategy import BASELINE,calculate
from hotwatch_contract import EngineError
import test_hotwatch_engine as fixture
from test_hotwatch_engine import tick

class ReviewFixes(unittest.TestCase):
 def setUp(self):
  self.f=fixture.HotWatch();self.f.setUp();self.at=datetime(2026,11,9,18,0,30,tzinfo=timezone.utc)
  self.req=copy.deepcopy(self.f.req);self.req.update(watch_id='audit-bars',purpose='review evidence',provider='eodhd',provider_symbol='MERC.US',watch_mode='exit')
  engine.create(app.connect,1,self.req,self.at)
 def tearDown(self):self.f.tearDown()
 def sample(self,price='94',offset=0):
  now=self.at+timedelta(seconds=offset)
  bars=[{'bar_open_at':(self.at.replace(second=0)-timedelta(minutes=40-i)).isoformat(),'open':'100','high':'100.1','low':'99.9','close':'100','volume':'100'} for i in range(40)]
  evidence={'provider_symbol':'MERC.US','market':'us','exchange':'US','timezone':'America/New_York','session_date':'2026-11-09','open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[],'schedule_received_at':now.isoformat(),'exchange_open':True,'feed':'eodhd_realtime_history'}
  s=tick(now,offset,price=price,held=True);s.update(source='eodhd',price_time_kind='trade',status_at=now.isoformat(),status_feed='us_status',bid_at=now.isoformat(),ask_at=now.isoformat(),quote_feed='us_quotes',bar_history=bars,bar_evidence=evidence)
  return s
 def ingest(self,s,now=None):return engine.ingest(app.connect,1,self.req['watch_id'],True,s,now or self.at,include_session=False)
 def view(self,offset=0):
  with app.connect() as c:return engine.view(c,engine.row_for(c,1,self.req['watch_id'],True),self.at+timedelta(seconds=offset))
 def test_exit_uses_own_inputs_but_keeps_confirmation_and_risk(self):
  risk=copy.deepcopy(self.req['risk']);risk['stop_price']=None
  rows=[tick(self.at-timedelta(minutes=10-i),i,price='99' if i==10 else '100',held=True) for i in range(11)];m=features(rows,BASELINE['parameters']);state={}
  for i,expected in enumerate(['WAIT','WAIT','SELL']):
   sample=tick(self.at+timedelta(seconds=i*10),100+i,price='99',held=True)
   r,state=calculate(sample,m,BASELINE,risk,state,self.at+timedelta(seconds=i*10));self.assertEqual(r['signal'],expected)
  stale=tick(self.at-timedelta(seconds=121),200,price='99',held=True)
  self.assertEqual(calculate(stale,m,BASELINE,risk,state,self.at)[0]['signal'],'NO_DATA')
  unknown=tick(self.at,201,price='99',held=True);unknown['context']['status']='unknown'
  self.assertEqual(calculate(unknown,m,BASELINE,risk,state,self.at)[0]['signal'],'NO_DATA')
 def test_stop_validity_uses_price_context_not_unrelated_bar_age(self):
  self.assertEqual(self.ingest(self.sample())['calculation']['signal'],'SELL')
  v=self.view(91);self.assertEqual(v['signal'],'SELL');self.assertEqual(v['last_action_signal']['state'],'ACTIVE')
  self.assertEqual(self.view(121)['signal'],'NO_DATA')
  self.assertEqual(self.view(121)['last_action_signal']['state'],'DATA_MISSING')
 def test_stale_optional_history_is_saved_without_blocking_fresh_stop(self):
  s=self.sample(offset=91);r=self.ingest(s,self.at+timedelta(seconds=91))['calculation']
  self.assertEqual(r['signal'],'SELL');self.assertEqual(r['supporting_metrics']['bar_history_status'],'INVALID_OR_STALE')
  with app.connect() as c:self.assertEqual(len(json.loads(c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=(SELECT id FROM hw_sessions WHERE watch_id=?)',(self.req['watch_id'],)).fetchone()[0])['bar_history']),40)
 def test_trailing_uses_live_price_and_does_not_latch_after_rebound(self):
  with app.connect() as c:
   req=copy.deepcopy(self.req);req['risk']['stop_price']=None;c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),req['watch_id']))
  for offset,expected in [(0,'WAIT'),(10,'WAIT'),(20,'SELL')]:
   r=self.ingest(self.sample(offset=offset),self.at+timedelta(seconds=offset))['calculation'];self.assertEqual(r['signal'],expected);self.assertEqual(r['supporting_metrics']['distance_high_pct'],'-6.00')
  r=self.ingest(self.sample('100',30),self.at+timedelta(seconds=30))['calculation'];self.assertEqual(r['signal'],'WAIT')
  a=self.view(30)['last_action_signal'];self.assertEqual(a['state'],'WITHDRAWN');self.assertIn('Kursen',a['reason']);self.assertIsNone(a['acknowledged_at'])
 def test_warning_ack_is_idempotent_owned_and_not_a_trade_or_state_change(self):
  self.ingest(self.sample());before=self.view();a=before['last_action_signal'];eid=a['event_id']
  engine.acknowledge_signal(app.connect,1,self.req['watch_id'],True,eid,self.at)
  engine.acknowledge_signal(app.connect,1,self.req['watch_id'],True,eid,self.at)
  after=self.view();self.assertEqual(after['signal'],'SELL');self.assertIsNotNone(after['last_action_signal']['acknowledged_at'])
  with self.assertRaises(EngineError):engine.acknowledge_signal(app.connect,2,self.req['watch_id'],True,eid,self.at)
  with self.assertRaises(EngineError):engine.acknowledge_signal(app.connect,1,self.req['watch_id'],False,eid,self.at)
  self.ingest(self.sample('100',10),self.at+timedelta(seconds=10));self.ingest(self.sample(offset=20),self.at+timedelta(seconds=20))
  self.assertNotEqual(self.view(20)['last_action_signal']['event_id'],eid);self.assertIsNone(self.view(20)['last_action_signal']['acknowledged_at'])
  with app.connect() as c:
   self.assertEqual(c.execute("SELECT count(*) FROM hw_events WHERE event_type='SIGNAL_ACKNOWLEDGED'").fetchone()[0],1)
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_optional_bad_history_does_not_fabricate_buy_indicators(self):
  sample=self.sample('100',91);sample['context']['position']='none';sample['context']['quantity']='0'
  result=self.ingest(sample,self.at+timedelta(seconds=91))['calculation']
  self.assertEqual(result['signal'],'NO_DATA');self.assertEqual(result['supporting_metrics']['sample_count'],1)
 def test_fast_poll_does_not_reset_actual_trade_history(self):
  rows=[tick(self.at+timedelta(seconds=60*i),i) for i in range(34)]+[tick(self.at+timedelta(seconds=1995),34)]
  for s in rows:s.update(source='eodhd',price_time_kind='trade',feed_type='EODHD trades')
  rows[-1]['interval_s']=15
  self.assertEqual(features(rows,BASELINE['parameters'])['sample_count'],35)
  rows[-1]['event_time']=(self.at+timedelta(seconds=2200)).isoformat()
  self.assertEqual(features(rows,BASELINE['parameters'])['sample_count'],35)
  self.assertIsNone(features(rows,BASELINE['parameters'])['return_1_pct'])
  self.assertIsNone(features(rows,BASELINE['parameters'])['acceleration_pct_s2'])
 def test_prepared_features_run_outside_writer_and_recheck_concurrent_history(self):
  original=engine.features;entered=False
  def concurrent(samples,parameters):
   nonlocal entered
   if not entered:
    entered=True
    # Would deadlock/fail if BEGIN IMMEDIATE were held during feature work.
    self.ingest(self.sample('100',1),self.at+timedelta(seconds=1))
   return original(samples,parameters)
  with patch.object(engine,'features',side_effect=concurrent):
   with self.assertRaisesRegex(EngineError,'out_of_order_market_data'):self.ingest(self.sample(),self.at+timedelta(seconds=2))
  self.assertEqual(self.view(2)['last_data_at'],(self.at+timedelta(seconds=1)).isoformat())
 def test_capacity_explicitly_configurable_default_sixty(self):
  with patch.dict(os.environ,{},clear=True):self.assertEqual(engine.capacity(),60)
  for count in (40,60,100,150):
   with patch.dict(os.environ,{'ESCAPE_HW_CAPACITY':str(count)}):self.assertEqual(engine.capacity(),count)
 def test_scan_log_is_private_bounded_and_filtered(self):
  service.configure_scan_log();r=service.Runner(app.connect);job={'user_id':1,'is_test':1,'watch_id':'one','request_data':{'provider':'eodhd'}}
  r.log(job,'processed','SELL',{'provider_ms':3});r.log(dict(job,user_id=2),'processed','WAIT');r.log(dict(job,is_test=0),'processed','WAIT')
  read=service.recent_scan_log(1,True,['one']);self.assertEqual(len(read['records']),1);self.assertEqual(read['records'][0]['code'],'SELL')
  self.assertEqual(service.recent_scan_log(1,True,['other'])['records'],[])
  path=Path(app.DB).parent/'hotwatch-scans.jsonl';self.assertEqual(path.stat().st_mode&0o777,0o600)
  logger=logging.getLogger('escape.hotwatch')
  for h in logger.handlers[:]:
   if getattr(h,'baseFilename',None)==str(path.resolve()):h.close();logger.removeHandler(h)

class AcknowledgeApi(unittest.TestCase):
 def test_ack_requires_cookie_csrf_and_changes_only_journal(self):
  import test_mcp_reports,report_ingest
  from test_intel_workflows import merc_report
  http=test_mcp_reports.McpReports();http.setUp()
  try:
   report_ingest.save(app.connect,1,merc_report(True));req=fixture.request();now=engine.utc();engine.create(app.connect,1,req,now)
   engine.ingest(app.connect,1,req['watch_id'],True,tick(now,price='94',held=True),now)
   action=engine.item(app.connect,1,req['watch_id'],True)['session']['last_action_signal']
   path='/api/v1/hotwatch/sessions/'+req['watch_id']+'/ack-signal';body={'is_test':True,'event_id':action['event_id']};auth=http.login()
   self.assertEqual(http.request(path,body,{'Cookie':auth['Cookie']})[0],403)
   self.assertEqual(http.request(path,body,auth)[0],200)
   self.assertEqual(http.request(path,body,auth)[0],200)
   self.assertEqual(engine.item(app.connect,1,req['watch_id'],True)['session']['signal'],'SELL')
   _,tokens,_=http.granted('hotwatch:read hotwatch:manage')
   self.assertEqual(http.request(path,body,{'Authorization':'Bearer '+tokens['access_token']})[0],403)
   with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
  finally:http.tearDown()
