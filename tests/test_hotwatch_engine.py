"""HOT WATCH phase 1–2: disposable databases and explicitly synthetic MERC."""
import copy,json,os,tempfile,unittest
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from unittest.mock import patch
import app,report_ingest,hotwatch_engine as engine
from hotwatch_contract import EngineError,checksum,stamp
from hotwatch_features import features,observation_status
from hotwatch_strategy import BASELINE,validate_strategy,calculate
from hotwatch_adapters import PlutoAdapter,EODHDAdapter,DataUnavailable,unknown_context,reserve
from test_intel_workflows import merc_report

def request(mode=True,wid='synthetic-merc-watch'):
 r=merc_report(mode)
 return {'watch_id':wid,'report_id':r['report_id'],'candidate_id':r['candidates'][0]['candidate_id'],'is_test':mode,'purpose':'MERC synthetic momentum','ticker':'MERC','exchange':'NASDAQ','asset_id':'synthetic-MERC','quote_currency':'USD','portfolio_ids':[],'priority':'NORMAL','profile':'NORMAL','provider':'synthetic' if mode else 'pluto','end_at':None,'activation_reason':'SYNTHETISK MERC-test, ingen faktisk handel','strategy_id':'escape_momentum','strategy_version':'1.0.0','risk':{'max_notional_dkk':'1000','max_loss_dkk':'100','max_spread_pct':'1','max_quote_age_s':120,'max_position_fraction_pct':'20','proposed_quantity':'1','stop_price':'95','exit_deadline':None}}

def tick(at,index=0,price='100',held=False):
 p=Decimal(price)
 return {'sample_id':'synthetic-tick-'+str(index),'source':'synthetic','ticker':'MERC','asset_id':'synthetic-MERC','venue':'SYNTHETIC NASDAQ','currency':'USD','event_time':at.isoformat(),'session_key':'SYNTHETIC-REGULAR-1','market_status':'REGULAR','feed_type':'synthetic interval bars','documented_delay_s':0,'verification':'verified','error_code':None,'interval_s':60,'price':price,'bid':format(p-Decimal('.05'),'f'),'ask':format(p+Decimal('.05'),'f'),'volume':'100','volume_type':'interval','open':price,'high':format(p+Decimal('.1'),'f'),'low':format(p-Decimal('.1'),'f'),'close':price,'context':{'tradability':'available','status':'verified','as_of':at.isoformat(),'position':'held' if held else 'none','quantity':'10' if held else '0','cost_price':'98' if held else None,'portfolio_equity_dkk':'10000','exposure_dkk':'0','fx_to_dkk':'7','fees_dkk':'1','orders':[]}}

def good_metrics():return {'sample_count':40,'price':'100','return_1_pct':'.1','return_3_pct':'.5','acceleration_pct_s2':'.01','relative_volume':'3','spread_pct':'.1','volatility_pct':'.3','breakout':True,'breakdown':False,'trend_up':True,'rsi':'60','macd_histogram':'.1','distance_high_pct':'0'}

