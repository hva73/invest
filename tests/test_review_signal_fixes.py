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
 def test_bar_blocker_explains_expiry_without_refreshing_trade_or_enabling_buy(self):
  s=self.sample('100');s['context']['position']='none';s['context']['quantity']='0'
  first=self.ingest(s)['calculation'];self.assertNotEqual(first['signal'],'BUY')
  before=self.view(0);self.assertNotIn('bar_blocking_detail',before['data_status'])
  after=self.view(91);self.assertEqual(after['signal'],'NO_DATA')
  self.assertIn('BAR_EVIDENCE_STALE',after['display_reason_codes'])
  detail=after['data_status']['bar_blocking_detail']
  self.assertEqual(detail['blocking_inputs'],['bar']);self.assertEqual(detail['bar_age_s'],121)
  self.assertEqual(detail['schedule_age_s'],91);self.assertTrue(detail['analysis_uses_bars'])
  self.assertEqual(after['last_data_at'],s['event_time'])
  with patch('hotwatch_engine.utc',return_value=self.at+timedelta(seconds=91)):
   summary=next(x for x in engine.sync(app.connect,1,True,summary_only=True)['open_sessions'] if x['watch_id']==self.req['watch_id'])
  self.assertEqual(summary['bar_blocking_detail']['blocking_inputs'],['bar']);self.assertEqual(summary['signal'],'NO_DATA')
 def test_bar_blocker_identifies_expired_calendar_separately(self):
  s=self.sample('100');s['context']['position']='none';s['context']['quantity']='0'
  s['bar_evidence']['schedule_received_at']=(self.at-timedelta(seconds=60)).isoformat()
  self.ingest(s);view=self.view(61)
  self.assertEqual(view['signal'],'NO_DATA')
  self.assertEqual(view['data_status']['bar_blocking_detail']['blocking_inputs'],['schedule'])
 def test_stale_optional_history_is_saved_without_blocking_fresh_stop(self):
  s=self.sample(offset=91);r=self.ingest(s,self.at+timedelta(seconds=91))['calculation']
  self.assertEqual(r['signal'],'SELL');self.assertEqual(r['supporting_metrics']['bar_history_status'],'INVALID_OR_STALE')
  with app.connect() as c:self.assertEqual(len(json.loads(c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=(SELECT id FROM hw_sessions WHERE watch_id=?)',(self.req['watch_id'],)).fetchone()[0])['bar_history']),40)
 def test_legacy_trailing_is_not_current_and_recalculates_independent_exit(self):
  with app.connect() as c:
   req=copy.deepcopy(self.req);req['risk']['stop_price']=None;c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),req['watch_id']))
  self.ingest(self.sample('94',0))
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True);state=json.loads(row['state']);state['signal']='SELL';c.execute('UPDATE hw_sessions SET state=? WHERE id=?',(json.dumps(state),row['id']))
   calc=c.execute('SELECT id,payload FROM hw_calculations WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone();payload=json.loads(calc['payload']);payload.update(signal='SELL',reason_codes=['TRAILING_EXIT'],signal_basis='live_price_window');c.execute('UPDATE hw_calculations SET payload=? WHERE id=?',(json.dumps(payload),calc['id']))
   engine.event(c,row,'SELL_SIGNAL',self.at,'Historical trailing signal',data_time=self.at.isoformat())
  view=self.view(0);self.assertEqual(view['signal'],'NO_DATA');self.assertIn('POSITION_TRAILING_EVIDENCE_REQUIRED',view['display_reason_codes']);self.assertNotEqual(view['last_action_signal']['state'],'ACTIVE')
  import web_push
  with app.connect() as c:self.assertIsNone(web_push._actionable(c,engine.row_for(c,1,self.req['watch_id'],True),self.at))
  r=self.ingest(self.sample('94',10),self.at+timedelta(seconds=10))['calculation']
  self.assertNotIn('TRAILING_EXIT',r['reason_codes']);self.assertNotEqual(r['signal'],'SELL')
 def test_trailing_uses_live_price_and_does_not_latch_after_rebound(self):
  with app.connect() as c:
   req=copy.deepcopy(self.req);req['risk']['stop_price']=None;req['portfolio_ids']=[1];c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),req['watch_id']))
  for offset,price,expected in [(0,'100','WAIT'),(10,'100','WAIT'),(20,'94','WAIT'),(30,'94','WAIT'),(40,'94','SELL')]:
   sample=self.sample(price,offset);sample['context'].update(orders_complete=True,position_history_complete=True)
   r=self.ingest(sample,self.at+timedelta(seconds=offset))['calculation'];self.assertEqual(r['signal'],expected)
  self.assertEqual(self.view(40)['signal'],'SELL')
  sample=self.sample('100',50);sample['context'].update(orders_complete=True,position_history_complete=True)
  r=self.ingest(sample,self.at+timedelta(seconds=50))['calculation'];self.assertEqual(r['signal'],'WAIT')
  a=self.view(50)['last_action_signal'];self.assertEqual(a['state'],'WITHDRAWN');self.assertIn('Kursen',a['reason']);self.assertIsNone(a['acknowledged_at'])
  import web_push
  with app.connect() as c:self.assertIsNone(web_push._actionable(c,engine.row_for(c,1,self.req['watch_id'],True),self.at+timedelta(seconds=50)))
 def test_real_event_generation_ignores_small_ticks_but_emits_trailing_worsening(self):
  with app.connect() as c:
   req=copy.deepcopy(self.req);req['risk']['stop_price']=None;req['portfolio_ids']=[1];c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),req['watch_id']))
  def put(price,offset):
   sample=self.sample(price,offset);sample['context'].update(orders_complete=True,position_history_complete=True)
   return self.ingest(sample,self.at+timedelta(seconds=offset))
  for offset,price in ((0,'100'),(10,'100'),(20,'94'),(30,'94'),(40,'94')):put(price,offset)
  for offset,price in ((50,'93.999'),(60,'93.998'),(70,'93.997')):put(price,offset)
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True)
   self.assertEqual(c.execute("SELECT count(*) FROM hw_events WHERE watch_row_id=? AND event_type='TRAILING_EXIT_WORSENED'",(row['id'],)).fetchone()[0],0)
  put('92.12',80)
  with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM hw_events WHERE watch_row_id=? AND event_type='TRAILING_EXIT_WORSENED'",(row['id'],)).fetchone()[0],1)
 def test_context_only_partial_sale_invalidates_active_trailing_for_readback_and_push(self):
  with app.connect() as c:
   req=copy.deepcopy(self.req);req['risk']['stop_price']=None;req['portfolio_ids']=[1];c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),req['watch_id']))
  for offset,price in ((0,'100'),(10,'100'),(20,'94'),(30,'94'),(40,'94')):
   sample=self.sample(price,offset);sample['context'].update(orders_complete=True,position_history_complete=True)
   result=self.ingest(sample,self.at+timedelta(seconds=offset))['calculation']
  self.assertEqual(result['signal'],'SELL');self.assertEqual(self.view(40)['last_action_signal']['state'],'ACTIVE')
  now=self.at+timedelta(seconds=50);context=copy.deepcopy(sample['context']);context.update(as_of=now.isoformat(),quantity='9')
  engine.observe_context(app.connect,1,self.req['watch_id'],True,context,now,broker_source='pluto')
  view=self.view(50);self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(view['last_action_signal']['state'],'DATA_MISSING')
  import web_push
  with app.connect() as c:self.assertIsNone(web_push._actionable(c,engine.row_for(c,1,self.req['watch_id'],True),now))
 def test_aggregated_depot_scope_never_inherits_a_trailing_high(self):
  import portfolios
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:synthetic-one','name':'Synthetic one','kind':'portfolio'},{'id':'portfolios:synthetic-two','name':'Synthetic two','kind':'portfolio'}])
   ids=[p['id'] for p in portfolios.list_owned(c,1)]
  for portfolio_ids in ([],ids):
   with self.subTest(portfolio_ids=portfolio_ids):
    req=copy.deepcopy(self.req);req['risk']['stop_price']=None;req['portfolio_ids']=portfolio_ids
    # Fresh independent session for each scope; no actual depot access occurs.
    req['watch_id']='scope-'+str(len(portfolio_ids));req['purpose']='synthetic scope '+str(len(portfolio_ids));engine.create(app.connect,1,req,self.at)
    for offset,price in ((0,'100'),(10,'100'),(20,'94'),(30,'94'),(40,'94')):
     sample=self.sample(price,offset);sample['context'].update(orders_complete=True,position_history_complete=True)
     now=self.at+timedelta(seconds=offset);result=engine.ingest(app.connect,1,req['watch_id'],True,sample,now,include_session=False)['calculation']
    self.assertNotIn('TRAILING_EXIT',result['reason_codes'])
    self.assertEqual(result['position_trailing']['status'],'WAITING_FOR_VERIFIED_POSITION_HISTORY')
 def test_stop_can_recur_after_unknown_context_without_verified_recovery(self):
  self.ingest(self.sample('94',0),self.at)
  missing=self.sample('93.999',10);missing['context']['status']='unknown';missing['context']['position']='unknown';missing['context']['quantity']=None
  self.ingest(missing,self.at+timedelta(seconds=10))
  self.ingest(self.sample('93.998',20),self.at+timedelta(seconds=20))
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True)
   events=c.execute("SELECT payload FROM hw_events WHERE watch_row_id=? AND event_type='RISK_REJECTION' AND severity='critical' ORDER BY id",(row['id'],)).fetchall()
  self.assertEqual([json.loads(e['payload'])['reason'] for e in events],['STOP_BREACHED','STOP_BREACHED'])
 def test_breached_stop_escalates_only_after_configured_worsening(self):
  for offset,price in ((0,'94'),(10,'93.999'),(20,'93.998'),(30,'92.12')):
   sample=self.sample(price,offset)
   if offset==10:sample['context']['quantity']=sample['context']['quantity']+'.0'
   result=self.ingest(sample,self.at+timedelta(seconds=offset))['calculation']
   self.assertEqual(result['signal'],'SELL')
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True)
   events=c.execute("SELECT payload FROM hw_events WHERE watch_row_id=? AND event_type='RISK_REJECTION' AND severity='critical' ORDER BY id",(row['id'],)).fetchall()
  self.assertEqual([json.loads(e['payload'])['reason'] for e in events],['STOP_BREACHED','STOP_BREACHED'])
 def test_breached_stop_emits_on_changed_verified_position(self):
  self.ingest(self.sample('94',0),self.at)
  changed=self.sample('93.999',10);changed['context']['quantity']=str(int(changed['context']['quantity'])+1)
  self.ingest(changed,self.at+timedelta(seconds=10))
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True)
   events=c.execute("SELECT payload FROM hw_events WHERE watch_row_id=? AND event_type='RISK_REJECTION' AND severity='critical'",(row['id'],)).fetchall()
  self.assertEqual(len(events),2)
 def test_unusable_trailing_distance_does_not_hide_new_critical_risk(self):
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True);strategy=json.loads(row['strategy']);strategy['parameters']['trailing_pct']='200'
   c.execute('UPDATE hw_sessions SET strategy=? WHERE id=?',(json.dumps(strategy),row['id']))
  self.ingest(self.sample('94',0),self.at);self.ingest(self.sample('93.999',10),self.at+timedelta(seconds=10))
  with app.connect() as c:
   events=c.execute("SELECT payload FROM hw_events WHERE watch_row_id=? AND event_type='RISK_REJECTION' AND severity='critical'",(row['id'],)).fetchall()
  self.assertEqual(len(events),2)
 def test_breached_stop_emits_on_changed_limit_and_after_recovery(self):
  self.ingest(self.sample('94',0),self.at)
  with app.connect() as c:
   req=copy.deepcopy(self.req);req['risk']['stop_price']='96';c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),req['watch_id']))
  self.ingest(self.sample('94',10),self.at+timedelta(seconds=10))
  recovered=self.ingest(self.sample('100',20),self.at+timedelta(seconds=20))['calculation'];self.assertEqual(recovered['signal'],'WAIT')
  self.ingest(self.sample('94',30),self.at+timedelta(seconds=30))
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True)
   events=c.execute("SELECT payload FROM hw_events WHERE watch_row_id=? AND event_type='RISK_REJECTION' AND severity='critical'",(row['id'],)).fetchall()
  self.assertEqual(len(events),3)
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