class HotWatch(unittest.TestCase):
 def setUp(self):
  self.old=app.DB;self.temp=tempfile.TemporaryDirectory();app.DB=self.temp.name+'/db';app.init();app.create_user('test-password-long-enough');self.now=datetime.now(timezone.utc).replace(microsecond=0);self.r=merc_report(True);report_ingest.save(app.connect,1,self.r);self.req=request();engine.create(app.connect,1,self.req,self.now)
 def tearDown(self):app.DB=self.old;self.temp.cleanup()
 def put(self,data,now=None):return engine.ingest(app.connect,1,self.req['watch_id'],True,data,now or self.now)
 def counts(self):
  with app.connect() as c:return {name:c.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ['hw_sessions','hw_samples','hw_calculations','hw_events']}
 def test_observation_status_separates_stale_price_from_signal_without_guessing_delay(self):
  sample=tick(self.now-timedelta(minutes=15));sample.update(source='eodhd',market_status='UNKNOWN',bid=None,ask=None,documented_delay_s=None)
  quality=observation_status([sample],self.now,120,'NO_DATA','DEGRADED')
  self.assertEqual(quality['price'],'100');self.assertEqual(quality['price_status'],'STALE');self.assertEqual(quality['market_status'],'UNKNOWN')
  self.assertEqual(quality['quote_status'],'UNAVAILABLE');self.assertEqual(quality['momentum_status'],'UNAVAILABLE');self.assertEqual(quality['signal_status'],'WAITING_FOR_DATA')
  sample['documented_delay_s']=900
  self.assertEqual(observation_status([sample],self.now,120,'NO_DATA','ACTIVE')['price_status'],'DELAYED')
  self.assertEqual(observation_status([],self.now,120,'NO_DATA','CREATED')['price_status'],'MISSING')
 def test_market_phase_is_not_current_when_evidence_is_old(self):
  sample=tick(self.now);sample.update(source='eodhd',status_at=(self.now-timedelta(seconds=121)).isoformat())
  view=observation_status([sample],self.now,120,'NO_DATA','ACTIVE')
  self.assertEqual(view['market_status'],'UNKNOWN');self.assertEqual(view['last_market_status'],'OPEN')
  sample['status_at']=self.now.isoformat();sample['market_status']='PRE'
  self.assertEqual(observation_status([sample],self.now,120,'NO_DATA','ACTIVE')['market_status'],'PREMARKET')
 def test_timed_momentum_uses_only_actual_comparable_samples(self):
  samples=[tick(self.now-timedelta(minutes=n),index=i,price=str(100+i)) for i,n in enumerate((30,15,5,1,0))]
  view=observation_status(samples,self.now,120,'WAIT','ACTIVE')
  self.assertEqual(view['momentum_status'],'READY');self.assertEqual(view['market_status'],'OPEN');self.assertEqual(view['signal_status'],'READY')
  self.assertTrue(all(v is not None for v in view['momentum_pct'].values()))
  samples[-2]['venue']='DIFFERENT';samples[-3]['session_key']='DIFFERENT'
  view=observation_status(samples,self.now,120,'WAIT','ACTIVE')
  self.assertIsNone(view['momentum_pct']['1']);self.assertIsNone(view['momentum_pct']['5']);self.assertIsNotNone(view['momentum_pct']['15'])
  samples[-1]['market_status']='UNKNOWN'
  self.assertEqual(observation_status(samples,self.now,120,'NO_DATA','ACTIVE')['momentum_status'],'UNAVAILABLE')
 def test_daily_and_since_last_use_only_recorded_comparable_prices(self):
  first=tick(self.now-timedelta(minutes=1),0,'100');last=tick(self.now,1,'110');last['previous_close']='100'
  result=observation_status([first,last],self.now,120,'WAIT','ACTIVE')
  self.assertEqual(Decimal(result['daily_change_pct']),Decimal('10'));self.assertEqual(Decimal(result['since_last_pct']),Decimal('10'))
  first['venue']='OTHER';result=observation_status([first,last],self.now,120,'WAIT','ACTIVE');self.assertIsNone(result['since_last_pct'])
 def test_since_last_uses_observed_trade_not_last_two_bar_closes(self):
  first=tick(self.now-timedelta(minutes=1),0,'100');last=tick(self.now,1,'110')
  last['bar_history']=[{'bar_open_at':(self.now-timedelta(minutes=2)).isoformat(),'close':'100'},{'bar_open_at':(self.now-timedelta(minutes=1)).isoformat(),'close':'100'}]
  view=observation_status([first,last],self.now,120,'WAIT','ACTIVE')
  self.assertEqual(Decimal(view['since_last_pct']),Decimal('10'));self.assertEqual(Decimal(view['momentum_pct']['1']),Decimal('0'))
  self.assertIsNone(observation_status([last],self.now,120,'WAIT','ACTIVE')['since_last_pct'])
 def test_eodhd_daily_reference_is_same_symbol_currency_and_exchange_day(self):
  at=datetime(2026,11,5,13,40,tzinfo=timezone.utc);current=tick(at,1,'110');current.update(source='eodhd',bar_evidence={'timezone':'Europe/Copenhagen'})
  prior=tick(at-timedelta(minutes=15),0,'101');prior.update(source='eodhd',feed_type='EODHD REST real-time endpoint; synthetic',previous_close='100')
  req={'provider':'eodhd'}
  self.assertEqual(Decimal(engine.reported_daily_from_history([prior,current],req,'110')),Decimal('10'))
  for change in ({'currency':'USD' if current['currency']!='USD' else 'DKK'},{'asset_id':'different'},{'event_time':(at-timedelta(days=1)).isoformat()},{'previous_close':'0'}):
   modified={**prior,**change};self.assertIsNone(engine.reported_daily_from_history([modified,current],req,'110'))
 def test_different_feed_and_price_time_kinds_are_not_mixed(self):
  first=tick(self.now-timedelta(minutes=1),0,'100');last=tick(self.now,1,'101');last['feed_type']='different quote source'
  self.assertEqual(features([first,last],BASELINE['parameters'])['sample_count'],1)
  last['feed_type']=first['feed_type'];last['price_time_kind']='bar_open'
  self.assertEqual(features([first,last],BASELINE['parameters'])['sample_count'],1)
 def test_session_view_keeps_price_when_signal_waits_for_data(self):
  result=self.put(tick(self.now))
  self.assertEqual(result['session']['signal'],'NO_DATA')
  self.assertEqual(result['session']['data_status']['price'],'100')
  self.assertEqual(result['session']['data_status']['price_status'],'FRESH')
  self.assertEqual(result['session']['data_status']['signal_status'],'WAITING_FOR_DATA')
 def test_dashboard_shows_only_unambiguous_owned_asset_watch(self):
  import dashboard_projection
  with app.connect() as c:c.execute('UPDATE hw_sessions SET is_test=0')
  with app.connect() as c:
   matched=dashboard_projection.position_hotwatch(c,1,123,self.req['asset_id'],None)
   self.assertEqual(matched['session']['watch_id'],self.req['watch_id'])
   self.assertIsNone(matched['candidate_id'])
   self.assertIsNone(dashboard_projection.position_hotwatch(c,2,123,self.req['asset_id'],None)['session'])
   self.assertIsNone(dashboard_projection.position_hotwatch(c,1,123,'other-asset',None)['session'])
  second=copy.deepcopy(self.req);second.update(watch_id='another-watch',purpose='another purpose')
  engine.create(app.connect,1,second,self.now)
  with app.connect() as c:c.execute('UPDATE hw_sessions SET is_test=0')
  with app.connect() as c:self.assertIsNone(dashboard_projection.position_hotwatch(c,1,123,self.req['asset_id'],None)['session'])
 def test_session_idempotence_conflict_duplicate_and_restart(self):
  self.assertTrue(engine.create(app.connect,1,self.req,self.now)['duplicate']);changed=copy.deepcopy(self.req);changed['activation_reason']='changed'
  with self.assertRaisesRegex(EngineError,'watch_id_conflict'):engine.create(app.connect,1,changed,self.now)
  other=copy.deepcopy(self.req);other['watch_id']='other';other['purpose']='  MERC SYNTHETIC MOMENTUM  '
  with self.assertRaisesRegex(EngineError,'active_watch_exists'):engine.create(app.connect,1,other,self.now)
  self.put(tick(self.now));app.init();self.assertEqual(engine.item(app.connect,1,self.req['watch_id'],True)['session']['last_data_at'],self.now.isoformat())
 def test_pause_resume_stop_are_persistent_and_idempotent(self):
  for action,status in [('pause','PAUSED'),('resume','VALIDATING'),('stop','COMPLETED')]:
   result=engine.control(app.connect,1,self.req['watch_id'],True,action,self.now);self.assertEqual(result['session']['status'],status);self.assertTrue(engine.control(app.connect,1,self.req['watch_id'],True,action,self.now)['duplicate'])
  with self.assertRaisesRegex(EngineError,'watch_is_terminal'):engine.control(app.connect,1,self.req['watch_id'],True,'resume',self.now)
 def test_owner_test_partition_and_global_capacity(self):
  for uid,mode in [(2,True),(1,False)]:
   with self.assertRaisesRegex(EngineError,'watch_not_found'):engine.item(app.connect,uid,self.req['watch_id'],mode)
  with patch.dict(os.environ,{'ESCAPE_HW_CAPACITY':'1'}):
   d=copy.deepcopy(self.req);d.update(watch_id='second',purpose='another purpose')
   with self.assertRaisesRegex(EngineError,'global_capacity_limit'):engine.create(app.connect,1,d,self.now)
  d=copy.deepcopy(self.req);d.update(watch_id='invalid-prod',is_test=False)
  with self.assertRaisesRegex(EngineError,'synthetic_requires_test_mode'):engine.create(app.connect,1,d,self.now)
 def test_twenty_session_default_and_claim_only_charges_real_adapter_requests(self):
  with patch.dict(os.environ,{},clear=True):self.assertEqual(engine.capacity(),20)
  job=engine.claim(app.connect,self.now)
  self.assertIsNotNone(job)
  with app.connect() as c:self.assertEqual(c.execute('SELECT COALESCE(sum(used),0) FROM hw_request_budget').fetchone()[0],0)
 def test_fast_eodhd_polling_is_explicit_bounded_and_budgeted(self):
  from hotwatch_contract import provider_floor
  from hotwatch_adapters import providers
  with patch.dict(os.environ,{},clear=True):
   self.assertEqual(provider_floor('eodhd'),300);self.assertEqual(providers()['eodhd']['minimum_poll_s'],300)
  for setting in ['4','301','broken','-1']:
   with self.subTest(setting=setting),patch.dict(os.environ,{'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':setting}):self.assertEqual(provider_floor('eodhd'),300)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':'5','ESCAPE_HW_REQUESTS_PER_MINUTE':'1'}):
   self.assertEqual(provider_floor('eodhd'),5);self.assertEqual(providers()['eodhd']['minimum_poll_s'],5);self.assertEqual(provider_floor('pluto'),300)
   reserve(app.connect,1,'eodhd',self.now)
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now)
 def test_fast_eodhd_scheduling_uses_opt_in_floor_without_weakening_risk(self):
  from hotwatch_contract import GLOBAL_RISK
  req=copy.deepcopy(self.req);req.update(watch_id='fast-eodhd',purpose='fast eodhd fixture',provider='eodhd',provider_symbol='MERC.US',profile='ACTIVE')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':'5'}):
   engine.create(app.connect,1,req,self.now);sample=tick(self.now);sample.update(source='eodhd',interval_s=15)
   engine.ingest(app.connect,1,req['watch_id'],True,sample,self.now)
   session=engine.item(app.connect,1,req['watch_id'],True)['session']
   self.assertEqual(session['effective_min_interval_s'],15);self.assertEqual((stamp(session['next_due_at'])-self.now).total_seconds(),15);self.assertEqual(GLOBAL_RISK['max_quote_age_s'],120)
 def test_live_eodhd_defaults_to_minute_updates_and_rest_keeps_its_floor(self):
  from hotwatch_contract import provider_floor
  env={'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'0','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}
  with patch.dict(os.environ,env):
   self.assertEqual(provider_floor('eodhd'),60)
   req=copy.deepcopy(self.req);req.update(watch_id='minute-live',purpose='minute live',provider='eodhd',provider_symbol='MERC.US',profile='NORMAL')
   engine.create(app.connect,1,req,self.now);sample=tick(self.now);sample.update(source='eodhd',interval_s=60)
   engine.ingest(app.connect,1,req['watch_id'],True,sample,self.now)
   session=engine.item(app.connect,1,req['watch_id'],True)['session']
   self.assertEqual((stamp(session['next_due_at'])-self.now).total_seconds(),60)
  with patch.dict(os.environ,{**env,'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0'}):self.assertEqual(provider_floor('eodhd'),300)
 def test_parallel_due_scans_are_bounded_and_keep_shared_budget(self):
  import threading
  from hotwatch_service import Runner
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  for i in range(2):
   req=copy.deepcopy(self.req);req.update(watch_id='parallel-'+str(i),purpose='parallel fixture '+str(i),provider='pluto');engine.create(app.connect,1,req,self.now)
  gate=threading.Barrier(2);active=0;peak=0;lock=threading.Lock();self_now=self.now
  class FakePluto:
   def __init__(self,connect,uid):self.connect=connect;self.uid=uid
   def poll(self,job):
    nonlocal active,peak
    reserve(self.connect,self.uid,'pluto',self_now)
    with lock:active+=1;peak=max(peak,active)
    try:gate.wait(timeout=3)
    finally:
     with lock:active-=1
    sample=tick(self_now);sample.update(source='pluto',sample_id='sample-'+job['watch_id']);return sample
  with patch.dict(os.environ,{'ESCAPE_HW_PARALLEL_SCANS':'2','ESCAPE_HW_CONCURRENCY':'2','ESCAPE_HW_REQUESTS_PER_MINUTE':'2'}),patch('hotwatch_service.PlutoAdapter',FakePluto):
   count=Runner(app.connect).drain()
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],2)
   self.assertEqual(c.execute("SELECT sum(used) FROM hw_request_budget WHERE source='pluto'").fetchone()[0],2)
  self.assertEqual(count,2);self.assertEqual(peak,2)
 def test_parallel_scan_setting_defaults_to_one_and_caps_at_leases(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  runner=Runner(app.connect);runner.once=Mock(return_value=False)
  with patch.dict(os.environ,{},clear=True):self.assertEqual(runner.drain(),0)
  self.assertEqual(runner.once.call_count,1)
 def test_worker_heartbeat_remains_fresh_during_slow_provider_call(self):
  import threading,time
  from hotwatch_service import Runner
  runner=Runner(app.connect);entered=threading.Event();release=threading.Event()
  def slow():entered.set();release.wait(timeout=3);runner.stop.set();return 0
  with patch('hotwatch_service.HEARTBEAT_INTERVAL_S',.03),patch.object(runner,'drain',side_effect=slow):
   worker=threading.Thread(target=runner.run,kwargs={'interval':.01});worker.start()
   try:
    self.assertTrue(entered.wait(2));first=None
    for _ in range(100):
     with app.connect() as c:row=c.execute('SELECT updated,status FROM hw_heartbeat WHERE id=1').fetchone()
     if row and row['status']=='running':first=row['updated'];break
     time.sleep(.01)
    self.assertIsNotNone(first)
    latest=first
    for _ in range(100):
     with app.connect() as c:row=c.execute('SELECT updated,status FROM hw_heartbeat WHERE id=1').fetchone()
     if row and row['updated']!=first:latest=row['updated'];break
     time.sleep(.01)
    self.assertNotEqual(first,latest)
   finally:release.set();worker.join(timeout=4)
  self.assertFalse(worker.is_alive())
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_heartbeat WHERE id=1').fetchone()['status'],'stopped')
 def test_startup_diagnostics_reports_missing_eodhd_access_without_network_or_entitlement_claim(self):
  from hotwatch_service import startup_diagnostics
  with patch.dict(os.environ,{},clear=True):info=startup_diagnostics(app.connect)
  self.assertFalse(info['startup_probe']['network_requests_made']);self.assertEqual(info['eodhd']['startup_status'],'blocked_feed_disabled');self.assertFalse(info['eodhd']['entitlements_verified'])
 def test_duplicate_samples_not_new_market_events_and_conflicts_atomic(self):
  t=tick(self.now);self.put(t);before=self.counts();self.assertTrue(self.put(t)['duplicate']);self.assertEqual(before,self.counts());changed=copy.deepcopy(t);changed['volume']='101'
  with self.assertRaisesRegex(EngineError,'sample_id_conflict'):self.put(changed)
  self.assertEqual(before,self.counts())
  older=tick(self.now-timedelta(seconds=1),99)
  with self.assertRaisesRegex(EngineError,'out_of_order_market_data'):self.put(older)
 def test_broker_context_changes_do_not_create_or_confirm_new_quotes(self):
  original=tick(self.now);self.put(original);before=self.counts()['hw_samples'];changed=copy.deepcopy(original);changed['context'].update(as_of=(self.now+timedelta(seconds=10)).isoformat(),position='held',quantity='2');changed['context']['orders']=[{'order_id':'synthetic-partial','status':'PARTIAL','requested_quantity':'5','filled_quantity':'2','side':'BUY'}]
  result=self.put(changed,self.now+timedelta(seconds=10));self.assertFalse(result['calculation']['new_market_observation']);self.assertEqual(self.counts()['hw_samples'],before);self.assertNotEqual(result['calculation']['signal'],'BUY');self.assertEqual(result['session']['latest_context']['quantity'],'2');self.assertTrue(self.put(changed,self.now+timedelta(seconds=11))['duplicate'])
  history=engine.history(app.connect,1,self.req['watch_id'],True)['items'];self.assertTrue(any(e['event_type']=='ORDER_FILLED' for e in history))
 def test_same_market_timestamp_with_new_provider_id_is_not_a_new_observation(self):
  t=tick(self.now);self.put(t);before=self.counts();copy_tick=copy.deepcopy(t);copy_tick['sample_id']='another-read-id';self.assertTrue(self.put(copy_tick)['duplicate']);self.assertEqual(before,self.counts())
 def test_context_without_quote_preserves_broker_evidence_without_market_signal(self):
  ctx=tick(self.now,held=True)['context'];before=self.counts()
  engine.observe_context(app.connect,1,self.req['watch_id'],True,ctx,self.now)
  view=engine.item(app.connect,1,self.req['watch_id'],True)['session']
  self.assertEqual(view['latest_context']['quantity'],'10');self.assertIsNone(view['last_data_at']);self.assertEqual(view['signal'],'NO_DATA')
  self.assertEqual(self.counts()['hw_samples'],before['hw_samples']);self.assertEqual(self.counts()['hw_calculations'],before['hw_calculations'])
  self.assertTrue(engine.observe_context(app.connect,1,self.req['watch_id'],True,ctx,self.now)['duplicate'])
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  with self.assertRaisesRegex(EngineError,'watch_not_running'):engine.observe_context(app.connect,1,self.req['watch_id'],True,ctx,self.now)
 def test_runner_journals_broker_context_when_quote_time_is_unavailable(self):
  from hotwatch_service import Runner
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  r=copy.deepcopy(self.req);r.update(watch_id='broker-no-quote',purpose='broker-context-test',provider='pluto');engine.create(app.connect,1,r,self.now)
  error=DataUnavailable('PLUTO_QUOTE_TIME_UNKNOWN');error.position_context=tick(self.now,held=True)['context']
  from unittest.mock import Mock
  adapter=Mock();adapter.poll.side_effect=error;runner=Runner(app.connect);runner.adapters[(1,'pluto')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now))
  view=engine.item(app.connect,1,r['watch_id'],True)['session'];self.assertEqual(view['status'],'DEGRADED');self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['last_data_at']);self.assertEqual(view['latest_context']['quantity'],'10')
  self.assertEqual(self.counts()['hw_samples'],0)
 def test_checkpoint_context_migration_preserves_old_journal(self):
  ctx=tick(self.now)['context'];engine.observe_context(app.connect,1,self.req['watch_id'],True,ctx,self.now)
  with app.connect() as c:
   c.execute('DROP TABLE hw_context_events')
   c.execute('CREATE TABLE hw_context_events(id INTEGER PRIMARY KEY,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),sample_row_id INTEGER NOT NULL REFERENCES hw_samples(id),observed TEXT NOT NULL,payload TEXT NOT NULL)')
   sample=tick(self.now)
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(1,?,?,?,?,?,?)',('synthetic','legacy-tick',self.now.timestamp(),self.now.isoformat(),json.dumps(sample),checksum(sample)))
   c.execute('INSERT INTO hw_context_events VALUES(1,1,1,?,?)',(self.now.isoformat(),json.dumps(ctx)))
  app.init()
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_context_events').fetchone()[0],1)
   self.assertFalse(next(r for r in c.execute('PRAGMA table_info(hw_context_events)') if r['name']=='sample_row_id')['notnull'])
 def test_system_kill_blocks_work_and_requires_explicit_resume(self):
  before=self.counts()['hw_events'];engine.system_kill(app.connect,True,'Synthetic operator test',self.now)
  self.assertIsNone(engine.claim(app.connect,self.now));self.assertEqual(engine.item(app.connect,1,self.req['watch_id'],True)['session']['status'],'PAUSED')
  engine.system_kill(app.connect,False,'Synthetic release',self.now)
  with app.connect() as c:self.assertEqual([r[0] for r in c.execute('SELECT killed FROM hw_operator_events ORDER BY id')],[1,0])
  self.assertIsNone(engine.claim(app.connect,self.now));self.assertGreater(self.counts()['hw_events'],before)
  engine.control(app.connect,1,self.req['watch_id'],True,'resume',self.now);self.assertIsNotNone(engine.claim(app.connect,self.now))
 def test_unknown_tradability_blocks_new_buy(self):
  t=tick(self.now);t['context']['tradability']='unknown';r,_=calculate(t,good_metrics(),BASELINE,self.req['risk'],{},self.now);self.assertNotEqual(r['signal'],'BUY');self.assertIn('TRADABILITY_UNCONFIRMED',r['reason_codes'])
 def test_stale_future_missing_and_crossed_market(self):
  stale=tick(self.now-timedelta(seconds=121));r=self.put(stale);self.assertEqual(r['calculation']['signal'],'NO_DATA');self.assertIn('DATA_STALE',r['calculation']['reason_codes'])
  with self.assertRaisesRegex(EngineError,'future_market_data'):self.put(tick(self.now+timedelta(seconds=1),1))
  crossed=tick(self.now,2);crossed['bid']='101';crossed['ask']='99'
  with self.assertRaisesRegex(EngineError,'crossed_market'):self.put(crossed)
  m=tick(self.now,3);m['bid']=None;m['ask']=None;metrics=features([m],BASELINE['parameters']);self.assertIsNone(metrics['spread']);self.assertIsNone(metrics['spread_pct'])
 def test_session_expiry_without_market_write(self):
  d=copy.deepcopy(self.req);d.update(watch_id='expiring',purpose='expiry',end_at=(self.now+timedelta(seconds=1)).isoformat());engine.create(app.connect,1,d,self.now);before=self.counts()['hw_samples'];r=engine.ingest(app.connect,1,d['watch_id'],True,tick(self.now+timedelta(seconds=2)),self.now+timedelta(seconds=2));self.assertTrue(r['expired']);self.assertEqual(self.counts()['hw_samples'],before)
 def test_feature_causality_rsi_ema_macd_atr_and_missing_volume(self):
  rows=[tick(self.now+timedelta(minutes=i),i,str(100+i%2)) for i in range(40)];f=features(rows,BASELINE['parameters']);self.assertIsNotNone(f['rsi']);self.assertIsNotNone(f['macd_signal']);self.assertIsNotNone(f['atr']);self.assertIsNotNone(f['ema_short']);self.assertEqual(f['relative_volume'],'1')
  before=features(rows[:35],BASELINE['parameters']);rows[-1]['price']='100000';self.assertEqual(before,features(rows[:35],BASELINE['parameters']))
  no_volume=copy.deepcopy(rows[:35]);no_volume[-1]['volume']=None;self.assertIsNone(features(no_volume,BASELINE['parameters'])['relative_volume'])
 def test_market_phase_source_currency_interval_and_gaps_reset_features(self):
  rows=[tick(self.now+timedelta(minutes=i),i) for i in range(40)]
  for key,value in [('source','eodhd'),('currency','DKK'),('market_status','PRE'),('session_key','NEXT'),('interval_s',15)]:
   changed=copy.deepcopy(rows);changed[-1][key]=value;self.assertEqual(features(changed,BASELINE['parameters'])['sample_count'],1)
  changed=copy.deepcopy(rows);changed[-1]['event_time']=(self.now+timedelta(hours=10)).isoformat();self.assertEqual(features(changed,BASELINE['parameters'])['sample_count'],1)
 def test_volume_cumulative_deltas_not_session_totals(self):
  rows=[tick(self.now+timedelta(minutes=i),i) for i in range(15)]
  for i,r in enumerate(rows):r.update(volume=str(1000+i*100),volume_type='cumulative')
  f=features(rows,BASELINE['parameters']);self.assertEqual(f['interval_volume'],'100');self.assertEqual(f['relative_volume'],'1');rows[-1]['volume']='0';self.assertIsNone(features(rows,BASELINE['parameters'])['interval_volume'])
 def test_buy_confirmation_cooldown_and_risk_cannot_be_bypassed(self):
  state={};m=good_metrics();t=tick(self.now)
  for i in range(3):r,state=calculate(t,m,BASELINE,self.req['risk'],state,self.now+timedelta(seconds=i*10))
  self.assertEqual(r['signal'],'BUY');self.assertEqual(state['confirmations'],3)
  t['bid']=None;m['spread_pct']=None;r,_=calculate(t,m,BASELINE,self.req['risk'],state,self.now+timedelta(seconds=21));self.assertNotEqual(r['signal'],'BUY');self.assertIn('SPREAD_UNKNOWN',r['reason_codes'])
  m=good_metrics();m['spread_pct']='2';r,_=calculate(t,m,BASELINE,self.req['risk'],{},self.now);self.assertIn('SPREAD_TOO_WIDE',r['reason_codes']);self.assertEqual(r['signal'],'WAIT')
 def test_critical_exit_overrides_confirmation_and_cooldown_but_not_stale_data(self):
  t=tick(self.now,price='90',held=True);state={'signal':'BUY','last_signal_at':self.now.timestamp()};m=good_metrics();m.update(price='90',sample_count=1);r,_=calculate(t,m,BASELINE,self.req['risk'],state,self.now);self.assertEqual(r['signal'],'SELL');self.assertTrue(r['critical_override'])
  stale=copy.deepcopy(t);stale['event_time']=(self.now-timedelta(minutes=10)).isoformat();r,_=calculate(stale,m,BASELINE,self.req['risk'],state,self.now);self.assertEqual(r['signal'],'NO_DATA');self.assertIn('STOP_BREACHED',r['reason_codes']);self.assertFalse(r['critical_override'])
 def test_deadline_before_market_open_warns_without_claiming_execution(self):
  t=tick(self.now,held=True);t['market_status']='CLOSED';risk=copy.deepcopy(self.req['risk']);risk['exit_deadline']=(self.now-timedelta(seconds=1)).isoformat();r,_=calculate(t,good_metrics(),BASELINE,risk,{},self.now);self.assertEqual(r['signal'],'PAUSE');self.assertIn('EXIT_DEADLINE',r['reason_codes']);self.assertFalse(r['critical_override'])
 def test_permanent_identity_fault_enters_error_and_preserves_history(self):
  before=self.counts();engine.fault(app.connect,1,self.req['watch_id'],True,'quote_currency_mismatch',self.now);self.assertEqual(engine.item(app.connect,1,self.req['watch_id'],True)['session']['status'],'ERROR');self.assertEqual(self.counts()['hw_samples'],before['hw_samples'])
 def test_no_position_never_gets_holdings_sell(self):
  m=good_metrics();m.update(return_3_pct='-3',breakdown=True,distance_high_pct='-10');r,_=calculate(tick(self.now,price='90'),m,BASELINE,self.req['risk'],{},self.now);self.assertNotIn(r['signal'],['SELL','REDUCE'])
 def test_risk_size_exposure_cost_fx_halt_premarket_and_gap(self):
  for name,value,expected in [('fees_dkk',None,'RISK_INPUTS_UNKNOWN'),('fx_to_dkk',None,'RISK_INPUTS_UNKNOWN'),('portfolio_equity_dkk','100','EXPOSURE_LIMIT')]:
   t=tick(self.now);t['context'][name]=value;r,_=calculate(t,good_metrics(),BASELINE,self.req['risk'],{},self.now);self.assertIn(expected,r['reason_codes']);self.assertNotEqual(r['signal'],'BUY')
  for market in ['PRE','HALTED','CLOSED','UNKNOWN']:
   t=tick(self.now);t['market_status']=market;r,_=calculate(t,good_metrics(),BASELINE,self.req['risk'],{},self.now);self.assertNotEqual(r['signal'],'BUY')
  m=good_metrics();m['return_1_pct']='9';r,_=calculate(tick(self.now),m,BASELINE,self.req['risk'],{},self.now);self.assertIn('PRICE_GAP_LIMIT',r['reason_codes'])
 def test_kill_switch_no_deletion_and_explicit_resume(self):
  self.put(tick(self.now));before=self.counts();engine.kill(app.connect,1,True,'Syntetisk nødstop',self.now);self.assertEqual(engine.item(app.connect,1,self.req['watch_id'],True)['session']['status'],'PAUSED');self.assertEqual(self.counts()['hw_samples'],before['hw_samples'])
  with self.assertRaisesRegex(EngineError,'kill_switch_active'):engine.control(app.connect,1,self.req['watch_id'],True,'resume',self.now)
  engine.kill(app.connect,1,False,'Kontrolleret genstart',self.now);self.assertEqual(engine.item(app.connect,1,self.req['watch_id'],True)['session']['status'],'PAUSED');engine.control(app.connect,1,self.req['watch_id'],True,'resume',self.now)
 def test_leases_protect_pause_and_worker_restart(self):
  job=engine.claim(app.connect,self.now);self.assertIsNotNone(job);self.assertIsNone(engine.claim(app.connect,self.now));engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  with self.assertRaises(EngineError):engine.ingest(app.connect,1,self.req['watch_id'],True,tick(self.now),self.now,job['lease_owner'])
  engine.control(app.connect,1,self.req['watch_id'],True,'resume',self.now);job=engine.claim(app.connect,self.now);app.init();self.assertIsNone(engine.claim(app.connect,self.now+timedelta(seconds=10)));self.assertIsNotNone(engine.claim(app.connect,self.now+timedelta(seconds=121)))
 def test_fault_backoff_dedup_and_recovery(self):
  engine.fault(app.connect,1,self.req['watch_id'],True,'DATA_STALE',self.now);before=self.counts();engine.fault(app.connect,1,self.req['watch_id'],True,'DATA_STALE',self.now+timedelta(seconds=5));self.assertEqual(before,self.counts());self.assertEqual(engine.item(app.connect,1,self.req['watch_id'],True)['session']['status'],'DEGRADED')
  self.put(tick(self.now+timedelta(seconds=60),1),self.now+timedelta(seconds=60));events=engine.history(app.connect,1,self.req['watch_id'],True)['items'];self.assertTrue(any(e['event_type']=='DATA_RECOVERED' for e in events))
 def test_local_budget_retry_and_expired_display_explain_actual_cause(self):
  engine.fault(app.connect,1,self.req['watch_id'],True,'PROVIDER_RATE_BUDGET',self.now)
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True);view=engine.view(c,row,self.now)
   self.assertEqual(row['next_due'],self.now.timestamp()+60);self.assertIn('PROVIDER_RATE_BUDGET',view['display_reason_codes'])
  self.put(tick(self.now+timedelta(seconds=61),1),self.now+timedelta(seconds=61))
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True);view=engine.view(c,row,self.now+timedelta(seconds=182))
   self.assertEqual(view['signal'],'NO_DATA');self.assertIn('DATA_STALE',view['display_reason_codes']);self.assertEqual(view['data_status']['price'],'100')
 def test_order_accepted_partial_filled_are_separate_from_signals(self):
  for i,filled in enumerate(['0','4','4','10']):
   t=tick(self.now+timedelta(minutes=i),i,held=True);t['context']['orders']=[{'order_id':'synthetic-limit','status':'ACCEPTED' if i==0 else 'PARTIAL' if i<3 else 'FILLED','requested_quantity':'10','filled_quantity':filled,'side':'SELL'}];self.put(t,self.now+timedelta(minutes=i))
  events=engine.history(app.connect,1,self.req['watch_id'],True)['items'];fills=[e for e in events if e['event_type']=='ORDER_FILLED'];self.assertEqual([e['data']['supporting_metrics']['filled_quantity'] for e in fills],['4','10']);self.assertEqual(self.counts()['hw_samples'],4)
  sample=engine.history(app.connect,1,self.req['watch_id'],True,'samples',order='desc')['items'][0]['data'];self.assertEqual(sample['context']['quantity'],'10')
 def test_declarative_versions_no_code_and_unqualified_upload_never_active(self):
  self.assertEqual(validate_strategy(BASELINE),[])
  for bad in [{'metric':'__import__','operator':'==','value':'x'},{'metric':'price','operator':'eval','value':'1'},{'metric':[],'operator':'==','value':1}]:
   d=copy.deepcopy(BASELINE);d['entry_rules']=bad;self.assertTrue(validate_strategy(d))
  d=copy.deepcopy(BASELINE);d['version']='1.1.0';engine.upload_strategy(app.connect,1,'synthetic-admin',d);self.assertTrue(engine.upload_strategy(app.connect,1,'synthetic-admin',d)['duplicate']);changed=copy.deepcopy(d);changed['description']='Changed'
  with self.assertRaisesRegex(EngineError,'strategy_version_conflict'):engine.upload_strategy(app.connect,1,'synthetic-admin',changed)
  r=copy.deepcopy(self.req);r.update(watch_id='unqualified',purpose='new algorithm',strategy_version='1.1.0')
  with self.assertRaisesRegex(EngineError,'strategy_qualification_required'):engine.create(app.connect,1,r,self.now)
 def test_request_budget_and_gateway_cannot_write_even_if_annotated_readonly(self):
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'1'}):
   reserve(app.connect,1,'synthetic-test',self.now)
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'synthetic-test',self.now)
  gateway=PlutoAdapter(app.connect,1).factory('SYNTHETIC-TOKEN');gateway.catalog=[{'name':'propose_orders','annotations':{'readOnlyHint':True}}]
  with patch('mcp_client.MCP.request',side_effect=AssertionError('Must not send write')):
   with self.assertRaisesRegex(DataUnavailable,'PLUTO_WRITE_OR_UNKNOWN_TOOL_BLOCKED'):gateway.request('tools/call',{'name':'propose_orders','arguments':{}})
 def test_scheduler_prioritizes_existing_critical_profile_without_changing_signal(self):
  second=copy.deepcopy(self.req);second.update(watch_id='critical-scheduler-watch',purpose='critical scheduler candidate')
  engine.create(app.connect,1,second,self.now)
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET state=? WHERE watch_id=?",(json.dumps({'signal':'WAIT','adaptive_profile':'CRITICAL'}),second['watch_id']))
   c.execute('UPDATE hw_sessions SET next_due=?',(self.now.timestamp(),))
  job=engine.claim(app.connect,self.now+timedelta(seconds=1));self.assertEqual(job['watch_id'],second['watch_id'])
  view=engine.item(app.connect,1,second['watch_id'],True)['session'];self.assertEqual(view['last_computed_signal'],'NO_DATA')
 def test_eodhd_disabled_without_purchase_and_errors_do_not_leak_key(self):
  with patch.dict(os.environ,{},clear=True):
   with self.assertRaisesRegex(DataUnavailable,'EODHD_FEED_NOT_ENABLED'):EODHDAdapter(app.connect,1).poll({'request_data':self.req})
  class Bad:
   def open(self,*a,**k):raise RuntimeError('SECRET-TEST-KEY')
  req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'SECRET-TEST-KEY'}):
   with self.assertRaises(DataUnavailable) as err:EODHDAdapter(app.connect,1,Bad()).poll({'request_data':req})
   self.assertNotIn('SECRET-TEST-KEY',str(err.exception))
 def test_eodhd_quote_without_currency_uses_explicit_instrument_currency(self):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'MERC.US','timestamp':int(self_now.timestamp()),'close':'12.34'}).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  self_now=self.now;req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US',quote_currency='USD')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY'}),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):
   sample=EODHDAdapter(app.connect,1,Opener()).poll({'request_data':req})
  self.assertEqual(sample['currency'],'USD');self.assertIn('explicit session instrument',sample['feed_type']);self.assertIsNone(sample['volume']);self.assertIsNone(sample['bid'])
 def test_eodhd_quote_trims_whitespace_from_existing_key(self):
  from urllib.parse import urlsplit,parse_qs
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'MERC.US','timestamp':int(observed.timestamp()),'close':'12.34','currency':'USD'}).encode()
  class Capture:
   def open(self,request,**kwargs):self.token=parse_qs(urlsplit(request.full_url).query)['api_token'][0];return Response()
  observed=self.now;opener=Capture();req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US',quote_currency='USD')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'  TEST-ONLY\n'}),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):
   sample=EODHDAdapter(app.connect,1,opener).poll({'request_data':req})
  self.assertEqual(opener.token,'TEST-ONLY');self.assertNotIn('TEST-ONLY',str(sample))
 def test_eodhd_quote_records_its_own_market_not_pluto_venue(self):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'NOVO-B.CO','timestamp':int(observed.timestamp()),'close':'100','currency':'DKK'}).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  observed=self.now;req=copy.deepcopy(self.req);req.update(ticker='NOVOB',exchange='CHIX',provider='eodhd',provider_symbol='NOVO-B.CO',quote_currency='DKK')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY'}),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):
   sample=EODHDAdapter(app.connect,1,Opener()).poll({'request_data':req})
  self.assertEqual(sample['source'],'eodhd');self.assertEqual(sample['venue'],'EODHD:CO');self.assertEqual(req['exchange'],'CHIX');self.assertEqual(sample['currency'],'DKK')
 def test_eodhd_reported_volume_keeps_unknown_basis_and_existing_observation(self):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps(payload).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  r=copy.deepcopy(self.req);r.update(watch_id='eodhd-volume',purpose='eodhd volume test',provider='eodhd',provider_symbol='MERC.US')
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now);engine.create(app.connect,1,r,self.now)
  with app.connect() as c:row=dict(c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(r['watch_id'],)).fetchone())
  row['request_data']=r;payload={'code':'MERC.US','timestamp':int(self.now.timestamp()),'close':'12.34','currency':'USD'}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY'}),patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()):
   adapter=EODHDAdapter(app.connect,1,Opener());old=adapter.poll(row)
   engine.ingest(app.connect,1,r['watch_id'],True,old,self.now)
   payload['volume']=12345;repeated=adapter.poll(row)
   self.assertIsNone(repeated['volume']);self.assertTrue(engine.ingest(app.connect,1,r['watch_id'],True,repeated,self.now)['duplicate'])
   payload['timestamp']+=1;fresh=adapter.poll(row)
   self.assertEqual(fresh['volume'],'12345');self.assertEqual(fresh['volume_type'],'unknown');self.assertIsNone(fresh['bid']);self.assertIsNone(fresh['ask'])
   result=engine.ingest(app.connect,1,r['watch_id'],True,fresh,self.now+timedelta(seconds=1))
   self.assertIsNone(result['calculation']['supporting_metrics']['interval_volume'])
   payload['volume']=-3;payload['timestamp']+=1
   self.assertIsNone(adapter.poll(row)['volume'])
 def test_eodhd_rate_limit_retry_after_is_observed_and_secret_redacted(self):
  import urllib.error
  class Limited:
   def open(self,*a,**k):raise urllib.error.HTTPError('https://example.invalid/SECRET',429,'limited',{'Retry-After':'900'},None)
  req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'SYNTHETIC-SECRET'}):
   with self.assertRaises(DataUnavailable) as err:EODHDAdapter(app.connect,1,Limited()).poll({'request_data':req})
   self.assertEqual(err.exception.code,'EODHD_RATE_LIMIT');self.assertEqual(err.exception.retry_after_s,900);self.assertNotIn('SECRET',str(err.exception))
   engine.fault(app.connect,1,self.req['watch_id'],True,err.exception.code,self.now,retry_after_s=err.exception.retry_after_s)
   with app.connect() as c:self.assertGreaterEqual(c.execute('SELECT next_due FROM hw_sessions').fetchone()[0],self.now.timestamp()+900)
 def test_runner_eodhd_adapter_preserves_market_time_and_measures_ingestion(self):
  from hotwatch_service import Runner
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'MERC.US','timestamp':int(self.now.timestamp()),'close':'12.34','currency':'USD'}).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  at=engine.utc().replace(microsecond=0);r=copy.deepcopy(self.req);r.update(watch_id='eodhd-runner-readonly',purpose='eodhd normal adapter test',provider='eodhd',provider_symbol='MERC.US')
  r['asset_id']='synthetic-MERC';r['report_id']=self.r['report_id'];engine.control(app.connect,1,self.req['watch_id'],True,'pause',at)
  with patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY-SECRET'}):
   engine.create(app.connect,1,r,at);runner=Runner(app.connect);runner.adapters[(1,'eodhd')]=EODHDAdapter(app.connect,1,Opener())
   # Adapter source timestamp is fixed to a known epoch and must remain exact through journal ingestion.
   epoch=int(at.timestamp());Response.now=at
   self.assertTrue(runner.once(at+timedelta(milliseconds=1)))
  self.assertIn('eodhd_http_ms',runner.adapters[(1,'eodhd')].last_telemetry);self.assertIn('pluto_context_ms',runner.adapters[(1,'eodhd')].last_telemetry)
  item=engine.history(app.connect,1,r['watch_id'],True,'samples')['items'][0]['data']
  self.assertEqual(stamp(item['event_time']).timestamp(),epoch);self.assertEqual(item['venue'],'EODHD:US');self.assertNotEqual(item['venue'],r['exchange'])
  with app.connect() as c:health=json.loads(c.execute("SELECT payload FROM hw_provider_health WHERE user_id=1 AND is_test=1 AND source='eodhd'").fetchone()['payload'])
  self.assertTrue(health['market_time_known']);self.assertIsInstance(health['event_to_adapter_receive_ms'],(int,float));self.assertIsInstance(health['adapter_to_journal_ms'],(int,float));self.assertGreaterEqual(health['adapter_to_journal_ms'],0)
 def test_worker_websocket_denied_falls_back_to_real_rest_observation(self):
  from hotwatch_service import Runner
  at=engine.utc().replace(microsecond=0);r=copy.deepcopy(self.req);r.update(watch_id='mock-rest-fallback',purpose='mock fallback chain',provider='eodhd',provider_symbol='MERC.US')
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'MERC.US','timestamp':int(at.timestamp()),'close':'12.34','previousClose':'12','currency':'USD'}).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  class Feeds:
   def capture(self,*args,**kwargs):return {'status':'ENTITLEMENT_UNVERIFIED'}
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',at);engine.create(app.connect,1,r,at);runner=Runner(app.connect);adapter=EODHDAdapter(app.connect,1,Opener());runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()),patch.object(adapter,'feeds',return_value=Feeds()),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1'}):
   self.assertTrue(runner.once(at+timedelta(milliseconds=1),watch_id=r['watch_id']))
  view=engine.item(app.connect,1,r['watch_id'],True)['session'];self.assertEqual(view['data_status']['price'],'12.34');self.assertEqual(view['last_data_at'],at.isoformat());self.assertEqual(view['display_status'],'AFVENTER SIGNALDATA')
  with app.connect() as c:health=json.loads(c.execute("SELECT payload FROM hw_provider_health WHERE user_id=1 AND is_test=1 AND source='eodhd'").fetchone()['payload'])
  self.assertEqual(health['websocket_trade_status'],'ENTITLEMENT_UNVERIFIED')
 def test_runner_ingests_real_source_time_from_mocked_ws_without_changing_risk(self):
  from hotwatch_service import Runner
  at=engine.utc().replace(microsecond=0);r=copy.deepcopy(self.req);r.update(watch_id='eodhd-ws-test',purpose='mock ws test',provider='eodhd',provider_symbol='MERC.US')
  class Stream:
   def capture(self,*args,**kwargs):return {'status':'OK','messages':[{'event_time':at.isoformat(),'price':'12.34'}]}
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',at)
  with patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()),patch('hotwatch_adapters.EODHDAdapter.feeds',return_value=Stream()),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY'}):
   engine.create(app.connect,1,r,at);runner=Runner(app.connect);self.assertTrue(runner.once(at+timedelta(milliseconds=1)))
  sample=engine.history(app.connect,1,r['watch_id'],True,'samples')['items'][0]['data']
  self.assertEqual(sample['event_time'],at.isoformat());self.assertIsNone(sample['venue']);self.assertEqual(sample['market_status'],'UNKNOWN');self.assertIsNone(sample['bid'])
  self.assertEqual(engine.item(app.connect,1,r['watch_id'],True)['session']['signal'],'NO_DATA')
 def test_live_trade_quote_status_and_real_bars_drive_full_signal_chain(self):
  from hotwatch_service import Runner
  base=datetime(2026,11,4,15,15,tzinfo=timezone.utc);r=copy.deepcopy(self.req);r.update(watch_id='mock-full-live',purpose='mock complete feed',provider='eodhd',provider_symbol='MERC.US')
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',base);engine.create(app.connect,1,r,base)
  prices=['100' if i%2==0 else '100.5' for i in range(34)]+['100.55','100.70','100.90','101.15','101.45','101.80','90']
  class Feeds:
   i=0
   def capture(self,feed,*args,**kwargs):
    at=base+timedelta(minutes=self.i);price=Decimal(prices[33+self.i])
    if feed.endswith('trades'):row={'event_time':at.isoformat(),'received_at':at.isoformat(),'price':str(price),'market_session':'open'}
    elif feed.endswith('quotes'):row={'event_time':at.isoformat(),'bid':str(price-Decimal('.05')),'ask':str(price+Decimal('.05'))}
    else:row={'event_time':at.isoformat(),'trading_status':'T'}
    return {'status':'OK','messages':[row]}
   def market_status(self,exchange):
    return {'status':'OK','exchange_open':True,'timezone':'America/New_York','received_at':(base+timedelta(minutes=self.i)).isoformat(),'calendar':{'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}}
   def minute_bars(self,*args):
    data=[]
    for j,price in enumerate(prices[:34+self.i]):
     at=base-timedelta(minutes=34)+timedelta(minutes=j);p=Decimal(price);volume=100 if j<34 else 1000*2**(j-34)
     data.append({'bar_open_at':at.isoformat(),'open':str(p),'high':str(p+Decimal('.1')),'low':str(p-Decimal('.1')),'close':str(p),'volume':str(volume)})
    return {'status':'OK','bars':data}
  feeds=Feeds();runner=Runner(app.connect);signals=[]
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'1','ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':'5'}
  with patch.dict(os.environ,env),patch('hotwatch_adapters.EODHDAdapter.feeds',return_value=feeds):
   for i in range(7):
    feeds.i=i;now=base+timedelta(minutes=i);context=tick(now)['context']
    with patch('hotwatch_adapters.PlutoAdapter.context',return_value=context),patch('hotwatch_adapters.utc',return_value=now),patch('hotwatch_engine.utc',return_value=now):
     self.assertTrue(runner.once(now,watch_id=r['watch_id']));signals.append(engine.item(app.connect,1,r['watch_id'],True)['session']['last_computed_signal'])
     if i==6:
      import dashboard_projection
      rows=dashboard_projection.engine_session_view(app.connect,1,True,'current',100,None)['sessions'];display=next(x for x in rows if x['watch_id']==r['watch_id'])
      self.assertEqual(display['display_status'],'KØBSSIGNAL');self.assertEqual(display['data_status']['quote_status'],'FRESH');self.assertIsNotNone(display['data_status']['momentum_pct']['5'])
  self.assertIn('BUY',signals)
  saved=engine.history(app.connect,1,r['watch_id'],True,'samples',order='desc')['items'][0]['data'];self.assertEqual(len(saved['bar_history']),40);self.assertEqual(saved['bid_at'],saved['event_time']);self.assertEqual(saved['status_feed'],'us_status')
  feeds.i=7;now=base+timedelta(minutes=7);held=tick(now,price='90',held=True)['context']
  with patch.dict(os.environ,env),patch('hotwatch_adapters.EODHDAdapter.feeds',return_value=feeds),patch('hotwatch_adapters.PlutoAdapter.context',return_value=held),patch('hotwatch_adapters.utc',return_value=now),patch('hotwatch_engine.utc',return_value=now):
   self.assertTrue(runner.once(now,watch_id=r['watch_id']));self.assertEqual(engine.item(app.connect,1,r['watch_id'],True)['session']['last_computed_signal'],'SELL')
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
   health=json.loads(c.execute("SELECT payload FROM hw_provider_health WHERE user_id=1 AND is_test=1 AND source='eodhd'").fetchone()['payload']);self.assertEqual(health['bar_history_status'],'VERIFIED')
 def test_worker_keeps_fresh_trade_if_local_budget_runs_out_mid_scan(self):
  from hotwatch_service import Runner
  now=engine.utc().replace(microsecond=0);r=copy.deepcopy(self.req);r.update(watch_id='budget-live',purpose='local budget integration',provider='eodhd',provider_symbol='MERC.US')
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',now);engine.create(app.connect,1,r,now)
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'100','market_session':'open'}]}
    return {'status':'LOCAL_BUDGET_EXHAUSTED'}
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'0'}
  with patch.dict(os.environ,env),patch('hotwatch_adapters.EODHDAdapter.feeds',return_value=Feeds()),patch('hotwatch_adapters.PlutoAdapter.context',return_value=tick(now)['context']):
   self.assertTrue(Runner(app.connect).once(now,watch_id=r['watch_id']))
  view=engine.item(app.connect,1,r['watch_id'],True)['session']
  self.assertEqual(view['data_status']['price'],'100');self.assertEqual(view['display_status'],'AFVENTER SIGNALDATA');self.assertNotEqual(view['last_error'],'EODHD_RATE_LIMIT');self.assertIsNone(view['data_status']['bid'])
 def test_minute_bar_adapter_to_motor_preserves_volume_and_missing_session(self):
  from hotwatch_service import Runner
  at=engine.utc().replace(microsecond=0);r=copy.deepcopy(self.req);r.update(watch_id='mock-minute-bars',purpose='mock minute bars',provider='eodhd',provider_symbol='MERC.US')
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',at)
  class Bars:
   index=0
   def minute_bars(self,*args):
    opened=at+timedelta(minutes=self.index);price=Decimal(100+self.index);v=100+self.index*self.index*10
    return {'status':'OK','bars':[{'bar_open_at':opened.isoformat(),'open':str(price),'high':str(price),'low':str(price),'close':str(price),'volume':str(v)}]}
  bars=Bars()
  with patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()),patch('hotwatch_adapters.EODHDAdapter.feeds',return_value=bars),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'1','ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':'5'}):
   engine.create(app.connect,1,r,at);runner=Runner(app.connect)
   for index in range(4):
    bars.index=index;now=at+timedelta(minutes=index+1)
    with patch('hotwatch_adapters.utc',return_value=now),patch('hotwatch_engine.utc',return_value=now):self.assertTrue(runner.once(now))
  session=engine.item(app.connect,1,r['watch_id'],True)['session'];metrics=session['latest_calculation']['supporting_metrics']
  self.assertEqual(metrics['sample_count'],4);self.assertGreater(Decimal(metrics['return_3_pct']),0);self.assertGreater(Decimal(metrics['volume_acceleration']),0)
  self.assertEqual(session['last_computed_signal'],'NO_DATA');self.assertEqual(len(engine.history(app.connect,1,r['watch_id'],True,'samples')['items']),4)
 def test_live_buy_display_expires_when_quote_is_stale_even_if_price_is_fresh(self):
  at=engine.utc().replace(microsecond=0);r=copy.deepcopy(self.req);r.update(watch_id='mock-quote-age',purpose='mock quote age',provider='eodhd',provider_symbol='MERC.US')
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',at);engine.create(app.connect,1,r,at)
  sample=tick(at);sample.update(source='eodhd',feed_type='mock EODHD trade',bid_at=(at-timedelta(seconds=119)).isoformat(),ask_at=(at-timedelta(seconds=119)).isoformat(),status_at=at.isoformat(),quote_feed='mock_quotes',status_feed='mock_status')
  engine.ingest(app.connect,1,r['watch_id'],True,sample,at)
  with app.connect() as c:
   row=c.execute('SELECT state FROM hw_sessions WHERE watch_id=?',(r['watch_id'],)).fetchone();state=json.loads(row['state']);state['signal']='BUY';c.execute('UPDATE hw_sessions SET state=? WHERE watch_id=?',(json.dumps(state),r['watch_id']))
   view=engine.view(c,engine.row_for(c,1,r['watch_id'],True),at+timedelta(seconds=2))
  self.assertFalse(view['data_stale']);self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(view['data_status']['quote_status'],'STALE');self.assertIn('MARKET_EVIDENCE_STALE',view['display_reason_codes'])
 def test_discovery_verifies_identity_and_is_idempotent_without_orders(self):
  from hotwatch_service import auto_activate_candidate
  report=copy.deepcopy(self.r);report['report_id']='synthetic-auto-report';candidate=report['candidates'][0];candidate['candidate_id']='synthetic-new-discovery';candidate['asset_id']='synthetic-auto-asset';candidate['exchange']='NASDAQ';report_ingest.save(app.connect,1,report)
  import candidate_lifecycle
  with app.connect() as c:candidate_lifecycle.record(c,1,True,candidate['candidate_id'],'WAITING_TRIGGER',engine.utc().isoformat(),'Synthetic existing cycle','test','cycle-preserved')
  verified={'asset_id':'synthetic-auto-asset','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  verify=lambda *args:verified
  lookup=lambda *args:{'choices':[{'symbol':'MERC.US','currency':'USD','isin':'US1234567890'}]}
  result=auto_activate_candidate(app.connect,1,True,report,candidate,verify,lookup);self.assertEqual(result['status'],'ACTIVE')
  again=auto_activate_candidate(app.connect,1,True,report,candidate,verify,lookup);self.assertIn(again['status'],('NOT_NEW','ALREADY_ACTIVE'))
  session=engine.item(app.connect,1,result['watch_id'],True)['session'];self.assertEqual(session['request']['candidate_id'],candidate['candidate_id']);self.assertEqual(session['request']['trade_cycle_id'],'cycle-preserved');self.assertIsNone(session['request']['risk']['proposed_quantity'])
  from hotwatch_service import Runner
  at=engine.utc().replace(microsecond=0)
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):item={'event_time':at.isoformat(),'price':'100','market_session':'open'}
    elif feed.endswith('quotes'):item={'event_time':at.isoformat(),'bid':'99.9','ask':'100.1'}
    else:item={'event_time':at.isoformat(),'trading_status':'T'}
    return {'status':'OK','messages':[item]}
  now=at+timedelta(seconds=1)
  with patch('hotwatch_adapters.PlutoAdapter.context',return_value=unknown_context()),patch('hotwatch_adapters.EODHDAdapter.feeds',return_value=Feeds()),patch('hotwatch_adapters.utc',return_value=now),patch('hotwatch_engine.utc',return_value=now),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}):
   self.assertTrue(Runner(app.connect).once(now,watch_id=result['watch_id']))
  import dashboard_projection
  projected=dashboard_projection.engine_session_view(app.connect,1,True,'current',100,None)
  self.assertTrue(any(x['watch_id']==result['watch_id'] and x['data_status']['price']=='100' for x in projected['sessions']))
  app.init();self.assertEqual(len(engine.history(app.connect,1,result['watch_id'],True,'samples')['items']),1)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_discovery_rejects_unverified_or_ambiguous_instruments(self):
  from hotwatch_service import auto_activate_candidate
  report=copy.deepcopy(self.r);report['report_id']='synthetic-ambiguous-report';candidate=report['candidates'][0];candidate['candidate_id']='synthetic-ambiguous';candidate['asset_id']='synthetic-asset';candidate['exchange']='NASDAQ';report_ingest.save(app.connect,1,report)
  verified={'asset_id':'synthetic-asset','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  self.assertEqual(auto_activate_candidate(app.connect,1,True,report,candidate,lambda *a:None,lambda *a:{})['status'],'PLUTO_VERIFICATION_REQUIRED')
  ambiguous=lambda *a:{'choices':[{'symbol':'MERC.US','currency':'USD','isin':'US1234567890'},{'symbol':'MERC.X','currency':'USD','isin':'US1234567890'}]}
  self.assertEqual(auto_activate_candidate(app.connect,1,True,report,candidate,lambda *a:verified,ambiguous)['status'],'EODHD_IDENTITY_UNCERTAIN')
 def test_discovery_respects_kill_switch_before_provider_calls(self):
  from hotwatch_service import auto_activate_candidate
  report=copy.deepcopy(self.r);report['report_id']='synthetic-killed-report';candidate=report['candidates'][0];candidate['candidate_id']='synthetic-killed';candidate['asset_id']='synthetic-asset';report_ingest.save(app.connect,1,report)
  engine.kill(app.connect,1,True,'synthetic test',engine.utc())
  def forbidden(*args):raise AssertionError('No provider access under kill switch')
  self.assertEqual(auto_activate_candidate(app.connect,1,True,report,candidate,forbidden,forbidden)['status'],'kill_switch_active')
 def test_auto_discovery_never_replays_reports_before_explicit_cutoff(self):
  from hotwatch_service import auto_discover
  report=merc_report(False);report['report_id']='synthetic-cutoff-report';report_ingest.save(app.connect,1,report)
  with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(engine.utc()+timedelta(minutes=1)).isoformat()}),patch('hotwatch_service.auto_activate_candidate') as start:
   auto_discover(app.connect);start.assert_not_called()
  with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(engine.utc()-timedelta(minutes=1)).isoformat()}),patch('hotwatch_service.auto_activate_candidate',return_value={'status':'NOT_NEW'}) as start:
   auto_discover(app.connect);start.assert_called_once()
 def test_discovery_does_not_assume_account_permission_from_asset_size_support(self):
  from hotwatch_service import verified_discovery_instrument
  candidate={'asset_id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ'}
  raw={'asset':{'id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'},'buyBy':{'shares':True}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw):
   self.assertIsNone(verified_discovery_instrument(app.connect,1,candidate))
 def test_tradability_requires_matching_asset_sizing_and_fresh_account_permission(self):
  adapter=PlutoAdapter(app.connect,1);portfolio={'id':123};raw={'asset':{'id':self.req['asset_id'],'ticker':'MERC','exchange':'NASDAQ','currency':'USD'},'buyBy':{'shares':True}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw),patch('trade_service.fresh_permission',side_effect=ValueError('not permitted')):
   self.assertEqual(adapter.tradability(self.req,'USD',[portfolio]),('unknown',None))
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw),patch('trade_service.fresh_permission'):
   status,checked=adapter.tradability(self.req,'USD',[portfolio]);self.assertEqual(status,'available');self.assertIsNotNone(checked)
  wrong=copy.deepcopy(self.req);wrong['ticker']='OTHER'
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw):
   self.assertEqual(adapter.tradability(wrong,'USD',[portfolio]),('unknown',None))
 def test_automatic_pluto_context_checks_all_portfolios_and_never_assumes_absence(self):
  import portfolios,portfolio_data
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:root','name':'Root','kind':'portfolio'},{'id':'collections:child','name':'Child','kind':'collection','parent_external_id':'portfolios:root'}])
   ids=[p['id'] for p in portfolios.list_owned(c,1)]
   for pid in ids:
    portfolio_data.save(c,1,pid,{'observed':engine.utc().isoformat(),'positions':[],'positions_complete':True,'complete':True,'value':{'value':{'amount':'1000','currency':'DKK'}},'pending_orders':[]})
  adapter=PlutoAdapter(app.connect,1)
  with patch.object(adapter,'tradability',return_value=('unknown',None)),patch.object(adapter,'inactive_orders',return_value=[]):
   result=adapter.context(self.req,'USD')
   self.assertEqual((result['status'],result['position'],result['quantity']),('verified','none','0'))
   self.assertIsNone(result['portfolio_equity_dkk'])
   with app.connect() as c:
    row=c.execute('SELECT payload FROM portfolio_snapshots WHERE portfolio_id=?',(ids[0],)).fetchone();payload=json.loads(row['payload']);payload['positions']=[{'asset_id':self.req['asset_id'],'ticker':'MERC','quantity':'2'}];c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(payload),ids[0]))
   overlap=adapter.context(self.req,'USD');self.assertEqual(overlap['status'],'unknown');self.assertEqual(overlap['diagnostic'],'HOLDING_SCOPE_OVERLAP')
   with app.connect() as c:
    payload['positions']=[];payload['positions_complete']=False;c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(payload),ids[0]))
   incomplete=adapter.context(self.req,'USD');self.assertEqual(incomplete['status'],'unknown');self.assertEqual(incomplete['diagnostic'],'PORTFOLIO_SNAPSHOT_INCOMPLETE')
 def test_realistic_synthetic_merc_buy_noise_exit_and_history_pinning(self):
  last=None
  prices=['100' if i%2==0 else '100.5' for i in range(34)]+['100.55','100.70','100.90','101.15','101.45','101.80']
  signals=[]
  for i,price in enumerate(prices):
   at=self.now+timedelta(minutes=i);t=tick(at,i,price);t['volume']=str(100 if i<34 else 1000*2**(i-34));last=self.put(t,at);signals.append(last['calculation']['signal'])
  self.assertIn('BUY',signals);self.assertTrue(all(s=='NO_DATA' for s in signals[:33]));self.assertEqual(last['calculation']['strategy_checksum'],checksum(BASELINE))
  at+=timedelta(minutes=1);t=tick(at,99,'90',True);exit=self.put(t,at);self.assertEqual(exit['calculation']['signal'],'SELL');self.assertTrue(exit['calculation']['critical_override'])
  events=engine.history(app.connect,1,self.req['watch_id'],True,limit=100)['items'];self.assertTrue(any(e['event_type']=='BUY_SIGNAL' for e in events));self.assertTrue(any(e['event_type']=='CRITICAL_OVERRIDE' for e in events))
 def test_weakening_volume_creates_observation_and_event_not_an_order(self):
  for i in range(4):
   at=self.now+timedelta(minutes=i);sample=tick(at,i,str(100+i));sample['volume']=str(400-100*i);result=self.put(sample,at)
  self.assertTrue(result['calculation']['supporting_metrics']['rising_price_falling_volume'])
  self.assertTrue(any(e['event_type']=='MOMENTUM_WEAKENING' for e in engine.history(app.connect,1,self.req['watch_id'],True,'events')['items']))
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_business_tables_reports_and_automation_unchanged(self):
  with app.connect() as c:before={r[0]:[tuple(x) for x in c.execute('SELECT * FROM "'+r[0]+'"')] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'hw_%'").fetchall()}
  self.put(tick(self.now));engine.kill(app.connect,1,True,'Synthetic test',self.now)
  with app.connect() as c:after={name:[tuple(x) for x in c.execute('SELECT * FROM "'+name+'"')] for name in before}
  self.assertEqual(before,after)

class EngineHTTP(unittest.TestCase):
 def setUp(self):
  import test_mcp_reports
  self.http=test_mcp_reports.McpReports();self.http.setUp();report_ingest.save(app.connect,1,merc_report(True));self.req=request();self.auth=self.http.login()
 def tearDown(self):self.http.tearDown()
 def test_session_auth_csrf_scoping_pagination_and_management(self):
  path='/api/v1/hotwatch/sessions';self.assertEqual(self.http.request(path,self.req)[0],401);self.assertEqual(self.http.request(path,self.req,{'Cookie':self.auth['Cookie']})[0],403);status,result,_=self.http.request(path,self.req,self.auth);self.assertEqual(status,201);wid=result['session']['watch_id'];self.assertEqual(self.http.request(path,self.req,self.auth)[0],200)
  self.assertEqual(self.http.request(path+'?is_test=false',None,self.auth)[1]['sessions'],[]);self.assertEqual(len(self.http.request(path+'?is_test=true',None,self.auth)[1]['sessions']),1);self.assertEqual(self.http.request(path+'?limit=101',None,self.auth)[0],400)
  for action,status in [('pause','PAUSED'),('resume','VALIDATING'),('stop','COMPLETED')]:self.assertEqual(self.http.request(path+'/'+wid+'/'+action,{'is_test':True},self.auth)[1]['session']['status'],status)
 def test_api_synthetic_feed_only_and_metadata_separation(self):
  self.http.request('/api/v1/hotwatch/sessions',self.req,self.auth);wid=self.req['watch_id'];t=tick(datetime.now(timezone.utc));path='/api/v1/hotwatch/sessions/'+wid+'/samples'
  self.assertEqual(self.http.request(path,t,self.auth)[0],403);self.assertEqual(self.http.request(path+'?is_test=true',t,self.auth)[0],200);self.assertEqual(len(self.http.request(path+'?is_test=true&order=desc',None,self.auth)[1]['items']),1)
  self.assertEqual(self.http.request('/api/reports/candidate-registry?is_test=false',None,self.auth)[1]['candidates'],[]);self.assertEqual(len(self.http.request('/api/reports/candidate-registry?is_test=true',None,self.auth)[1]['candidates']),12)
 def test_strategy_upload_validates_versions_and_deferred_actions_are_explicit(self):
  d=copy.deepcopy(BASELINE);d['version']='1.1.0';path='/api/v1/hotwatch/strategies';self.assertEqual(self.http.request(path,d,self.auth)[0],201);self.assertTrue(self.http.request(path+'/'+d['strategy_id']+'/'+d['version']+'/validate',{},self.auth)[1]['valid']);self.assertEqual(self.http.request(path+'/'+d['strategy_id']+'/'+d['version']+'/activate',{},self.auth)[0],501);self.assertFalse(self.http.request(path,None,self.auth)[1]['capabilities']['shadow'])
 def test_old_report_grants_cannot_manage_or_read_engine(self):
  _,token,_=self.http.granted();access=token['access_token'];result=self.http.call(access,'start_hot_watch',self.req)[1];self.assertIn('error',result);self.assertEqual(self.http.request('/api/v1/hotwatch/sessions',None,{'Authorization':'Bearer '+access})[0],403)
 def test_mcp_start_control_read_and_strategy_admin_scope(self):
  _,token,_=self.http.granted('reports:read reports:write hotwatch:read hotwatch:manage');access=token['access_token'];result=self.http.call(access,'start_hot_watch',self.req)[1]['result'];self.assertFalse(result['isError']);self.assertEqual(result['structuredContent']['session']['status'],'CREATED')
  read=self.http.call(access,'get_hot_watch_engine',{'is_test':True})[1]['result'];self.assertEqual(len(read['structuredContent']['sessions']),1);bad=self.http.call(access,'get_hot_watch_engine',{'limit':101})[1]['result'];self.assertTrue(bad['isError'])
  stopped=self.http.call(access,'control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'stop'})[1]['result'];self.assertFalse(stopped['isError']);self.assertEqual(stopped['structuredContent']['session']['status'],'COMPLETED')
  d=copy.deepcopy(BASELINE);d['version']='1.2.0';self.assertEqual(self.http.request('/api/v1/hotwatch/strategies',d,{'Authorization':'Bearer '+access})[0],403)
