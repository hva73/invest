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
 def test_sync_reads_sanitized_fallback_errors_through_existing_endpoint(self):
  import hotwatch_supervisor
  row={'created':self.now.isoformat(),'event':'site_portfolio_list','code':1}
  self.assertEqual(hotwatch_supervisor.application_error_fallback([row])['status'],'AVAILABLE')
  result=engine.sync(app.connect,1,True,session_limit=1,summary_only=True)
  self.assertEqual(result['application_error_fallback'],{'status':'AVAILABLE','events':[row]})
  self.assertEqual(result['open_sessions'][0]['last_computed_signal'],'NO_DATA')

 def test_status_uses_worker_interval_when_api_environment_differs(self):
  req=copy.deepcopy(self.req);req.update(watch_id='worker-interval',purpose='worker interval',provider='eodhd',provider_symbol='MERC.US',profile='ACTIVE')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':'5'},clear=True):
   engine.create(app.connect,1,req,self.now)
   sample=tick(self.now);sample.update(source='eodhd',interval_s=15)
   engine.ingest(app.connect,1,req['watch_id'],True,sample,self.now)
  with patch.dict(os.environ,{},clear=True),patch.object(engine,'effective_poll_interval',side_effect=AssertionError('API must not recalculate worker budget')):
   session=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertEqual(session['effective_min_interval_s'],15)
  self.assertEqual(session['interval_basis'],'worker_schedule')
  self.assertEqual((stamp(session['next_due_at'])-self.now).total_seconds(),15)
  self.assertEqual(session['request']['risk']['max_quote_age_s'],120)

 def test_fault_and_duplicate_release_update_the_reported_worker_schedule(self):
  engine.fault(app.connect,1,self.req['watch_id'],True,'PROCESSING_DATABASE_BUSY_ENGINE_793',self.now)
  item=engine.item(app.connect,1,self.req['watch_id'],True)['session']
  self.assertEqual(item['effective_min_interval_s'],60)
  later=self.now+timedelta(seconds=60);job=engine.claim(app.connect,later,self.req['watch_id'])
  engine.release(app.connect,job,later)
  with patch.object(engine,'effective_poll_interval',side_effect=AssertionError('not a worker')):
   item=engine.item(app.connect,1,self.req['watch_id'],True)['session']
  self.assertEqual(item['effective_min_interval_s'],(stamp(item['next_due_at'])-later).total_seconds())
  self.assertEqual(item['interval_basis'],'worker_schedule')
  self.assertEqual(item['signal'],'NO_DATA')

 def test_provider_pipeline_times_are_bounded_and_do_not_expose_other_fields(self):
  self.put(tick(self.now))
  values={'provider_ms':70000,'pluto_context_ms':62000,'websocket_capture_ms':2000,'adapter_to_journal_ms':7,'event_to_adapter_receive_ms':None,'secret':'not-for-client','begin_wait_ms':.3,'scope_entry_wait_ms':.1,'sqlite_begin_ms':.2}
  with app.connect() as c:
   c.execute('INSERT INTO hw_provider_health VALUES(?,?,?,?,?,?,?)',(1,1,'synthetic',self.now.isoformat(),self.now.isoformat(),None,json.dumps(values)))
  item=engine.sync(app.connect,1,True,session_limit=1,summary_only=True)['open_sessions'][0]
  diag=item['provider_feed_diagnostics']
  self.assertEqual(diag['last_successful_sqlite_timing_ms'],{k:values[k] for k in ('begin_wait_ms','scope_entry_wait_ms','sqlite_begin_ms')})
  self.assertEqual(diag['last_successful_pipeline_timing_ms'],{k:values[k] for k in ('provider_ms','pluto_context_ms','websocket_capture_ms','adapter_to_journal_ms')})
  self.assertEqual(diag['scope'],'provider_wide_not_session')
  self.assertNotIn('not-for-client',json.dumps(item))

 def test_reported_catalyst_priority_requires_evidence_and_expires(self):
  at=datetime(2026,11,9,8,0,tzinfo=timezone.utc)
  proposal={'strategy_id':'escape_early_catalyst','proposed_at':at.isoformat(),'news_check':{'status':'verified_news','checked_at':at.isoformat(),'source_ids':['news']},'catalyst':{'published_at':(at-timedelta(minutes=2)).isoformat(),'available_at':at.isoformat(),'source_ids':['news']}}
  self.assertIsNotNone(engine.reported_catalyst_priority_until({'strategy_proposal':proposal},at))
  self.assertIsNone(engine.reported_catalyst_priority_until({'strategy_proposal':proposal},at+timedelta(minutes=120)))
  bad=copy.deepcopy(proposal);bad['news_check']['source_ids']=['other']
  self.assertIsNone(engine.reported_catalyst_priority_until({'strategy_proposal':bad},at))
  bad=copy.deepcopy(proposal);bad['news_check']['status']='unknown'
  self.assertIsNone(engine.reported_catalyst_priority_until({'strategy_proposal':bad},at))
  bad=copy.deepcopy(proposal);bad['catalyst']['available_at']=(at+timedelta(seconds=1)).isoformat()
  self.assertIsNone(engine.reported_catalyst_priority_until({'strategy_proposal':bad},at))
 def setUp(self):
  self.old=app.DB;self.temp=tempfile.TemporaryDirectory();app.DB=self.temp.name+'/db';app.init();app.create_user('test-password-long-enough');self.now=datetime.now(timezone.utc).replace(microsecond=0);self.r=merc_report(True);report_ingest.save(app.connect,1,self.r);self.req=request();engine.create(app.connect,1,self.req,self.now)
 def tearDown(self):app.DB=self.old;self.temp.cleanup()
 def test_regular_close_uses_same_day_verified_exchange_calendar(self):
  from datetime import datetime,timezone
  cal={'open':'09:00:00','close':'17:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  received=datetime(2026,11,5,15,0,tzinfo=timezone.utc)
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('CO',received.isoformat(),'Europe/Copenhagen',json.dumps(cal)))
   closed=engine.scheduled_regular_close(c,'CO',datetime(2026,11,5,19,57,tzinfo=timezone.utc));self.assertEqual(closed['status'],'CLOSED')
   self.assertIsNone(engine.scheduled_regular_close(c,'CO',datetime(2026,11,5,15,30,tzinfo=timezone.utc)))
   self.assertIsNone(engine.scheduled_regular_close(c,'CO',datetime(2026,11,6,19,57,tzinfo=timezone.utc)))
   cal['excluded_dates']=['2026-11-05'];c.execute('UPDATE hw_exchange_calendar SET calendar=? WHERE exchange=?',(json.dumps(cal),'CO'))
   self.assertIsNone(engine.scheduled_regular_close(c,'CO',datetime(2026,11,5,19,57,tzinfo=timezone.utc)))
 def test_next_open_uses_current_calendar_and_never_guesses_premarket_or_holidays(self):
  at=datetime(2026,11,10,5,40,tzinfo=timezone.utc);req=dict(self.req,exchange='NASDAQ',provider='eodhd',provider_symbol='MERC.US')
  calendar={'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',at.isoformat(),'America/New_York',json.dumps(calendar)))
   result=engine.expected_regular_open(c,req,at);self.assertEqual(result['kind'],'REGULAR');self.assertEqual(result['expected_at'],'2026-11-10T14:30:00+00:00');self.assertFalse(result['execution_confirmed'])
   self.assertIsNone(engine.expected_regular_open(c,req,at+timedelta(hours=10)))
   calendar['excluded_dates']=['2026-11-10'];c.execute('UPDATE hw_exchange_calendar SET calendar=? WHERE exchange=?',(json.dumps(calendar),'US'));self.assertIsNone(engine.expected_regular_open(c,req,at))
   calendar['excluded_dates']=[];c.execute('UPDATE hw_exchange_calendar SET received=?,calendar=? WHERE exchange=?',((at-timedelta(days=1)).isoformat(),json.dumps(calendar),'US'));self.assertIsNone(engine.expected_regular_open(c,req,at))
   saturday=datetime(2026,11,14,12,0,tzinfo=timezone.utc);c.execute("UPDATE hw_exchange_calendar SET received=? WHERE exchange='US'",(saturday.isoformat(),))
   weekend=engine.expected_regular_open(c,req,saturday);self.assertEqual(weekend['expected_at'],'2026-11-16T14:30:00+00:00');self.assertFalse(weekend['same_day_copenhagen'])
   dst=datetime(2026,3,9,5,40,tzinfo=timezone.utc);c.execute("UPDATE hw_exchange_calendar SET received=? WHERE exchange='US'",(dst.isoformat(),))
   self.assertEqual(engine.expected_regular_open(c,req,dst)['expected_at'],'2026-03-09T13:30:00+00:00')
 def test_next_open_flows_from_engine_to_front_page_without_changing_signal(self):
  import dashboard_projection
  at=datetime(2026,11,10,5,40,tzinfo=timezone.utc);calendar={'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone();req=json.loads(row['request']);req.update(provider='pluto',exchange='NASDAQ',report_id='manual-pluto')
   c.execute('UPDATE hw_sessions SET is_test=0,request=? WHERE id=?',(json.dumps(req),row['id']));c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',at.isoformat(),'America/New_York',json.dumps(calendar)))
   row=c.execute('SELECT * FROM hw_sessions WHERE id=?',(row['id'],)).fetchone()
   with patch('hotwatch_engine.utc',return_value=at):
    session=engine.view(c,row);front=dashboard_projection.position_hotwatch(c,1,1,req['asset_id'],None)['session']
   self.assertEqual(session['signal'],'NO_DATA');self.assertEqual(front['signal'],'NO_DATA');self.assertEqual(front['next_market_session'],session['data_status']['next_market_session']);self.assertEqual(front['next_market_session']['expected_at'],'2026-11-10T14:30:00+00:00')
   pre=at+timedelta(hours=7);c.execute('UPDATE hw_exchange_calendar SET received=? WHERE exchange=?',(pre.isoformat(),'US'))
   quality=observation_status([],pre,120,'NO_DATA','CREATED');quality['market_status']='PREMARKET'
   with patch('hotwatch_engine.utc',return_value=pre),patch('hotwatch_engine.observation_status',return_value=quality):session=engine.view(c,row)
   self.assertEqual(session['signal'],'NO_DATA');self.assertEqual(session['data_status']['next_market_session']['expected_at'],'2026-11-10T14:30:00+00:00')
 def test_closed_market_without_other_errors_is_a_normal_active_session(self):
  sample=tick(self.now,held=True);sample.update(market_status='CLOSED',session_key='SYNTHETIC-CLOSED')
  result=engine.ingest(app.connect,1,self.req['watch_id'],True,sample,self.now)
  self.assertEqual(result['calculation']['signal'],'PAUSE')
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone()['status'],'ACTIVE')
 def test_novob_shows_closed_regular_session_even_when_quote_is_old(self):
  cal={'open':'09:00:00','close':'17:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  at=datetime(2026,11,5,19,57,tzinfo=timezone.utc)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='NOVO-B.CO')
   c.execute('UPDATE hw_sessions SET is_test=0,request=? WHERE id=?',(json.dumps(req),row['id']))
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('CO','2026-11-05T15:00:00+00:00','Europe/Copenhagen',json.dumps(cal)))
   row=c.execute('SELECT * FROM hw_sessions WHERE id=?',(row['id'],)).fetchone();result=engine.view(c,row,at)
  self.assertEqual(result['data_status']['regular_session']['status'],'CLOSED');self.assertEqual(result['display_status'],'MARKED LUKKET (ORDINÆR HANDEL)');self.assertTrue(result['data_stale'])
 def test_manual_pluto_search_creates_one_non_report_watch(self):
  import hotwatch_service as service
  asset={'id':'manual-asset','ticker':'ABC','exchange':'NASDAQ','currency':'USD','name':'ABC Company'}
  def call(client,tools,name,data):return [{'id':'manual-asset','ticker':'ABC'}] if name=='search_assets' else {'asset':asset}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=call),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'0'}):
   result=service.start_manual_pluto(app.connect,1,{'asset_id':'manual-asset','ticker':'ABC'});again=service.start_manual_pluto(app.connect,1,{'asset_id':'manual-asset','ticker':'ABC'})
  self.assertFalse(result['duplicate']);self.assertTrue(again['duplicate']);self.assertEqual(result['session']['watch_id'],again['session']['watch_id']);self.assertEqual(result['session']['request']['report_id'],'manual-pluto')
  self.assertEqual(engine.reconcile_candidates(app.connect,self.now+timedelta(days=10)),0)
 def put(self,data,now=None):return engine.ingest(app.connect,1,self.req['watch_id'],True,data,now or self.now)
 def counts(self):
  with app.connect() as c:return {name:c.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ['hw_sessions','hw_samples','hw_calculations','hw_events']}
 def test_read_only_summary_exposes_calculation_schedule_and_labels_provider_wide_feed(self):
  self.put(tick(self.now))
  with app.connect() as c:
   c.execute('INSERT INTO hw_provider_health VALUES(?,?,?,?,?,?,?)',(1,1,'synthetic',self.now.isoformat(),self.now.isoformat(),'EXAMPLE_ERROR',json.dumps({'websocket_trade_status':'OK','secret':'must-not-escape'})))
  result=engine.sync(app.connect,1,True,session_limit=1,summary_only=True);item=result['open_sessions'][0]
  self.assertEqual(item['last_calculation_at'],self.now.isoformat());self.assertTrue(item['next_due_at']);self.assertGreaterEqual(item['effective_min_interval_s'],1)
  self.assertIsInstance(item['last_calculation_reason_codes'],list);self.assertIsInstance(item['display_reason_codes'],list)
  diag=item['provider_feed_diagnostics'];self.assertEqual(diag['scope'],'provider_wide_not_session');self.assertEqual(diag['last_successful_feed_statuses']['websocket_trade_status'],'OK')
  self.assertEqual(diag['last_error'],'EXAMPLE_ERROR');self.assertNotIn('must-not-escape',json.dumps(item));self.assertNotIn('request',item)
  self.assertEqual(engine.sync(app.connect,2,True,summary_only=True)['open_sessions'],[])
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
 def test_exchange_status_separates_closed_regular_hours_from_extended_trading(self):
  self.put(tick(self.now))
  with app.connect() as c:
   row=c.execute('SELECT id,request FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='MERC.US')
   c.execute('UPDATE hw_sessions SET is_test=0,request=? WHERE id=?',(json.dumps(req),row['id']))
   c.execute('INSERT INTO hw_exchange_status VALUES(?,?,?,?)',('US',(self.now+timedelta(seconds=121)).isoformat(),0,self.now.timestamp()+421))
   view=engine.view(c,engine.row_for(c,1,self.req['watch_id'],False),self.now+timedelta(seconds=121))
   self.assertEqual(view['display_status'],'MARKED LUKKET (ORDINÆR HANDEL)');self.assertEqual(view['data_status']['regular_session']['status'],'CLOSED');self.assertTrue(view['data_stale'])
   data=json.loads(c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=?',(row['id'],)).fetchone()[0]);data.update(market_status='PRE',status_at=self.now.isoformat());c.execute('UPDATE hw_samples SET payload=? WHERE watch_row_id=?',(json.dumps(data),row['id']))
   view=engine.view(c,engine.row_for(c,1,self.req['watch_id'],False),self.now+timedelta(seconds=121))
   self.assertEqual(view['data_status']['market_status'],'UNKNOWN')
   c.execute('UPDATE hw_exchange_status SET received=? WHERE exchange=?',(self.now.isoformat(),'US'))
   view=engine.view(c,engine.row_for(c,1,self.req['watch_id'],False),self.now+timedelta(seconds=301))
   self.assertEqual(view['data_status']['regular_session']['status'],'UNKNOWN');self.assertEqual(view['display_status'],'DATA FOR GAMLE')
   c.execute('UPDATE hw_exchange_status SET received=? WHERE exchange=?',(self.now.isoformat(),'US'))
   view=engine.view(c,engine.row_for(c,1,self.req['watch_id'],False),self.now+timedelta(seconds=60))
   self.assertEqual(view['data_status']['market_status'],'PREMARKET');self.assertNotEqual(view['display_status'],'MARKED LUKKET (ORDINÆR HANDEL)')
   data.update(market_status='REGULAR',status_at=self.now.isoformat());c.execute('UPDATE hw_samples SET payload=? WHERE watch_row_id=?',(json.dumps(data),row['id']))
   c.execute('UPDATE hw_exchange_status SET received=? WHERE exchange=?',((self.now-timedelta(seconds=1)).isoformat(),'US'))
   view=engine.view(c,engine.row_for(c,1,self.req['watch_id'],False),self.now+timedelta(seconds=1))
   self.assertEqual(view['data_status']['regular_session']['status'],'UNKNOWN');self.assertNotEqual(view['display_status'],'MARKED LUKKET (ORDINÆR HANDEL)')
   c.execute('UPDATE hw_exchange_status SET received=? WHERE exchange=?',((self.now+timedelta(seconds=1)).isoformat(),'US'))
   view=engine.view(c,engine.row_for(c,1,self.req['watch_id'],False),self.now+timedelta(seconds=2))
   self.assertEqual(view['data_status']['market_status'],'UNKNOWN');self.assertEqual(view['display_status'],'MARKED LUKKET (ORDINÆR HANDEL)')
 def test_closed_market_unknown_access_is_reduced_without_suppressing_us_extended_hours(self):
  at=datetime(2026,11,10,6,0,tzinfo=timezone.utc)
  req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US')
  schedule={'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',at.isoformat(),'America/New_York',json.dumps(schedule)))
   self.assertEqual(engine.quiet_market_interval(c,req,'NORMAL',at,60),120)
   self.assertEqual(engine.quiet_market_interval(c,req,'CRITICAL',at,60),60)
   self.assertEqual(engine.quiet_market_interval(c,req,'NORMAL',at,60,{'market_status':'AFTER'}),60)
   pre=at+timedelta(hours=4)
   self.assertEqual(engine.quiet_market_interval(c,req,'NORMAL',pre,60),60)
   pre=at+timedelta(hours=2,minutes=58)
   self.assertEqual(engine.quiet_market_interval(c,req,'NORMAL',pre,60),60)
   next_day=at+timedelta(days=1);self.assertEqual(engine.quiet_market_interval(c,req,'NORMAL',next_day,60),60)
   schedule['excluded_dates']=['2026-11-10'];c.execute('UPDATE hw_exchange_calendar SET calendar=? WHERE exchange=?',(json.dumps(schedule),'US'))
   self.assertEqual(engine.quiet_market_interval(c,req,'NORMAL',at,60),60)
 def test_installed_revision_is_reported_only_from_valid_build_metadata(self):
  fake='a'*40
  with patch.dict(os.environ,{'ESCAPE_BUILD_COMMIT':fake}):self.assertEqual(engine.installed_revision(),{'commit':fake,'source':'ESCAPE_BUILD_COMMIT'})
  with patch.dict(os.environ,{'ESCAPE_BUILD_COMMIT':'not-a-hash'}):self.assertIsNone(engine.installed_revision()['commit'])
 def test_observation_requires_fresh_comparable_verified_data_and_never_approves_risk(self):
  data={'price_status':'FRESH','momentum_status':'READY','market_status':'PREMARKET','momentum_pct':{'5':'1.2'},'event_time':self.now.isoformat(),'source':'eodhd'}
  obs=engine.market_observation(data,'DEGRADED',True)
  self.assertEqual(obs['kind'],'RISING');self.assertEqual(obs['change_pct'],'1.2');self.assertFalse(obs['risk_approved'])
  for changes in ({'price_status':'STALE'},{'momentum_status':'INSUFFICIENT_HISTORY'},{'market_status':'UNKNOWN'},{'market_status':'HALTED'},{'momentum_pct':{'5':'-2'}}):
   self.assertIsNone(engine.market_observation(dict(data,**changes),'ACTIVE',True))
  self.assertIsNone(engine.market_observation(data,'PAUSED',True));self.assertIsNone(engine.market_observation(data,'ACTIVE',False))
 def test_daily_budget_still_retries_on_normal_cadence_for_websocket_events(self):
  req=copy.deepcopy(self.req);req.update(watch_id='daily-budget-watch',purpose='daily budget watch',provider='eodhd',provider_symbol='MERC.US')
  engine.create(app.connect,1,req,self.now)
  for i in range(7):engine.fault(app.connect,1,req['watch_id'],True,'EODHD_DAILY_BUDGET',self.now+timedelta(seconds=i))
  with app.connect() as c:
   row=engine.row_for(c,1,req['watch_id'],True);interval=engine.effective_poll_interval(c,req)
   self.assertEqual(row['last_error'],'EODHD_DAILY_BUDGET');self.assertAlmostEqual(row['next_due'],(self.now+timedelta(seconds=6+interval)).timestamp())
 def test_exchange_status_refresh_does_not_starve_later_exchange(self):
  import hotwatch_service as service
  second=copy.deepcopy(self.req);second.update(watch_id='other-exchange',purpose='other exchange')
  engine.create(app.connect,1,second,self.now)
  with app.connect() as c:
   for wid,symbol in ((self.req['watch_id'],'MERC.CO'),(second['watch_id'],'LHA.XETRA')):
    row=c.execute('SELECT id,request FROM hw_sessions WHERE watch_id=?',(wid,)).fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol=symbol)
    c.execute('UPDATE hw_sessions SET is_test=0,request=? WHERE id=?',(json.dumps(req),row['id']))
  calls=[]
  class Client:
   def market_status(client,exchange):
    calls.append(exchange);return {'status':'OK','exchange':exchange,'exchange_open':False,'received_at':engine.utc().isoformat(),'timezone':'Europe/Berlin','calendar':{'open':'09:00:00','close':'17:30:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}):
   for at in (self.now,self.now+timedelta(seconds=75)):
    with patch('hotwatch_engine.utc',return_value=at):self.assertEqual(service.exchange_status_tick(app.connect,lambda:Client(),at),'OK')
  self.assertEqual(calls,['CO','XETRA'])
  with app.connect() as c:self.assertIsNotNone(c.execute("SELECT received FROM hw_exchange_calendar WHERE exchange='XETRA'").fetchone())
 def test_exchange_status_refresh_is_cached_and_failed_read_does_not_refresh_old_evidence(self):
  import hotwatch_service as service
  with app.connect() as c:
   row=c.execute('SELECT id,request FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='MERC.CO')
   c.execute('UPDATE hw_sessions SET is_test=0,request=? WHERE id=?',(json.dumps(req),row['id']))
  calls=[]
  class Client:
   def market_status(client,exchange):
    calls.append(exchange);return {'status':'OK','exchange':exchange,'exchange_open':False,'received_at':self.now.isoformat(),'timezone':'Europe/Copenhagen','calendar':{'open':'09:00:00','close':'17:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_engine.utc',return_value=self.now):
   self.assertEqual(service.exchange_status_tick(app.connect,lambda:Client(),self.now),'OK')
   self.assertIsNone(service.exchange_status_tick(app.connect,lambda:Client(),self.now+timedelta(seconds=1)))
  self.assertEqual(calls,['CO'])
  with app.connect() as c:self.assertIsNotNone(c.execute("SELECT received FROM hw_exchange_calendar WHERE exchange='CO'").fetchone())
  class Failed:
   def market_status(client,exchange):return {'status':'LOCAL_BUDGET_EXHAUSTED'}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}):self.assertEqual(service.exchange_status_tick(app.connect,lambda:Failed(),self.now+timedelta(seconds=301)),'LOCAL_BUDGET_EXHAUSTED')
  with app.connect() as c:
   row=c.execute("SELECT received,is_open FROM hw_exchange_status WHERE exchange='CO'").fetchone();self.assertEqual(row['received'],self.now.isoformat());self.assertEqual(row['is_open'],0)
 def test_exchange_status_idle_does_not_request_writer_lock(self):
  import sqlite3,hotwatch_service as service
  holder=app.connect()
  def quick_connect():
   c=sqlite3.connect(app.DB,timeout=0);c.row_factory=sqlite3.Row;return c
  try:
   holder.execute('BEGIN IMMEDIATE')
   with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}):
    self.assertIsNone(service.exchange_status_tick(quick_connect,now=self.now))
  finally:holder.rollback();holder.close()
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
 def test_verified_and_provisional_observations_never_share_history(self):
  first=tick(self.now-timedelta(minutes=1),0,'100');last=tick(self.now,1,'101')
  first['verification']='unverified'
  self.assertEqual(features([first,last],BASELINE['parameters'])['sample_count'],1)
  self.assertIsNone(observation_status([first,last],self.now,120,'NO_DATA','DEGRADED')['since_last_pct'])
  first['verification']='verified';last['verification']='unverified'
  self.assertEqual(features([first,last],BASELINE['parameters'])['sample_count'],1)
  self.assertEqual(observation_status([first,last],self.now,120,'NO_DATA','DEGRADED')['price_status'],'UNVERIFIED')
  del first['verification'];last['verification']='verified'
  self.assertEqual(features([first,last],BASELINE['parameters'])['sample_count'],1)
  self.assertEqual(observation_status([first],self.now,120,'NO_DATA','DEGRADED')['price_status'],'UNVERIFIED')
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
 def test_dashboard_warmup_counts_actual_observations_and_does_not_hide_stale_data(self):
  import dashboard_projection
  self.put(tick(self.now))
  with app.connect() as c:c.execute('UPDATE hw_sessions SET is_test=0')
  with patch('hotwatch_engine.utc',return_value=self.now):
   with app.connect() as c:view=dashboard_projection.position_hotwatch(c,1,123,self.req['asset_id'],None)
  self.assertEqual(view['session']['warmup'],{'count':1,'required':34,'remaining':33,'historical':True})
  self.assertEqual(view['session']['display_status'],'AFVENTER SIGNALDATA')
  with patch('hotwatch_engine.utc',return_value=self.now+timedelta(seconds=121)):
   with app.connect() as c:view=dashboard_projection.position_hotwatch(c,1,123,self.req['asset_id'],None)
  self.assertEqual(view['session']['warmup'],{'count':1,'required':34,'remaining':33,'historical':True});self.assertNotEqual(view['session']['display_status'],'WARMUP')
 def test_start_candidates_omits_open_watches_by_candidate_and_verified_asset(self):
  base=self.req['candidate_id'];asset=self.req['asset_id']
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET is_test=0')
   c.execute('INSERT INTO market_asset_links VALUES(?,?,?,?)',(1,'linked-id','LINKED',asset))
  entries=[{'candidate':{'candidate_id':base,'ticker':'MERC'},'report_id':'r'}, {'candidate':{'candidate_id':'same-asset','ticker':'OTHER','asset_id':asset},'report_id':'r'}, {'candidate':{'candidate_id':'linked-id','ticker':'LINKED'},'report_id':'r'}, {'candidate':{'candidate_id':'different-asset','ticker':'MERC','asset_id':'other'},'report_id':'r'}, {'candidate':{'candidate_id':'unknown-asset','ticker':'MERC'},'report_id':'r'}]
  for item in entries:item['candidate']['decision']={'status':'AFVENT','decided_at':self.now.isoformat(),'deadline':(self.now+timedelta(hours=1)).isoformat()}
  with patch('report_ingest.desk',return_value={'candidates':entries}):
   result=engine.start_candidates(app.connect,1,False)
   self.assertEqual([x['candidate']['candidate_id'] for x in result['candidates']],['different-asset','unknown-asset']);self.assertEqual(result['already_watched'],3)
   self.assertEqual(len(engine.start_candidates(app.connect,2,False)['candidates']),5)
   with app.connect() as c:c.execute("UPDATE hw_sessions SET status='PAUSED'")
   self.assertEqual(engine.start_candidates(app.connect,1,False)['already_watched'],3)
   with app.connect() as c:c.execute("UPDATE hw_sessions SET status='COMPLETED'")
   self.assertEqual(len(engine.start_candidates(app.connect,1,False)['candidates']),4)
 def test_start_candidates_omits_unassessed_expired_and_verified_duplicates(self):
  decision={'status':'AFVENT','decided_at':self.now.isoformat(),'deadline':(self.now+timedelta(hours=1)).isoformat()}
  entries=[{'candidate':{'candidate_id':'one','ticker':'ABC','asset_id':'asset-one','decision':decision}}, {'candidate':{'candidate_id':'duplicate','ticker':'ABC','asset_id':'asset-one','decision':decision}}, {'candidate':{'candidate_id':'different','ticker':'ABC','asset_id':'asset-two','decision':decision}}, {'candidate':{'candidate_id':'unknown','ticker':'ABC'}}, {'candidate':{'candidate_id':'expired','ticker':'ABC','decision':dict(decision,deadline=(self.now-timedelta(seconds=1)).isoformat())}}]
  with patch('report_ingest.desk',return_value={'candidates':entries}):
   result=engine.start_candidates(app.connect,1,False)
   self.assertEqual([x['candidate']['candidate_id'] for x in result['candidates']],['one','different'])
   self.assertEqual(result['duplicates'],1);self.assertEqual(result['without_current_assessment'],2)
 def test_unresolved_duplicates_require_same_ticker_exchange_and_name(self):
  decision={'status':'AFVENT','decided_at':self.now.isoformat(),'deadline':(self.now+timedelta(hours=1)).isoformat()}
  def row(cid,exchange):return {'candidate':{'candidate_id':cid,'ticker':'BTC','exchange':exchange,'company_name':'Bitcoin','decision':decision}}
  with patch('report_ingest.desk',return_value={'candidates':[row('a','XONE'),row('b','XONE'),row('c','XTWO')]}):
   result=engine.start_candidates(app.connect,1,False)
   self.assertEqual([x['candidate']['candidate_id'] for x in result['candidates']],['a','c']);self.assertEqual(result['duplicates'],1)
 def test_start_candidates_respects_test_partition(self):
  result=engine.start_candidates(app.connect,1,True)
  self.assertEqual(result['already_watched'],1);self.assertNotIn(self.req['candidate_id'],[x['candidate']['candidate_id'] for x in result['candidates']])
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
 def test_sixty_session_default_and_claim_only_charges_real_adapter_requests(self):
  with patch.dict(os.environ,{},clear=True):self.assertEqual(engine.capacity(),60)
  job=engine.claim(app.connect,self.now)
  self.assertIsNotNone(job)
  with app.connect() as c:self.assertEqual(c.execute('SELECT COALESCE(sum(used),0) FROM hw_request_budget').fetchone()[0],0)
 def test_capacity_supports_60_sessions_and_rejects_61st(self):
  with patch.dict(os.environ,{},clear=True):
   for i in range(1,60):
    item=copy.deepcopy(self.req);item.update(watch_id='capacity-watch-'+str(i),purpose='capacity '+str(i));engine.create(app.connect,1,item,self.now)
   with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],60)
   item=copy.deepcopy(self.req);item.update(watch_id='capacity-watch-over',purpose='capacity overflow')
   with self.assertRaisesRegex(EngineError,'global_capacity_limit'):engine.create(app.connect,1,item,self.now)
 def test_many_provisional_sessions_use_honest_budget_aware_cadence(self):
  settings={'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'1'}
  with patch.dict(os.environ,settings,clear=True):
   for index in range(24):
    item=copy.deepcopy(self.req);item.update(watch_id='budget-provisional-'+str(index),purpose='budget '+str(index),provider='eodhd',provider_symbol='MERC.US')
    engine.create(app.connect,1,item,self.now)
    with app.connect() as c:
     row=c.execute('SELECT id FROM hw_sessions WHERE watch_id=?',(item['watch_id'],)).fetchone()
     c.execute('INSERT INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],'MERC.US','{}',self.now.isoformat()))
   with app.connect() as c:
    self.assertEqual(engine.effective_poll_interval(c,item),60)
   sample=tick(self.now);sample.update(source='eodhd',market_status='UNKNOWN',session_key='test:UNKNOWN',feed_type='synthetic EODHD snapshot',bid=None,ask=None,interval_s=60)
   result=engine.ingest(app.connect,1,item['watch_id'],True,sample,self.now)
   self.assertEqual(result['session']['effective_min_interval_s'],60)
   with app.connect() as c:
    due=c.execute('SELECT next_due FROM hw_sessions WHERE watch_id=?',(item['watch_id'],)).fetchone()['next_due']
   self.assertEqual(due-self.now.timestamp(),60)
   verified=copy.deepcopy(self.req);verified.update(watch_id='budget-verified',purpose='verified budget',provider='eodhd',provider_symbol='MERC.US')
   engine.create(app.connect,1,verified,self.now)
   with app.connect() as c:self.assertEqual(engine.effective_poll_interval(c,verified),60)
 def test_fast_eodhd_polling_is_explicit_bounded_and_budgeted(self):
  from hotwatch_contract import provider_floor
  from hotwatch_adapters import providers
  with patch.dict(os.environ,{},clear=True):
   self.assertEqual(provider_floor('eodhd'),300);self.assertEqual(providers()['eodhd']['minimum_poll_s'],300)
  for setting in ['4','301','broken','-1']:
   with self.subTest(setting=setting),patch.dict(os.environ,{'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':setting}):self.assertEqual(provider_floor('eodhd'),300)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':'5','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'1'}):
   self.assertEqual(provider_floor('eodhd'),5);self.assertEqual(providers()['eodhd']['minimum_poll_s'],5);self.assertEqual(provider_floor('pluto'),300)
   reserve(app.connect,1,'eodhd',self.now)
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now)
 def test_btc_and_many_stocks_share_budget_without_aging_btc(self):
  settings={'ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'30','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'1'}
  with patch.dict(os.environ,settings,clear=True):
   for i in range(16):
    stock=copy.deepcopy(self.req);stock.update(watch_id='stock-'+str(i),purpose='stock '+str(i),provider='eodhd',provider_symbol='MERC.US');engine.create(app.connect,1,stock,self.now)
   for i in range(2):
    btc=copy.deepcopy(self.req);btc.update(watch_id='btc-'+str(i),purpose='btc fixture '+str(i),provider='eodhd',provider_symbol='BTC-USD.CC');engine.create(app.connect,1,btc,self.now)
    btc.update(purpose='automatic holding watch',asset_id='54368e0b-2d53-401e-bf68-1033a5b84b08',ticker='BTC')
    with app.connect() as c:c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(btc),btc['watch_id']))
   with app.connect() as c:
    btc_interval=engine.effective_poll_interval(c,btc);stock_interval=engine.effective_poll_interval(c,stock)
   self.assertEqual(btc_interval,60);self.assertEqual(stock_interval,60)
   self.assertLessEqual(60/btc_interval+60/stock_interval,30) # identical symbols share raw observations
   with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'1'}):
    with app.connect() as c:self.assertEqual(engine.effective_poll_interval(c,btc),120)
 def test_live_poll_budget_accounts_for_shared_stream_schedule_and_conditional_rest(self):
  with app.connect() as c:
   base=dict(engine.row_for(c,1,self.req['watch_id'],True));base.pop('id')
   for i,symbol in enumerate(['MSFT.US','HIMS.US','FLY.US','LUNR.US','BRK-B.US']):
    item=dict(base);item.update(watch_id='poll-batch-'+str(i),candidate_id='poll-candidate-'+str(i),is_test=0)
    req=json.loads(item['request']);req.update(watch_id=item['watch_id'],candidate_id=item['candidate_id'],provider='eodhd',provider_symbol=symbol,is_test=False,profile='ACTIVE');item['request']=json.dumps(req)
    cols=list(item);c.execute('INSERT INTO hw_sessions('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',[item[k] for k in cols])
  settings={'ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'10','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'1','ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'1','ESCAPE_HW_EODHD_MIN_POLL_S':'5'}
  with patch.dict(os.environ,settings,clear=True):
   with app.connect() as c:self.assertEqual(engine.effective_poll_interval(c,req),(5*60+8)//9)
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
   self.assertEqual(provider_floor('eodhd'),5)
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
 def test_parallel_scan_setting_defaults_to_two_and_caps_at_leases(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  runner=Runner(app.connect)
  with patch.dict(os.environ,{},clear=True),patch.object(Runner,'once',return_value=False) as once:
   self.assertEqual(runner.drain(),0);self.assertEqual(once.call_count,2)
  with patch.dict(os.environ,{'ESCAPE_HW_PARALLEL_SCANS':'6','ESCAPE_HW_CONCURRENCY':'1'}),patch.object(Runner,'once',return_value=False) as once:
   self.assertEqual(runner.drain(),0);self.assertEqual(once.call_count,1)
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
 def test_verified_context_after_unknown_timestamp_does_not_crash_or_accept_older_evidence(self):
  ctx=tick(self.now,held=True)['context']
  with app.connect() as c:
   row=c.execute('SELECT id FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone()
   c.execute('INSERT INTO hw_context_events(watch_row_id,sample_row_id,observed,payload) VALUES(?,NULL,?,?)',(row['id'],self.now.isoformat(),json.dumps(unknown_context())))
  engine.observe_context(app.connect,1,self.req['watch_id'],True,ctx,self.now)
  older=dict(ctx,as_of=(self.now-timedelta(seconds=1)).isoformat())
  with self.assertRaisesRegex(EngineError,'out_of_order_position_context'):engine.observe_context(app.connect,1,self.req['watch_id'],True,older,self.now)
  with app.connect() as c:
   c.execute('INSERT INTO hw_context_events(watch_row_id,sample_row_id,observed,payload) VALUES(?,NULL,?,?)',(row['id'],self.now.isoformat(),json.dumps({'as_of':'not-a-date'})))
  with self.assertRaisesRegex(EngineError,'invalid_previous_position_context'):engine.observe_context(app.connect,1,self.req['watch_id'],True,ctx,self.now)
  self.assertEqual(self.counts()['hw_samples'],0)
 def test_runner_journals_broker_context_when_quote_time_is_unavailable(self):
  from hotwatch_service import Runner
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  r=copy.deepcopy(self.req);r.update(watch_id='broker-no-quote',purpose='broker-context-test',provider='pluto');engine.create(app.connect,1,r,self.now)
  with app.connect() as c:
   row=c.execute('SELECT id FROM hw_sessions WHERE watch_id=?',(r['watch_id'],)).fetchone()
   c.execute('INSERT INTO hw_context_events(watch_row_id,sample_row_id,observed,payload) VALUES(?,NULL,?,?)',(row['id'],self.now.isoformat(),json.dumps(unknown_context())))
  error=DataUnavailable('PLUTO_QUOTE_TIME_UNKNOWN');error.position_context=tick(self.now,held=True)['context']
  from unittest.mock import Mock
  adapter=Mock();adapter.poll.side_effect=error;runner=Runner(app.connect);runner.adapters[(1,'pluto')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now))
  view=engine.item(app.connect,1,r['watch_id'],True)['session'];self.assertEqual(view['status'],'DEGRADED');self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['last_data_at']);self.assertEqual(view['latest_context']['quantity'],'10')
  self.assertEqual(self.counts()['hw_samples'],0)
 def test_untimed_price_is_journalled_but_cannot_create_a_signal(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='untimed-price',purpose='untimed observation',provider='pluto');engine.create(app.connect,1,req,self.now)
  error=DataUnavailable('PLUTO_QUOTE_TIME_UNKNOWN');error.partial_observation={'source':'pluto','price':'12.34','currency':'USD','source_time':None,'received_at':self.now.isoformat(),'quality':'TIME_UNKNOWN'}
  adapter=Mock();adapter.poll.side_effect=error;runner=Runner(app.connect);runner.adapters[(1,'pluto')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  view=engine.item(app.connect,1,req['watch_id'],True)['session'];self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(view['display_status'],'KURSTID MANGLER');self.assertIsNone(view['last_data_at']);self.assertEqual(self.counts()['hw_samples'],0)
  events=engine.history(app.connect,1,req['watch_id'],True)['items'];observed=[x for x in events if x['event_type']=='PARTIAL_MARKET_OBSERVATION']
  self.assertEqual(len(observed),1);self.assertIsNone(observed[0]['data_timestamp']);self.assertEqual(observed[0]['data']['supporting_metrics']['price'],'12.34')
  self.assertFalse(engine.record_partial_observation(app.connect,1,req['watch_id'],True,error.partial_observation,self.now))
  with self.assertRaises(EngineError):engine.record_partial_observation(app.connect,1,req['watch_id'],True,dict(error.partial_observation,currency='EUR'),self.now)
 def test_fresh_partial_quote_is_visible_without_becoming_a_trade_or_signal(self):
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='quote-no-trade',purpose='quote only test',provider='eodhd',provider_symbol='MERC.US');engine.create(app.connect,1,req,self.now)
  quote={'source':'eodhd','price':None,'bid':'12.30','ask':'12.40','currency':'USD','source_time':self.now.isoformat(),'received_at':self.now.isoformat(),'quality':'TRADE_MISSING'}
  self.assertTrue(engine.record_partial_observation(app.connect,1,req['watch_id'],True,quote,self.now))
  with patch('hotwatch_engine.utc',return_value=self.now):view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['last_data_at'])
  self.assertEqual(view['data_status']['partial_quote']['bid'],'12.30')
  self.assertEqual(view['data_status']['partial_quote']['source_time'],self.now.isoformat())
  with patch('hotwatch_engine.utc',return_value=self.now+timedelta(hours=1)):old=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertNotIn('partial_quote',old['data_status']);self.assertEqual(old['signal'],'NO_DATA')
 def test_scan_reuses_only_fresh_same_response_exchange_evidence(self):
  from unittest.mock import Mock
  adapter=EODHDAdapter(app.connect,1);client=Mock();client.market_status.return_value={'status':'LOCAL_BUDGET_EXHAUSTED'}
  calendar={'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  observed=self.now-timedelta(seconds=30)
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_status(exchange,received,is_open,next_attempt) VALUES(?,?,?,?)',('US',observed.isoformat(),0,0))
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',observed.isoformat(),'America/New_York',json.dumps(calendar)))
  with patch('hotwatch_adapters.utc',return_value=self.now):
   result=adapter.market_status(client,'US',120)
   self.assertEqual(result['received_at'],observed.isoformat());self.assertIs(result['exchange_open'],False)
   client.market_status.assert_not_called()
   with app.connect() as c:c.execute('UPDATE hw_exchange_calendar SET received=? WHERE exchange=?',(self.now.isoformat(),'US'))
   self.assertEqual(adapter.market_status(client,'US',120)['status'],'LOCAL_BUDGET_EXHAUSTED')
   with app.connect() as c:c.execute('UPDATE hw_exchange_calendar SET received=? WHERE exchange=?',(observed.isoformat(),'US'))
  with patch('hotwatch_adapters.utc',return_value=self.now+timedelta(seconds=91)):
   self.assertEqual(adapter.market_status(client,'US',120)['status'],'LOCAL_BUDGET_EXHAUSTED')
  with patch('hotwatch_adapters.utc',return_value=observed-timedelta(seconds=1)):
   self.assertEqual(adapter.market_status(client,'US',120)['status'],'LOCAL_BUDGET_EXHAUSTED')
 def test_premarket_trade_uses_shared_exchange_evidence_when_http_budget_is_blocked(self):
  from unittest.mock import Mock
  now=datetime(2026,11,10,13,0,tzinfo=timezone.utc);observed=now-timedelta(seconds=20)
  calendar={'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_status(exchange,received,is_open,next_attempt) VALUES(?,?,?,?)',('US',observed.isoformat(),0,0))
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',observed.isoformat(),'America/New_York',json.dumps(calendar)))
  req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US')
  feed=Mock();feed.market_status.return_value={'status':'LOCAL_BUDGET_EXHAUSTED'}
  feed.capture.side_effect=lambda kind,*args,**kwargs: {'status':'OK','messages':[{'event_time':now.isoformat(),'price':'100','trade_size':'2','market_session':'extended-hours'}]} if kind=='us_trades' else {'status':'OK','messages':[{'event_time':now.isoformat(),'bid':'99','ask':'101'}]} if kind=='us_quotes' else {'status':'NO_MESSAGES','messages':[]}
  adapter=EODHDAdapter(app.connect,1,opener=object())
  env={'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}
  with patch.dict(os.environ,env),patch('hotwatch_adapters.utc',return_value=now),patch.object(adapter,'feeds',return_value=feed),patch.object(adapter.pluto,'safe_context',return_value=unknown_context()):
   sample=adapter.poll({'request_data':req})
  self.assertEqual(sample['market_status'],'PRE');self.assertEqual(sample['event_time'],now.isoformat())
  self.assertEqual(sample['status_at'],now.isoformat());self.assertEqual(sample['context']['status'],'unknown')
  feed.market_status.assert_not_called()
 def test_quote_is_preserved_when_trade_status_expires_during_collection(self):
  from unittest.mock import Mock
  from hotwatch_service import Runner
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='quote-stale-phase',purpose='quote evidence',provider='eodhd',provider_symbol='MERC.US');engine.create(app.connect,1,req,self.now)
  sample=tick(self.now-timedelta(seconds=119));sample.update(source='eodhd',feed_type='EODHD WS trade',price_time_kind='trade',market_status='AFTER',status_feed='us_trades',status_at=(self.now-timedelta(seconds=121)).isoformat(),quote_feed='us_quotes',bid='12.30',ask='12.40',bid_at=self.now.isoformat(),ask_at=self.now.isoformat())
  adapter=Mock();adapter.poll.return_value=sample;adapter.last_partial_observations=[];adapter.capture_metrics=[];adapter.last_feed_diagnostics={};adapter.last_telemetry={}
  runner=Runner(app.connect);runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now,watch_id=req['watch_id']));view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(view['last_error'],'market_status_evidence_stale');self.assertIsNone(view['last_data_at'])
  self.assertEqual(view['data_status']['partial_quote']['bid'],'12.30');self.assertEqual(view['data_status']['partial_quote']['source_time'],self.now.isoformat())
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_samples WHERE watch_row_id=(SELECT id FROM hw_sessions WHERE watch_id=?)',(req['watch_id'],)).fetchone()[0],0)
 def test_fresh_quote_attached_to_an_old_trade_remains_visible_only_as_quote(self):
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='old-trade-fresh-quote',purpose='quote evidence',provider='eodhd',provider_symbol='MERC.US');engine.create(app.connect,1,req,self.now)
  observed=tick(self.now-timedelta(seconds=130));observed.update(source='eodhd',price_time_kind='trade',market_status='AFTER',status_at=self.now.isoformat(),quote_feed='us_quotes',bid='12.30',ask='12.40',bid_at=self.now.isoformat(),ask_at=self.now.isoformat())
  with app.connect() as c:
   row=c.execute('SELECT id FROM hw_sessions WHERE watch_id=?',(req['watch_id'],)).fetchone()
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],'eodhd','old-trade',(self.now-timedelta(seconds=130)).timestamp(),self.now.isoformat(),json.dumps(observed),'x'))
   c.execute("UPDATE hw_sessions SET status='DEGRADED',last_data=? WHERE id=?",(observed['event_time'],row['id']))
  with patch('hotwatch_engine.utc',return_value=self.now):view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(view['data_status']['partial_quote']['bid'],'12.30')
  self.assertEqual(view['data_status']['partial_quote']['source_time'],self.now.isoformat())
  self.assertEqual(view['data_status']['quote_status'],'FRESH');self.assertEqual(view['data_status']['price_status'],'STALE');self.assertTrue(view['data_stale'])
  self.assertEqual(view['display_status'],'EFTERMARKED AKTIVT · SIGNAL AFVENTER')
  with patch('hotwatch_engine.utc',return_value=self.now):
   summary=next(x for x in engine.sync(app.connect,1,True,summary_only=True)['open_sessions'] if x['watch_id']==req['watch_id'])
  self.assertEqual(summary['price_status'],'STALE');self.assertEqual(summary['bid_ask_status'],'FRESH')
  self.assertEqual(summary['signal'],'NO_DATA')
  invalid=dict(observed,ask_at=(self.now+timedelta(seconds=1)).isoformat())
  with app.connect() as c:c.execute('UPDATE hw_samples SET payload=? WHERE watch_row_id=?',(json.dumps(invalid),row['id']))
  with patch('hotwatch_engine.utc',return_value=self.now):invalid_view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertNotIn('partial_quote',invalid_view['data_status']);self.assertNotEqual(invalid_view['data_status']['quote_status'],'FRESH');self.assertEqual(invalid_view['signal'],'NO_DATA');self.assertTrue(invalid_view['data_stale'])
  with patch('hotwatch_engine.utc',return_value=self.now+timedelta(minutes=3)):view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertNotIn('partial_quote',view['data_status']);self.assertEqual(view['signal'],'NO_DATA')
 def test_pluto_adapter_preserves_untimed_price_as_unverified_observation(self):
  req=copy.deepcopy(self.req);req.update(provider='pluto')
  quote={'asset_id':req['asset_id'],'ticker':req['ticker'],'currency':'USD','price':'12.34','price_time':None,'fetched_at':self.now.isoformat()}
  adapter=PlutoAdapter(app.connect,1)
  with patch('market_data.quote',return_value=quote),patch.object(adapter,'safe_context',return_value=unknown_context()):
   with self.assertRaises(DataUnavailable) as error:adapter.poll({'request_data':req})
  self.assertEqual(error.exception.code,'PLUTO_QUOTE_TIME_UNKNOWN');self.assertEqual(error.exception.partial_observation['price'],'12.34');self.assertIsNone(error.exception.partial_observation['source_time'])
 def test_untimed_eodhd_trade_survives_followup_feed_failure(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='untimed-eodhd',purpose='untimed eodhd',provider='eodhd',provider_symbol='MERC.US',watch_mode='entry');engine.create(app.connect,1,req,self.now)
  adapter=Mock();adapter.poll.side_effect=DataUnavailable('EODHD_READ_ERROR');adapter.last_partial_observations=[{'source':'eodhd','price':'12.34','currency':'USD','source_time':None,'received_at':self.now.isoformat(),'quality':'TIME_UNKNOWN','trade_size':'7'}]
  runner=Runner(app.connect);runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  events=engine.history(app.connect,1,req['watch_id'],True)['items'];observed=[x for x in events if x['event_type']=='PARTIAL_MARKET_OBSERVATION']
  self.assertEqual(len(observed),1);self.assertEqual(observed[0]['data']['supporting_metrics']['trade_size'],'7');self.assertIsNone(observed[0]['data_timestamp'])
  view=engine.item(app.connect,1,req['watch_id'],True)['session'];self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(self.counts()['hw_samples'],0)
 def test_european_quote_is_kept_even_when_no_trade_or_fallback_is_available(self):
  from hotwatch_service import Runner
  class BadOpener:
   def open(self,*args,**kwargs):raise OSError('synthetic outage')
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed.endswith('trades'):return {'status':'NO_MESSAGES','messages':[]}
    return {'status':'OK','messages':[{'event_time':self_now.isoformat(),'received_at':self_now.isoformat(),'bid':'99','ask':'101'}]}
  self_now=self.now;engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='quote-no-trade',purpose='quote without trade',provider='eodhd',provider_symbol='MERC.CO',watch_mode='entry');engine.create(app.connect,1,req,self.now)
  runner=Runner(app.connect);adapter=EODHDAdapter(app.connect,1,BadOpener());runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_adapters.utc',return_value=self.now),patch('hotwatch_adapters.reserve'),patch.object(adapter,'feeds',return_value=Feeds()),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1','ESCAPE_HW_EODHD_WS_EU_EXCHANGES':'CO','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}):
   self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  events=engine.history(app.connect,1,req['watch_id'],True)['items'];observed=[x for x in events if x['event_type']=='PARTIAL_MARKET_OBSERVATION']
  self.assertEqual(len(observed),1);self.assertEqual(observed[0]['data_timestamp'],self.now.isoformat());self.assertEqual(observed[0]['data']['supporting_metrics']['bid'],'99')
  self.assertEqual(engine.item(app.connect,1,req['watch_id'],True)['session']['signal'],'NO_DATA');self.assertEqual(self.counts()['hw_samples'],0)
 def test_us_trade_reaches_database_and_calculation_when_status_is_rate_limited(self):
  from hotwatch_service import Runner
  class Feeds:
   def capture(self,feed,*args,**kwargs):
    if feed=='us_trades':return {'status':'OK','messages':[{'event_time':self_now.isoformat(),'received_at':self_now.isoformat(),'price':'25.93','trade_size':'20','market_session':'extended-hours'}]}
    if feed=='us_quotes':return {'status':'OK','messages':[{'event_time':self_now.isoformat(),'received_at':self_now.isoformat(),'bid':'25.80','ask':'25.99'}]}
    return {'status':'RATE_LIMIT','messages':[]}
  self_now=self.now;engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='us-hims-trace',purpose='synthetic HIMS trace',provider='eodhd',provider_symbol='HIMS.US',watch_mode='entry');engine.create(app.connect,1,req,self.now)
  adapter=EODHDAdapter(app.connect,1,object());runner=Runner(app.connect);runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_adapters.utc',return_value=self.now),patch.object(adapter,'feeds',return_value=Feeds()),patch.object(adapter.pluto,'safe_context',return_value=unknown_context()),patch('hotwatch_warmup.refresh'),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}):
   self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  samples=engine.history(app.connect,1,req['watch_id'],True,'samples')['items'];self.assertEqual(len(samples),1)
  data=samples[0]['data'];self.assertEqual((data['price'],data['trade_size'],data['bid'],data['ask']),('25.93','20','25.80','25.99'));self.assertEqual(data['event_time'],self.now.isoformat());self.assertIsNone(data['volume'])
  view=engine.item(app.connect,1,req['watch_id'],True)['session'];self.assertNotEqual(view['last_computed_signal'],'BUY');self.assertIsNotNone(view['last_calculation_at'])
  # A repeated trade must not suppress a new independently timestamped quote.
  with app.connect() as c:c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',(self.now.timestamp(),req['watch_id']))
  with patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_adapters.utc',return_value=self.now),patch.object(adapter,'feeds',return_value=Feeds()),patch.object(adapter.pluto,'safe_context',return_value=unknown_context()),patch('hotwatch_warmup.refresh'),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1','ESCAPE_HW_EODHD_FUSE_ENABLED':'1'}):
   self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  samples=engine.history(app.connect,1,req['watch_id'],True,'samples')['items']
  self.assertEqual(len(samples),1);self.assertEqual(samples[0]['data']['bid'],'25.80')
  # This feed repeated the identical quote too: no duplicate journal write.
  events=engine.history(app.connect,1,req['watch_id'],True)['items'];self.assertFalse(any(e['event_type']=='MARKET_EVIDENCE_UPDATED' for e in events))
 def test_processing_errors_expose_only_safe_category_and_do_not_create_signal(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='safe-processing-error',purpose='safe processing error',provider='pluto');engine.create(app.connect,1,req,self.now)
  adapter=Mock();adapter.poll.side_effect=TypeError('private-token-never-print');runner=Runner(app.connect);runner.adapters[(1,'pluto')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  session=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertTrue(session['last_error'].startswith('PROCESSING_TYPE_ERROR_'));self.assertNotIn('private-token',session['last_error'])
  self.assertEqual(session['signal'],'NO_DATA');self.assertIsNone(session['last_data_at'])
 def test_repeated_database_contention_retries_without_thirty_minute_backoff(self):
  with app.connect() as c:c.execute('UPDATE hw_sessions SET failures=9 WHERE watch_id=?',(self.req['watch_id'],))
  engine.fault(app.connect,1,self.req['watch_id'],True,'PROCESSING_DATABASE_BUSY_ADAPTER_315',self.now)
  with app.connect() as c:row=engine.row_for(c,1,self.req['watch_id'],True)
  self.assertEqual(row['next_due']-self.now.timestamp(),60);self.assertEqual(row['status'],'DEGRADED')
  self.assertEqual(engine.item(app.connect,1,self.req['watch_id'],True)['session']['signal'],'NO_DATA')
 def test_processing_diagnostic_identifies_real_sqlite_busy_without_error_text(self):
  import sqlite3
  from hotwatch_service import processing_error_code
  holder=app.connect();other=sqlite3.connect(app.DB,timeout=0)
  try:
   holder.execute('BEGIN IMMEDIATE')
   try:other.execute('BEGIN IMMEDIATE')
   except sqlite3.OperationalError as error:
    self.assertTrue(processing_error_code(error).startswith('PROCESSING_DATABASE_BUSY_'))
    self.assertNotIn(app.DB,processing_error_code(error))
   else:self.fail('expected SQLite writer contention')
  finally:
   other.close();holder.rollback();holder.close()
 def test_eodhd_failure_keeps_verified_pluto_context_without_market_signal(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  r=copy.deepcopy(self.req);r.update(watch_id='eodhd-broker-context',purpose='eodhd broker context',provider='eodhd',provider_symbol='MERC.US')
  engine.create(app.connect,1,r,self.now)
  ctx=tick(self.now,held=True)['context']
  with self.assertRaisesRegex(EngineError,'broker_context_source_required'):engine.observe_context(app.connect,1,r['watch_id'],True,ctx,self.now)
  error=DataUnavailable('EODHD_INSTRUMENT_REVALIDATION_REQUIRED');error.position_context=ctx
  adapter=Mock();adapter.poll.side_effect=error;runner=Runner(app.connect);runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_warmup.refresh'):
   self.assertTrue(runner.once(self.now))
  view=engine.item(app.connect,1,r['watch_id'],True)['session']
  self.assertEqual(view['latest_context']['quantity'],'10');self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(view['status'],'DEGRADED')
  self.assertIsNone(view['last_data_at']);self.assertEqual(self.counts()['hw_samples'],0)
 def test_stale_eodhd_fallback_journals_verified_holding_without_signal(self):
  from hotwatch_service import Runner
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'MERC.US','timestamp':int((self_now-timedelta(minutes=1)).timestamp()),'close':'12.34','currency':'USD'}).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  self_now=self.now;engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='stale-fallback-holding',purpose='holding test',provider='eodhd',provider_symbol='MERC.US',watch_mode='exit');engine.create(app.connect,1,req,self.now)
  with app.connect() as c:c.execute('UPDATE hw_sessions SET last_data=? WHERE watch_id=?',(self.now.isoformat(),req['watch_id']))
  runner=Runner(app.connect);adapter=EODHDAdapter(app.connect,1,Opener());runner.adapters[(1,'eodhd')]=adapter
  context=tick(self.now,held=True)['context']
  with patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_adapters.reserve'),patch.object(adapter.pluto,'safe_context',return_value=context),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}):
   self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertEqual(view['latest_context']['quantity'],'10');self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(view['last_error'],'DATA_STALE')
  self.assertEqual(self.counts()['hw_samples'],0)
 def test_stale_fallback_does_not_invent_missing_holding_context(self):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'MERC.US','timestamp':int((self_now-timedelta(minutes=1)).timestamp()),'close':'12.34'}).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  self_now=self.now;req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US',watch_mode='exit')
  with patch('hotwatch_adapters.reserve'),patch('hotwatch_adapters.PlutoAdapter.safe_context',return_value=unknown_context()),patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}):
   with self.assertRaises(DataUnavailable) as error:EODHDAdapter(app.connect,1,Opener()).poll({'request_data':req,'last_data':self.now.isoformat()})
  self.assertEqual(error.exception.code,'DATA_STALE');self.assertIsNone(getattr(error.exception,'position_context',None))
 def test_feed_error_does_not_block_independent_verified_exit_context(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='feed-failed-holding',purpose='feed failed holding test',provider='eodhd',provider_symbol='MERC.US',watch_mode='exit');engine.create(app.connect,1,req,self.now)
  runner=Runner(app.connect);adapter=Mock();adapter.poll.side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429);adapter.pluto.safe_context.return_value=tick(self.now,held=True)['context'];runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertEqual(view['latest_context']['quantity'],'10');self.assertEqual(view['signal'],'NO_DATA');self.assertEqual(view['last_error'],'PROVIDER_RATE_BUDGET');self.assertEqual(self.counts()['hw_samples'],0)
 def test_feed_error_does_not_invent_or_require_missing_exit_context(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='feed-failed-unknown',purpose='feed failed unknown test',provider='eodhd',provider_symbol='MERC.US',watch_mode='exit');engine.create(app.connect,1,req,self.now)
  runner=Runner(app.connect);adapter=Mock();adapter.poll.side_effect=DataUnavailable('EODHD_READ_ERROR');adapter.pluto.safe_context.return_value=unknown_context();runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['latest_context']);self.assertEqual(view['last_error'],'EODHD_READ_ERROR')
 def test_feed_error_rejects_expired_broker_context(self):
  from hotwatch_service import Runner
  from unittest.mock import Mock
  engine.control(app.connect,1,self.req['watch_id'],True,'pause',self.now)
  req=copy.deepcopy(self.req);req.update(watch_id='feed-failed-old-context',purpose='expired broker context test',provider='eodhd',provider_symbol='MERC.US',watch_mode='exit');engine.create(app.connect,1,req,self.now)
  old=tick(self.now-timedelta(minutes=10),held=True)['context'];runner=Runner(app.connect);adapter=Mock();adapter.poll.side_effect=DataUnavailable('EODHD_READ_ERROR');adapter.pluto.safe_context.return_value=old;runner.adapters[(1,'eodhd')]=adapter
  with patch('hotwatch_engine.utc',return_value=self.now):self.assertTrue(runner.once(self.now,watch_id=req['watch_id']))
  view=engine.item(app.connect,1,req['watch_id'],True)['session']
  self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['latest_context']);self.assertEqual(view['last_error'],'EODHD_READ_ERROR')
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
 def test_historical_warmup_never_generates_current_trading_signals(self):
  req=copy.deepcopy(self.req);req.update(watch_id='history-isolation',purpose='history isolation',provider='eodhd',provider_symbol='MERC.US')
  engine.create(app.connect,1,req,self.now)
  with app.connect() as c:
   row=c.execute('SELECT id FROM hw_sessions WHERE watch_id=?',(req['watch_id'],)).fetchone()
   bars=[{'bar_open_at':(self.now-timedelta(minutes=34-i)).isoformat(),'open':'100','high':'102','low':'99','close':'101','volume':'20'} for i in range(34)]
   c.execute('INSERT INTO hw_warmup_history VALUES(?,?,?,?,?,?)',(row['id'],'MERC.US',self.now.isoformat(),json.dumps(bars),self.now.timestamp()+300,'OK'))
  sample=tick(self.now);sample.update(source='eodhd',price_time_kind='trade',status_at=self.now.isoformat(),bid_at=self.now.isoformat(),ask_at=self.now.isoformat())
  result=engine.ingest(app.connect,1,req['watch_id'],True,sample,self.now)
  self.assertEqual(result['calculation']['supporting_metrics']['sample_count'],1);self.assertEqual(result['calculation']['signal'],'NO_DATA');self.assertIn('WARMUP',result['calculation']['reason_codes'])
 def test_verified_history_is_used_only_with_a_new_current_observation(self):
  req=copy.deepcopy(self.req);req.update(watch_id='history-live',purpose='history live',provider='eodhd',provider_symbol='MERC.US')
  engine.create(app.connect,1,req,self.now);end=self.now.replace(second=0,microsecond=0);at=end+timedelta(seconds=59)
  bars=[{'bar_open_at':(end-timedelta(minutes=34-i)).isoformat(),'open':'100','high':'102','low':'99','close':'101','volume':'20'} for i in range(34)]
  with app.connect() as c:
   row=c.execute('SELECT id FROM hw_sessions WHERE watch_id=?',(req['watch_id'],)).fetchone()
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,req['asset_id'],req['ticker'],req['quote_currency'],req['exchange'],req['provider_symbol'],'US1234567890',self.now.timestamp()))
   c.execute('INSERT INTO hw_warmup_history VALUES(?,?,?,?,?,?)',(row['id'],'MERC.US',self.now.isoformat(),json.dumps(bars),self.now.timestamp()+300,'OK'))
   self.assertEqual(c.execute('SELECT count(*) FROM hw_calculations WHERE watch_row_id=?',(row['id'],)).fetchone()[0],0)
  sample=tick(at);sample.update(source='eodhd',market_status='UNKNOWN',session_key='fixture:UNKNOWN',bid=None,ask=None,interval_s=60)
  result=engine.ingest(app.connect,1,req['watch_id'],True,sample,at)
  self.assertEqual(result['calculation']['supporting_metrics']['sample_count'],34)
  self.assertEqual(result['calculation']['supporting_metrics']['bar_history_count'],34)
  self.assertEqual(result['calculation']['signal'],'NO_DATA');self.assertIn('MARKET_STATUS_UNKNOWN',result['calculation']['reason_codes'])
 def test_history_can_seed_a_fresh_regular_session_without_skipping_risk_rules(self):
  base=datetime(2026,11,4,15,30,tzinfo=timezone.utc);at=base+timedelta(seconds=59)
  req=copy.deepcopy(self.req);req.update(watch_id='history-regular',purpose='history regular',provider='eodhd',provider_symbol='MERC.US')
  engine.create(app.connect,1,req,base)
  bars=[{'bar_open_at':(base-timedelta(minutes=34-i)).isoformat(),'open':'100','high':'102','low':'99','close':'101','volume':'20'} for i in range(34)]
  calendar={'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  with app.connect() as c:
   row=c.execute('SELECT id FROM hw_sessions WHERE watch_id=?',(req['watch_id'],)).fetchone()
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,req['asset_id'],req['ticker'],req['quote_currency'],req['exchange'],req['provider_symbol'],'US1234567890',base.timestamp()))
   c.execute('INSERT INTO hw_warmup_history VALUES(?,?,?,?,?,?)',(row['id'],'MERC.US',base.isoformat(),json.dumps(bars),base.timestamp()+300,'OK'))
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',at.isoformat(),'America/New_York',json.dumps(calendar)))
  sample=tick(at);sample.update(source='eodhd',feed_type='test real-time trade',price_time_kind='trade',status_at=at.isoformat(),status_feed='us-status',bid_at=at.isoformat(),ask_at=at.isoformat(),quote_feed='us-quotes')
  result=engine.ingest(app.connect,1,req['watch_id'],True,sample,at)
  self.assertEqual(result['calculation']['supporting_metrics']['sample_count'],34)
  self.assertEqual(result['calculation']['supporting_metrics']['bar_history_count'],34)
  self.assertNotIn('WARMUP',result['calculation']['reason_codes'])
  self.assertFalse(result['calculation']['critical_override'])
 def test_identity_and_phase_reset_but_gaps_keep_actual_period_history(self):
  rows=[tick(self.now+timedelta(minutes=i),i) for i in range(40)]
  for key,value in [('source','eodhd'),('currency','DKK'),('market_status','PRE'),('session_key','NEXT'),('interval_s',15)]:
   changed=copy.deepcopy(rows);changed[-1][key]=value;self.assertEqual(features(changed,BASELINE['parameters'])['sample_count'],1)
  changed=copy.deepcopy(rows);changed[-1]['event_time']=(self.now+timedelta(hours=10)).isoformat();m=features(changed,BASELINE['parameters']);self.assertEqual(m['sample_count'],40);self.assertIsNone(m['return_3_pct']);self.assertIsNone(m['acceleration_pct_s2'])
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
 def test_worker_ingest_skips_view_for_new_and_duplicate_sample(self):
  from unittest.mock import patch
  sample=tick(self.now)
  with patch.object(engine,'view',side_effect=AssertionError('worker must not build view')):
   first=engine.ingest(app.connect,1,self.req['watch_id'],True,sample,self.now,include_session=False)
   second=engine.ingest(app.connect,1,self.req['watch_id'],True,sample,self.now,include_session=False)
  self.assertTrue(first['ok']);self.assertFalse(first['duplicate']);self.assertIn('calculation',first)
  self.assertTrue(second['duplicate']);self.assertNotIn('session',first);self.assertNotIn('session',second)
  self.assertEqual(self.counts()['hw_samples'],1)
 def test_empty_queue_does_not_request_database_writer_lock(self):
  import sqlite3
  with app.connect() as c:c.execute('UPDATE hw_sessions SET next_due=?',(self.now.timestamp()+3600,))
  holder=app.connect()
  def quick_connect():
   c=sqlite3.connect(app.DB,timeout=0);c.row_factory=sqlite3.Row;return c
  try:
   holder.execute('BEGIN IMMEDIATE')
   self.assertIsNone(engine.claim(quick_connect,self.now))
  finally:holder.rollback();holder.close()
 def test_stale_data_rechecks_at_budgeted_cadence_without_enabling_signal(self):
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True);req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='MERC.US')
   c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(req),row['id']))
  for i in range(6):
   at=self.now+timedelta(minutes=i*10);engine.fault(app.connect,1,self.req['watch_id'],True,'DATA_STALE',at)
  with app.connect() as c:
   row=engine.row_for(c,1,self.req['watch_id'],True)
   self.assertEqual(row['next_due'],at.timestamp()+engine.effective_poll_interval(c,req))
   self.assertEqual(json.loads(row['state'])['signal'],'NO_DATA')
 def test_sync_bounds_each_page_but_returns_all_sessions_via_cursor(self):
  with app.connect() as c:
   base=dict(engine.row_for(c,1,self.req['watch_id'],True));base.pop('id')
   for i in range(11):
    item=dict(base);item['watch_id']='extra-'+str(i);item['candidate_id']='candidate-extra-'+str(i)
    req=json.loads(item['request']);req.update(watch_id=item['watch_id'],candidate_id=item['candidate_id'],watch_mode='exit');item['request']=json.dumps(req)
    cols=list(item);c.execute('INSERT INTO hw_sessions('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',[item[k] for k in cols])
  first=engine.sync(app.connect,1,True,session_limit=100,summary_only=True)
  self.assertEqual(len(first['open_sessions']),10);self.assertTrue(first['sessions_have_more'])
  second=engine.sync(app.connect,1,True,sessions_after=first['next_sessions_cursor'],session_limit=100,summary_only=True)
  self.assertEqual(len(second['open_sessions']),2);self.assertFalse(second['sessions_have_more'])
  self.assertEqual(len({s['watch_id'] for s in first['open_sessions']+second['open_sessions']}),12)
 def test_due_verified_sessions_share_european_stream_by_symbol(self):
  import hotwatch_adapters as adapters
  symbols=['NOVO-B.CO','GMAB.CO','DSV.CO','VWS.CO','CARL-B.CO'];jobs=[]
  with app.connect() as c:
   base=dict(engine.row_for(c,1,self.req['watch_id'],True));base.pop('id')
   for i,symbol in enumerate(symbols):
    item=dict(base);item.update(watch_id='batch-'+str(i),candidate_id='batch-candidate-'+str(i),is_test=0,next_due=self.now.timestamp())
    req=json.loads(item['request']);req.update(watch_id=item['watch_id'],candidate_id=item['candidate_id'],provider='eodhd',provider_symbol=symbol,is_test=False,asset_id='asset-'+str(i));item['request']=json.dumps(req)
    cols=list(item);cur=c.execute('INSERT INTO hw_sessions('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',[item[k] for k in cols]);jobs.append({'id':cur.lastrowid,'request_data':req})
  class Client:
   def __init__(self):self.calls=[]
   def capture(self,feed,requested,duration,max_messages):
    self.calls.append((feed,requested));return {'status':'OK','messages':[{'symbol':s,'event_time':self_now.isoformat(),'price':str(i+1)} for i,s in enumerate(requested)]}
  self_now=self.now;client=Client();adapter=EODHDAdapter(app.connect,1);adapters._ws_batch_cache.clear()
  try:
   with patch('hotwatch_engine.verified_automatic_feed',return_value=True),patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'test-only','ESCAPE_HW_EODHD_WS_EU_EXCHANGES':'CO'}):
    for symbol,job in zip(symbols,jobs):
     result=adapter.capture(client,'eu_trades',symbol,job)
     self.assertEqual([m['symbol'] for m in result['messages']],[symbol])
   self.assertEqual(len(client.calls),1);self.assertEqual(set(client.calls[0][1]),set(symbols))
  finally:adapters._ws_batch_cache.clear()
 def test_different_websocket_feeds_do_not_block_each_other_during_network_wait(self):
  import hotwatch_adapters as adapters,threading
  from concurrent.futures import ThreadPoolExecutor
  adapter=EODHDAdapter(app.connect,1);entered={'us_trades':threading.Event(),'us_quotes':threading.Event()};release=threading.Event()
  req=copy.deepcopy(self.req);req.update(is_test=False,provider='eodhd',provider_symbol='MERC.US');job={'id':1,'request_data':req}
  class Client:
   def capture(self,feed,symbol,**kw):
    entered[feed].set();release.wait(3);return {'status':'NO_MESSAGES','messages':[]}
  adapters._ws_batch_cache.clear()
  try:
   with patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'test-only'}),ThreadPoolExecutor(max_workers=2) as pool:
    futures=[pool.submit(adapter.capture,Client(),feed,'MERC',job) for feed in ('us_trades','us_quotes')]
    self.assertTrue(entered['us_trades'].wait(2));self.assertTrue(entered['us_quotes'].wait(2));release.set()
    self.assertTrue(all(x.result(timeout=3)['status']=='NO_MESSAGES' for x in futures))
  finally:release.set();adapters._ws_batch_cache.clear()
 def test_concurrent_identical_websocket_batch_is_captured_once(self):
  import hotwatch_adapters as adapters,threading
  from concurrent.futures import ThreadPoolExecutor
  adapter=EODHDAdapter(app.connect,1);entered=threading.Event();release=threading.Event();calls=[]
  req=copy.deepcopy(self.req);req.update(is_test=False,provider='eodhd',provider_symbol='MERC.US');job={'id':1,'request_data':req}
  class Client:
   def capture(self,feed,symbol,**kw):
    calls.append(feed);entered.set();release.wait(3);return {'status':'NO_MESSAGES','messages':[]}
  adapters._ws_batch_cache.clear()
  try:
   with patch.dict(os.environ,{'ESCAPE_EODHD_API_KEY':'test-only'}),ThreadPoolExecutor(max_workers=2) as pool:
    first=pool.submit(adapter.capture,Client(),'us_trades','MERC',job);self.assertTrue(entered.wait(2))
    second=pool.submit(adapter.capture,Client(),'us_trades','MERC',job)
    self.assertEqual(second.result(timeout=1)['status'],'COLLECTING');release.set()
    self.assertEqual(first.result(timeout=3)['status'],'NO_MESSAGES')
    self.assertEqual(adapter.capture(Client(),'us_trades','MERC',job)['status'],'NO_MESSAGES');self.assertEqual(calls,['us_trades'])
  finally:release.set();adapters._ws_batch_cache.clear()
 def test_five_concurrent_scans_record_without_busy_in_local_database(self):
  import threading
  from concurrent.futures import ThreadPoolExecutor
  watches=[]
  for i in range(5):
   req=copy.deepcopy(self.req);req.update(watch_id='concurrent-scan-'+str(i),purpose='concurrent scan '+str(i));engine.create(app.connect,1,req,self.now);watches.append(req['watch_id'])
  barrier=threading.Barrier(5)
  def scan(wid):
   barrier.wait(timeout=5);return engine.ingest(app.connect,1,wid,True,tick(self.now),self.now,include_session=False)
  with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(scan,watches))
  self.assertEqual(len(results),5)
  for result in results:
   self.assertTrue(result['ok']);self.assertNotEqual(result['calculation']['signal'],'BUY')
   self.assertGreaterEqual(result['sqlite_timing']['begin_wait_ms'],0);self.assertGreaterEqual(result['sqlite_timing']['work_before_commit_ms'],0)
 def test_ingest_timing_distinguishes_scope_entry_from_sqlite_begin(self):
  import time
  from contextlib import contextmanager
  calls=[]
  @contextmanager
  def slow_second_scope():
   calls.append(1)
   if len(calls)==2:time.sleep(.06)
   with app.connect() as c:yield c
  timing=engine.ingest(slow_second_scope,1,self.req['watch_id'],True,tick(self.now),self.now,include_session=False)['sqlite_timing']
  self.assertGreaterEqual(timing['scope_entry_wait_ms'],45)
  self.assertGreaterEqual(timing['sqlite_begin_ms'],0)
  self.assertAlmostEqual(timing['begin_wait_ms'],timing['scope_entry_wait_ms']+timing['sqlite_begin_ms'],delta=.01)
 def test_ingest_timing_records_sqlite_writer_wait_separately(self):
  import threading
  from contextlib import contextmanager
  ready=threading.Event();entered=threading.Event();errors=[];calls=[]
  def writer():
   try:
    with app.connect() as c:
     c.execute('BEGIN IMMEDIATE');ready.set()
     if not entered.wait(5):raise RuntimeError('ingest did not start writer scope')
     threading.Event().wait(.08)
   except Exception as exc:errors.append(exc);ready.set()
  @contextmanager
  def notify_second_scope():
   calls.append(1)
   with app.connect() as c:
    if len(calls)==2:entered.set()
    yield c
  thread=threading.Thread(target=writer);thread.start()
  try:
   self.assertTrue(ready.wait(5));self.assertFalse(errors)
   timing=engine.ingest(notify_second_scope,1,self.req['watch_id'],True,tick(self.now),self.now,include_session=False)['sqlite_timing']
  finally:entered.set();thread.join(5)
  self.assertFalse(thread.is_alive());self.assertFalse(errors)
  self.assertGreaterEqual(timing['sqlite_begin_ms'],50)
  self.assertAlmostEqual(timing['begin_wait_ms'],timing['scope_entry_wait_ms']+timing['sqlite_begin_ms'],delta=.01)
 def test_latest_observations_have_indexes_after_repeat_initialization(self):
  app.init()
  with app.connect() as c:
   for table,index in [('hw_samples','hw_samples_latest'),('hw_calculations','hw_calculations_latest'),('hw_context_events','hw_context_latest')]:
    plan=' '.join(str(tuple(row)) for row in c.execute('EXPLAIN QUERY PLAN SELECT payload FROM '+table+' WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(1,)))
    self.assertIn(index,plan);self.assertNotIn('TEMP B-TREE',plan)
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
 def test_scheduler_prioritizes_due_exit_before_candidate_without_disabling_either(self):
  exit_req=copy.deepcopy(self.req);exit_req.update(watch_id='exit-first',purpose='separate holding protection',watch_mode='exit')
  engine.create(app.connect,1,exit_req,self.now)
  with app.connect() as c:c.execute('UPDATE hw_sessions SET next_due=?',(self.now.timestamp(),))
  first=engine.claim(app.connect,self.now+timedelta(seconds=1));self.assertEqual(first['watch_id'],'exit-first')
  second=engine.claim(app.connect,self.now+timedelta(seconds=1));self.assertEqual(second['watch_id'],self.req['watch_id'])
 def test_scheduler_prioritizes_time_limited_catalyst_then_returns_to_fifo(self):
  candidate=copy.deepcopy(self.req);candidate.update(watch_id='news-priority',purpose='news-priority')
  engine.create(app.connect,1,candidate,self.now)
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET next_due=?',(self.now.timestamp(),))
   c.execute('UPDATE hw_sessions SET state=? WHERE watch_id=?',(json.dumps({'signal':'NO_DATA','catalyst_priority_until':self.now.timestamp()+30}),candidate['watch_id']))
  selected=engine.claim(app.connect,self.now+timedelta(seconds=1));self.assertEqual(selected['watch_id'],'news-priority')
  with app.connect() as c:c.execute("UPDATE hw_sessions SET lease_until=0,lease_owner=NULL")
  selected=engine.claim(app.connect,self.now+timedelta(seconds=31));self.assertEqual(selected['watch_id'],self.req['watch_id'])
 def test_overdue_candidate_is_not_starved_by_newly_due_holdings(self):
  exit_req=copy.deepcopy(self.req);exit_req.update(watch_id='exit-fairness',purpose='holding fairness',watch_mode='exit');engine.create(app.connect,1,exit_req,self.now)
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',((self.now-timedelta(seconds=121)).timestamp(),self.req['watch_id']))
   c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',(self.now.timestamp(),exit_req['watch_id']))
  selected=engine.claim(app.connect,self.now);self.assertEqual(selected['watch_id'],self.req['watch_id'])
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
 def test_older_eodhd_fallback_is_explicitly_stale_and_not_rejournalled(self):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'MERC.US','timestamp':int(old.timestamp()),'close':'12.34','currency':'USD'}).encode()
  class Opener:
   def open(self,*args,**kwargs):return Response()
  old=self.now-timedelta(minutes=2);req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US',quote_currency='USD')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}):
   with self.assertRaisesRegex(DataUnavailable,'DATA_STALE'):EODHDAdapter(app.connect,1,Opener()).poll({'request_data':req,'last_data':self.now.isoformat()})
 def test_real_adapter_shares_identical_quote_without_sharing_context(self):
  import hotwatch_adapters as adapters
  adapters._quote_cache.clear()
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,limit):return json.dumps({'code':'MERC.US','timestamp':int(self_now.timestamp()),'close':'12.34','currency':'USD'}).encode()
  class Opener:
   def __init__(self):self.calls=0
   def open(self,*args,**kwargs):self.calls+=1;return Response()
  opener=Opener();self_now=self.now;req=copy.deepcopy(self.req);req.update(provider='eodhd',provider_symbol='MERC.US',quote_currency='USD')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'TEST-ONLY','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}),patch('hotwatch_adapters.urllib.request.build_opener',return_value=opener),patch('hotwatch_adapters.PlutoAdapter.context',side_effect=[unknown_context('FIRST'),unknown_context('SECOND')]),patch('eodhd_capacity.Capacity.reserve') as budget:
   a=EODHDAdapter(app.connect,1).poll({'request_data':req});b=EODHDAdapter(app.connect,1).poll({'request_data':req})
  self.assertEqual(opener.calls,1);self.assertEqual(budget.call_count,1)
  self.assertEqual(a['event_time'],b['event_time']);self.assertEqual(a['context']['diagnostic'],'FIRST');self.assertEqual(b['context']['diagnostic'],'SECOND')
  adapters._quote_cache.clear()
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
   old['feed_type']='EODHD REST real-time endpoint; legacy metadata';old['price']='12.3400';old['sample_id']='legacy-sample-id';old['verification']='unverified'
   engine.ingest(app.connect,1,r['watch_id'],True,old,self.now)
   row['last_data']=old['event_time']
   payload['volume']=12345;repeated=adapter.poll(row)
   self.assertIsNone(repeated['volume']);self.assertEqual(repeated['verification'],'unverified');self.assertEqual(repeated['sample_id'],'legacy-sample-id');self.assertTrue(engine.ingest(app.connect,1,r['watch_id'],True,repeated,self.now)['duplicate'])
   payload['close']='12.35';conflict=adapter.poll(row)
   with self.assertRaisesRegex(EngineError,'sample_id_conflict'):engine.ingest(app.connect,1,r['watch_id'],True,conflict,self.now)
   payload['close']='12.34'
   payload['timestamp']+=1;fresh=adapter.poll(row)
   self.assertEqual(fresh['volume'],'12345');self.assertEqual(fresh['volume_type'],'unknown');self.assertIsNone(fresh['bid']);self.assertIsNone(fresh['ask'])
   result=engine.ingest(app.connect,1,r['watch_id'],True,fresh,self.now+timedelta(seconds=1))
   self.assertIsNone(result['calculation']['supporting_metrics']['interval_volume'])
   payload['volume']=-3;payload['timestamp']+=1
   self.assertIsNone(adapter.poll(row)['volume'])
 def test_conflicting_sample_is_retried_at_sustainable_interval_without_acceptance(self):
  wid=self.req['watch_id']
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(wid,)).fetchone()
   request=json.loads(row['request'])
   expected=engine.effective_poll_interval(c,request)
   c.execute('UPDATE hw_sessions SET failures=8 WHERE id=?',(row['id'],))
  engine.fault(app.connect,1,wid,True,'sample_id_conflict',self.now)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(wid,)).fetchone()
   self.assertEqual(row['status'],'DEGRADED')
   self.assertEqual(row['last_error'],'sample_id_conflict')
   self.assertAlmostEqual(row['next_due']-self.now.timestamp(),expected)
   self.assertEqual(json.loads(row['state'])['signal'],'NO_DATA')
 def test_existing_conflict_backoff_is_rescheduled_without_changing_data(self):
  wid=self.req['watch_id']
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET status='DEGRADED',last_error='sample_id_conflict',next_due=?,state=? WHERE watch_id=?",((self.now+timedelta(minutes=30)).timestamp(),json.dumps({'signal':'NO_DATA','confirmations':0}),wid))
   before=c.execute('SELECT last_data,last_calculation FROM hw_sessions WHERE watch_id=?',(wid,)).fetchone()
   count=c.execute('SELECT count(*) FROM hw_samples').fetchone()[0]
  with patch('intel_workflows.candidate_currentness',return_value={'status':'CURRENT'}):
   self.assertEqual(engine.reconcile_candidates(app.connect,self.now),1)
   self.assertEqual(engine.reconcile_candidates(app.connect,self.now),0)
  with app.connect() as c:
   after=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(wid,)).fetchone()
   self.assertEqual(after['next_due'],self.now.timestamp())
   self.assertEqual(after['last_error'],'sample_id_conflict')
   self.assertEqual((after['last_data'],after['last_calculation']),(before['last_data'],before['last_calculation']))
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],count)
 def test_deferred_conflict_retry_accepts_only_a_new_valid_observation(self):
  wid=self.req['watch_id'];original=tick(self.now);self.put(original)
  conflict=copy.deepcopy(original);conflict['volume']='101'
  with self.assertRaisesRegex(EngineError,'sample_id_conflict'):self.put(conflict)
  engine.fault(app.connect,1,wid,True,'sample_id_conflict',self.now)
  with app.connect() as c:c.execute('UPDATE hw_sessions SET next_due=? WHERE watch_id=?',((self.now+timedelta(minutes=30)).timestamp(),wid))
  with patch('intel_workflows.candidate_currentness',return_value={'status':'CURRENT'}):engine.reconcile_candidates(app.connect,self.now)
  later=self.now+timedelta(seconds=1);new=tick(later,1,price='101');result=self.put(new,later)
  self.assertFalse(result['duplicate']);self.assertEqual(result['session']['watch_id'],wid)
  with app.connect() as c:
   rows=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=(SELECT id FROM hw_sessions WHERE watch_id=?) ORDER BY id',(wid,)).fetchall()
   self.assertEqual([json.loads(x['payload'])['volume'] for x in rows],['100','100'])
   self.assertIsNone(c.execute('SELECT last_error FROM hw_sessions WHERE watch_id=?',(wid,)).fetchone()['last_error'])
 def test_conflict_backoff_does_not_interrupt_an_active_lease(self):
  wid=self.req['watch_id']
  with app.connect() as c:c.execute("UPDATE hw_sessions SET status='DEGRADED',last_error='sample_id_conflict',next_due=?,lease_owner='synthetic',lease_until=? WHERE watch_id=?",((self.now+timedelta(minutes=30)).timestamp(),(self.now+timedelta(minutes=1)).timestamp(),wid))
  with patch('intel_workflows.candidate_currentness',return_value={'status':'CURRENT'}):self.assertEqual(engine.reconcile_candidates(app.connect,self.now),0)
  with app.connect() as c:
   row=c.execute('SELECT next_due,lease_owner FROM hw_sessions WHERE watch_id=?',(wid,)).fetchone()
   self.assertEqual(row['lease_owner'],'synthetic');self.assertEqual(row['next_due'],(self.now+timedelta(minutes=30)).timestamp())
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
  self.assertEqual(view['data_status']['price'],'100');self.assertEqual(view['display_status'],'AFVENTER SIGNALDATA');self.assertEqual(view['signal'],'NO_DATA');self.assertNotEqual(view['last_error'],'EODHD_RATE_LIMIT');self.assertIsNone(view['data_status']['bid'])
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
  result=auto_activate_candidate(app.connect,1,True,report,candidate,verify,lookup);self.assertEqual(result['status'],'CREATED')
  again=auto_activate_candidate(app.connect,1,True,report,candidate,verify,lookup);self.assertIn(again['status'],('NOT_NEW','ALREADY_ACTIVE'))
  session=engine.item(app.connect,1,result['watch_id'],True)['session'];self.assertEqual(session['request']['candidate_id'],candidate['candidate_id']);self.assertEqual(session['request']['trade_cycle_id'],'cycle-preserved');self.assertIsNone(session['request']['risk']['proposed_quantity'])
  # Simulate the separate, completed feed-recovery step in this synthetic test.
  # Activation itself must not perform a provider lookup.
  with app.connect() as c:
   row=c.execute('SELECT request FROM hw_sessions WHERE watch_id=?',(result['watch_id'],)).fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='MERC.US')
   c.execute('UPDATE hw_sessions SET request=? WHERE watch_id=?',(json.dumps(req),result['watch_id']))
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
  result=auto_activate_candidate(app.connect,1,True,report,candidate,lambda *a:verified,ambiguous);self.assertEqual(result['status'],'CREATED')
  self.assertEqual(engine.item(app.connect,1,result['watch_id'],True)['session']['request']['provider'],'pluto')
 def test_discovery_handles_renewed_report_without_asset_id_or_explicit_decision(self):
  from hotwatch_service import auto_activate_candidate
  report=copy.deepcopy(self.r);report['report_id']='automatic-unresolved-1';report['generated_at']=self.now.isoformat();candidate=report['candidates'][0];candidate.update(candidate_id='unresolved-auto',asset_id=None,decision=None,exchange='NASDAQ')
  report_ingest.save(app.connect,1,report);new=copy.deepcopy(report);new['report_id']='automatic-unresolved-2';report_ingest.save(app.connect,1,new)
  verified={'asset_id':'resolved-asset','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  with patch('trade_service.search',return_value={'assets':[{'asset_id':'resolved-asset','ticker':'MERC'}]}):
   result=auto_activate_candidate(app.connect,1,True,new,new['candidates'][0],lambda *a:verified,lambda *a:{'choices':[{'symbol':'MERC.US','currency':'USD','isin':'US1234567890'}]})
  self.assertEqual(result['status'],'CREATED');self.assertEqual(engine.item(app.connect,1,result['watch_id'],True)['session']['request']['asset_id'],'resolved-asset')
  engine.control(app.connect,1,result['watch_id'],True,'stop',self.now)
  self.assertEqual(auto_activate_candidate(app.connect,1,True,new,new['candidates'][0],lambda *a:verified,lambda *a:{})['status'],'NOT_NEW')
 def test_auto_discovery_does_not_restart_manually_stopped_instrument_under_new_candidate(self):
  from hotwatch_service import auto_activate_candidate
  engine.control(app.connect,1,self.req['watch_id'],True,'stop',self.now)
  report=copy.deepcopy(self.r);report['report_id']='synthetic-stopped-asset';candidate=report['candidates'][0];candidate.update(candidate_id='another-idea',asset_id=self.req['asset_id'],exchange='NASDAQ');report_ingest.save(app.connect,1,report)
  result=auto_activate_candidate(app.connect,1,True,report,candidate,lambda *a:self.fail('Stopped asset must not be restarted'),lambda *a:{})
  self.assertEqual(result['status'],'NOT_NEW')
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
 def test_auto_discovery_report_to_persisted_session_and_retry_evidence(self):
  from hotwatch_service import auto_discover
  report=merc_report(False);report['report_id']='automatic-report-live-fixture';candidate=report['candidates'][0];candidate['asset_id']='synthetic-MERC';candidate['exchange']='NASDAQ';report_ingest.save(app.connect,1,report)
  verified={'asset_id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(engine.utc()-timedelta(minutes=1)).isoformat()}),patch('hotwatch_service.verified_discovery_instrument',return_value=verified),patch('hotwatch_adapters.search_eodhd_symbols',return_value={'choices':[{'symbol':'MERC.US','currency':'USD','isin':'US1234567890'}]}):
   auto_discover(app.connect,0)
  with app.connect() as c:
   attempt=c.execute('SELECT status,watch_id FROM hw_discovery_attempts WHERE user_id=1 AND candidate_id=?',(candidate['candidate_id'],)).fetchone();self.assertEqual(attempt['status'],'CREATED');wid=attempt['watch_id']
  session=engine.item(app.connect,1,wid,False)['session'];self.assertEqual(session['request']['candidate_id'],candidate['candidate_id']);self.assertEqual(session['status'],'CREATED')
 def test_reassessed_candidate_after_automatic_expiry_starts_new_unplanned_watch(self):
  from hotwatch_service import auto_activate_candidate
  import intel_workflows
  report=merc_report(False);report['report_id']='reassessed-fixture';candidate=report['candidates'][0];candidate.update(asset_id='synthetic-MERC',exchange='NASDAQ');report_ingest.save(app.connect,1,report)
  verified={'asset_id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  now=engine.utc();expired=now-timedelta(seconds=10)
  first=auto_activate_candidate(app.connect,1,False,report,candidate,lambda *_:verified)
  self.assertEqual(first['status'],'CREATED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(first['watch_id'],)).fetchone()
   c.execute("UPDATE hw_sessions SET status='EXPIRED' WHERE id=?",(row['id'],))
   engine.event(c,row,'CAPACITY_RELEASED',expired-timedelta(seconds=2),'older capacity event')
   engine.event(c,row,'CAPACITY_RESTORED',expired-timedelta(seconds=1),'older restore event')
   engine.event(c,row,'CANDIDATE_WATCH_EXPIRED',expired,'synthetic expiry')
  self.assertEqual(auto_activate_candidate(app.connect,1,False,report,candidate,lambda *_:self.fail('old assessment cannot reactivate'))['status'],'NOT_NEW')
  reassessment=copy.deepcopy(candidate['decision']);reassessment['decided_at']=(now-timedelta(seconds=1)).isoformat()
  with app.connect() as c:intel_workflows.index_decision(c,1,False,candidate['candidate_id'],reassessment,'synthetic-new-assessment')
  second=auto_activate_candidate(app.connect,1,False,report,candidate,lambda *_:verified)
  self.assertEqual(second['status'],'CREATED');self.assertNotEqual(first['watch_id'],second['watch_id'])
  with app.connect() as c:
   rows=c.execute('SELECT watch_id,status,request FROM hw_sessions WHERE candidate_id=? AND watch_id IN (?,?) ORDER BY id',(candidate['candidate_id'],first['watch_id'],second['watch_id'])).fetchall()
   self.assertEqual([(r['watch_id'],r['status']) for r in rows],[(first['watch_id'],'EXPIRED'),(second['watch_id'],'CREATED')])
   risk=json.loads(rows[-1]['request'])['risk'];self.assertIsNone(risk['proposed_quantity']);self.assertIsNone(risk['stop_price'])
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
  engine.control(app.connect,1,second['watch_id'],False,'stop')
  self.assertEqual(auto_activate_candidate(app.connect,1,False,report,candidate,lambda *_:self.fail('manual stop must be respected'))['status'],'NOT_NEW')

 def test_capacity_released_candidate_can_restart_when_space_returns(self):
  from hotwatch_service import auto_activate_candidate
  report=merc_report(False);report['report_id']='capacity-return-fixture';candidate=report['candidates'][0];candidate['asset_id']='synthetic-MERC';candidate['exchange']='NASDAQ';report_ingest.save(app.connect,1,report)
  verified={'asset_id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  first=auto_activate_candidate(app.connect,1,False,report,candidate,lambda *_:verified)
  self.assertEqual(first['status'],'CREATED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(first['watch_id'],)).fetchone()
   original_id=row['id'];original_strategy=row['strategy']
   c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(row['id'],self.now.isoformat(),json.dumps({'status':'verified','position':'none','orders':[],'as_of':self.now.isoformat()})))
   c.execute("UPDATE hw_sessions SET status='EXPIRED' WHERE id=?",(row['id'],))
   engine.event(c,row,'CAPACITY_RELEASED',self.now,'synthetic')
  second=auto_activate_candidate(app.connect,1,False,report,candidate,lambda *_:verified)
  self.assertEqual(second['status'],'VALIDATING')
  self.assertEqual(first['watch_id'],second['watch_id'])
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions WHERE id=?',(original_id,)).fetchone()
   self.assertEqual(row['strategy'],original_strategy)
   self.assertEqual(c.execute('SELECT count(*) FROM hw_context_events WHERE watch_row_id=?',(original_id,)).fetchone()[0],1)
   self.assertEqual(c.execute("SELECT count(*) FROM hw_events WHERE watch_row_id=? AND event_type IN ('CAPACITY_RELEASED','CAPACITY_RESTORED')",(original_id,)).fetchone()[0],2)
 def test_auto_discovery_visits_every_report_candidate_without_replaying_completed_attempts(self):
  from hotwatch_service import auto_discover
  report=merc_report(False);report['report_id']='synthetic-all-candidates';report_ingest.save(app.connect,1,report);seen=[]
  def activate(connect,uid,mode,report,candidate):seen.append(candidate['candidate_id']);return {'status':'ALREADY_ACTIVE'}
  with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(engine.utc()-timedelta(minutes=1)).isoformat()}),patch('hotwatch_service.auto_activate_candidate',side_effect=activate):
   cursor=0
   for _ in range(len(report['candidates'])+2):cursor=auto_discover(app.connect,cursor)
  self.assertEqual(set(seen),{x['candidate_id'] for x in report['candidates']});self.assertEqual(len(seen),len(report['candidates']))
 def test_discovery_keeps_candidates_from_previous_reports_and_uses_latest_assessment(self):
  from hotwatch_service import auto_discover
  with app.connect() as c:
   for name,cid,offset in [('old-A','A',20),('new-B','B',10),('new-A','A',5)]:
    at=(engine.utc()-timedelta(seconds=offset)).timestamp();payload={'report_id':name,'candidates':[{'candidate_id':cid}]}
    row=c.execute('INSERT INTO ingested_reports(user_id,report_id,received,payload,digest,is_test,generated_epoch,report_type) VALUES(?,?,?,?,?,?,?,?)',(1,name,engine.utc().isoformat(),json.dumps(payload),name,0,at,'legacy')).lastrowid
    c.execute('INSERT INTO report_candidate_links VALUES(?,?,?,?,?)',(1,0,cid,row,at))
  seen=[]
  def activate(connect,uid,mode,report,candidate):seen.append((candidate['candidate_id'],report['report_id']));return {'status':'ALREADY_ACTIVE'}
  with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(engine.utc()-timedelta(minutes=1)).isoformat()}),patch('hotwatch_service.auto_activate_candidate',side_effect=activate):
   cursor=0
   for _ in range(4):cursor=auto_discover(app.connect,cursor)
  self.assertEqual(set(seen),{('A','new-A'),('B','new-B')});self.assertEqual(len(seen),2)
 def test_discovery_does_not_replay_unattempted_historical_reports_on_first_start(self):
  from hotwatch_service import auto_discover
  with app.connect() as c:
   for name,cid,offset in [('old-report','OLD',120),('latest-report','LATEST',60)]:
    at=engine.utc()-timedelta(seconds=offset);payload={'report_id':name,'candidates':[{'candidate_id':cid}]}
    row=c.execute('INSERT INTO ingested_reports(user_id,report_id,received,payload,digest,is_test,generated_epoch,report_type) VALUES(?,?,?,?,?,?,?,?)',(1,name,at.isoformat(),json.dumps(payload),name,0,at.timestamp(),'legacy')).lastrowid
    c.execute('INSERT INTO report_candidate_links VALUES(?,?,?,?,?)',(1,0,cid,row,at.timestamp()))
  seen=[]
  with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1'},clear=False),patch('hotwatch_service.auto_activate_candidate',side_effect=lambda connect,uid,mode,report,candidate:seen.append(candidate['candidate_id']) or {'status':'NOT_NEW'}):
   cursor=0
   for _ in range(4):cursor=auto_discover(app.connect,cursor)
  self.assertEqual(seen,['LATEST'])
 def test_automatic_discovery_checks_currentness_before_provider_calls(self):
  from hotwatch_service import auto_activate_candidate
  report=merc_report(False);report['report_id']='expired-candidate-before-lookup';report_ingest.save(app.connect,1,report);candidate=report['candidates'][0]
  with patch('intel_workflows.candidate_currentness',return_value={'status':'COLD'}):
   result=auto_activate_candidate(app.connect,1,False,report,candidate,lambda *_:self.fail('expired candidate must not access provider'),lambda *_:self.fail('expired candidate must not access provider'))
  self.assertEqual(result['status'],'NOT_NEW')
 def test_discovery_verifies_asset_without_assuming_trading_permission(self):
  from hotwatch_service import verified_discovery_instrument
  candidate={'asset_id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ'}
  raw={'asset':{'id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'},'buyBy':{'shares':True}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[[{'id':'synthetic-MERC','ticker':'MERC'}],raw]),patch('trade_service.fresh_permission',side_effect=AssertionError('No trading permission check for read-only monitoring')):
   self.assertEqual(verified_discovery_instrument(app.connect,1,candidate)['asset_id'],'synthetic-MERC')
 def test_discovery_uses_isin_from_exact_pluto_search_match_without_guessing(self):
  from hotwatch_service import verified_discovery_instrument
  candidate={'asset_id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ'}
  match={'id':'synthetic-MERC','ticker':'MERC','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  asset={'asset':{'id':'synthetic-MERC','ticker':'MERC'}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[[match],asset]):
   result=verified_discovery_instrument(app.connect,1,candidate)
  self.assertEqual(result['isin'],'US1234567890');self.assertEqual(result['currency'],'USD')
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[[match],{'asset':{'id':'synthetic-MERC','ticker':'MERC','currency':'EUR'}}]):
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
   root=c.execute("SELECT id FROM portfolios WHERE external_id='portfolios:root'").fetchone()['id']
   for pid in ids:
    p=c.execute('SELECT kind FROM portfolios WHERE id=?',(pid,)).fetchone();scope='DIRECT' if p['kind']=='portfolio' else 'COLLECTION'
    portfolio_data.save(c,1,pid,{'observed':engine.utc().isoformat(),'positions':[],'positions_complete':True,'positions_strict_verified':True,'positions_scope':scope,'positions_collection_ids':['child'] if scope=='DIRECT' else [],'complete':True,'value':{'value':{'amount':'1000','currency':'DKK'}},'pending_orders':[]})
  adapter=PlutoAdapter(app.connect,1)
  with patch.object(adapter,'tradability',return_value=('unknown',None)),patch.object(adapter,'inactive_orders',return_value=[]):
   result=adapter.context(self.req,'USD')
   self.assertEqual((result['status'],result['position'],result['quantity']),('verified','none','0'))
   self.assertEqual(result['portfolio_equity_dkk'],'1000')
   with patch.object(adapter,'tradability',side_effect=AssertionError('exit-only monitoring needs no buy permission')):
    exit_context=adapter.context(dict(self.req,watch_mode='exit'),'USD')
   self.assertEqual((exit_context['status'],exit_context['tradability']),('verified','unknown'))
   with app.connect() as c:
    row=c.execute('SELECT payload FROM portfolio_snapshots WHERE portfolio_id=?',(root,)).fetchone();payload=json.loads(row['payload']);payload['positions']=[{'asset_id':self.req['asset_id'],'ticker':'MERC','quantity':'2'}];c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(payload),root))
   overlap=adapter.context(self.req,'USD');self.assertEqual((overlap['status'],overlap['position'],overlap['quantity']),('verified','held','2'))
   with app.connect() as c:
    child=c.execute('SELECT id FROM portfolios WHERE kind=?',('collection',)).fetchone()['id'];saved=c.execute('SELECT payload FROM portfolio_snapshots WHERE portfolio_id=?',(child,)).fetchone();cp=json.loads(saved['payload']);cp['positions']=[{'asset_id':self.req['asset_id'],'ticker':'MERC','quantity':'3'}];c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(cp),child))
   self.assertEqual(adapter.context(self.req,'USD')['quantity'],'5')
   with app.connect() as c:
    payload['positions']=[];c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(payload),root))
   self.assertEqual(adapter.context(self.req,'USD')['quantity'],'3')
   with app.connect() as c:
    payload['positions_collection_ids']=['missing-child'];c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(payload),root))
   self.assertEqual(adapter.context(self.req,'USD')['diagnostic'],'HOLDING_SCOPE_OVERLAP')
   with app.connect() as c:
    payload['positions_collection_ids']=['child'];payload['positions_complete']=False;c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(payload),root))
   incomplete=adapter.context(self.req,'USD');self.assertEqual(incomplete['status'],'unknown');self.assertEqual(incomplete['diagnostic'],'PORTFOLIO_SNAPSHOT_INCOMPLETE')
 def test_exit_position_can_be_verified_independently_of_unrelated_snapshot_sections(self):
  import portfolios,portfolio_data
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:partial','name':'Partial','kind':'portfolio'}]);pid=portfolios.list_owned(c,1)[0]['id']
   payload={'observed':engine.utc().isoformat(),'positions':[{'kind':'holding','asset_id':self.req['asset_id'],'ticker':'MERC','quantity':'2'}],'positions_complete':True,'positions_strict_verified':True,'complete':False,'value':None,'pending_orders':[],'errors':['accounts unavailable']}
   portfolio_data.save(c,1,pid,payload)
  adapter=PlutoAdapter(app.connect,1);req=dict(self.req,portfolio_ids=[pid],watch_mode='exit')
  with patch.object(adapter,'inactive_orders',return_value=[]),patch.object(adapter,'tradability',side_effect=AssertionError('no entry permission check')),patch('portfolio_data.read',side_effect=AssertionError('fresh verified snapshot must be reused')):
   result=adapter.context(req,'USD')
  self.assertEqual((result['status'],result['position'],result['quantity']),('verified','held','2'));self.assertIsNone(result['portfolio_equity_dkk'])
  from hotwatch_strategy import risk_gate
  at=engine.utc();stale=tick(at-timedelta(seconds=121),held=True);stale['context']=result
  signal,reasons,_=risk_gate(stale,good_metrics(),req['risk'],at,'SELL')
  self.assertEqual(signal,'NO_DATA');self.assertIn('DATA_STALE',reasons)
  self.assertEqual(adapter.context(dict(req,watch_mode='entry'),'USD')['status'],'verified')
  payload['positions_complete']=False
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(json.dumps(payload),pid))
  self.assertEqual(adapter.context(req,'USD')['status'],'unknown')
 def test_exit_partial_legacy_snapshot_requires_fresh_strict_read(self):
  import portfolios,portfolio_data
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:partial','name':'Partial','kind':'portfolio'}]);pid=portfolios.list_owned(c,1)[0]['id']
   payload={'observed':engine.utc().isoformat(),'positions':[{'kind':'holding','asset_id':self.req['asset_id'],'ticker':'MERC','quantity':'2'}],'positions_complete':True,'complete':False,'value':None,'pending_orders':[]}
   portfolio_data.save(c,1,pid,payload)
  adapter=PlutoAdapter(app.connect,1);req=dict(self.req,portfolio_ids=[pid],watch_mode='exit')
  with patch('portfolio_data.read',side_effect=RuntimeError('unavailable')) as read:
   result=adapter.safe_context(req,'USD')
  self.assertEqual(result['status'],'unknown');self.assertTrue(read.call_args.kwargs['strict_positions'])
 def test_realistic_synthetic_merc_buy_noise_exit_and_history_pinning(self):
  last=None
  prices=['100' if i%2==0 else '100.5' for i in range(34)]+['100.55','100.70','100.90','101.15','101.45','101.80']
  signals=[]
  for i,price in enumerate(prices):
   at=self.now+timedelta(minutes=i);t=tick(at,i,price);t['volume']=str(100 if i<34 else 1000*2**(i-34));last=self.put(t,at);signals.append(last['calculation']['signal'])
  self.assertIn('BUY',signals);self.assertTrue(all(s in ('NO_DATA','WAIT') for s in signals[:33]));self.assertEqual(last['calculation']['strategy_checksum'],checksum(BASELINE))
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
 def test_live_session_requires_pluto_identity_gate(self):
  live=request(False)
  with patch('hotwatch_service.verified_discovery_instrument',return_value=None):
   status,result,_=self.http.request('/api/v1/hotwatch/sessions',live,self.auth)
  self.assertEqual(status,409);self.assertEqual(result['code'],'pluto_identity_unverified')
 def test_session_auth_csrf_scoping_pagination_and_management(self):
  path='/api/v1/hotwatch/sessions';self.assertEqual(self.http.request(path,self.req)[0],401);self.assertEqual(self.http.request(path,self.req,{'Cookie':self.auth['Cookie']})[0],403);status,result,_=self.http.request(path,self.req,self.auth);self.assertEqual(status,201);wid=result['session']['watch_id'];self.assertEqual(self.http.request(path,self.req,self.auth)[0],200)
  self.assertEqual(self.http.request(path+'?is_test=false',None,self.auth)[1]['sessions'],[]);self.assertEqual(len(self.http.request(path+'?is_test=true',None,self.auth)[1]['sessions']),1);self.assertEqual(self.http.request(path+'?limit=101',None,self.auth)[0],400)
  for action,status in [('pause','PAUSED'),('resume','VALIDATING'),('stop','COMPLETED')]:self.assertEqual(self.http.request(path+'/'+wid+'/'+action,{'is_test':True},self.auth)[1]['session']['status'],status)
 def test_start_candidate_endpoint_requires_auth_and_excludes_running_watch(self):
  path='/api/v1/hotwatch/start-candidates?is_test=true'
  self.assertEqual(self.http.request(path)[0],401)
  self.assertEqual(self.http.request('/api/v1/hotwatch/sessions',self.req,self.auth)[0],201)
  status,result,_=self.http.request(path,None,self.auth)
  self.assertEqual(status,200);self.assertEqual(result['already_watched'],1)
  self.assertNotIn(self.req['candidate_id'],[x['candidate']['candidate_id'] for x in result['candidates']])
 def test_api_synthetic_feed_only_and_metadata_separation(self):
  self.http.request('/api/v1/hotwatch/sessions',self.req,self.auth);wid=self.req['watch_id'];t=tick(datetime.now(timezone.utc));path='/api/v1/hotwatch/sessions/'+wid+'/samples'
  self.assertEqual(self.http.request(path,t,self.auth)[0],403);self.assertEqual(self.http.request(path+'?is_test=true',t,self.auth)[0],200);self.assertEqual(len(self.http.request(path+'?is_test=true&order=desc',None,self.auth)[1]['items']),1)
  self.assertEqual(self.http.request('/api/reports/candidate-registry?is_test=false',None,self.auth)[1]['candidates'],[]);self.assertEqual(len(self.http.request('/api/reports/candidate-registry?is_test=true',None,self.auth)[1]['candidates']),12)
 def test_strategy_upload_validates_versions_and_deferred_actions_are_explicit(self):
  d=copy.deepcopy(BASELINE);d['version']='1.1.0';path='/api/v1/hotwatch/strategies';self.assertEqual(self.http.request(path,d,self.auth)[0],201);self.assertTrue(self.http.request(path+'/'+d['strategy_id']+'/'+d['version']+'/validate',{},self.auth)[1]['valid']);self.assertEqual(self.http.request(path+'/'+d['strategy_id']+'/'+d['version']+'/activate',{},self.auth)[0],501);self.assertFalse(self.http.request(path,None,self.auth)[1]['capabilities']['shadow'])
 def test_old_report_grants_cannot_manage_or_read_engine(self):
  _,token,_=self.http.granted();access=token['access_token'];result=self.http.call(access,'start_hot_watch',self.req)[1];self.assertIn('error',result);self.assertEqual(self.http.request('/api/v1/hotwatch/sessions',None,{'Authorization':'Bearer '+access})[0],403)
 def test_report_read_grant_exposes_scoped_status_sync_without_manage_access(self):
  import mcp_reports
  engine.create(app.connect,1,self.req);_,token,_=self.http.granted('reports:read');access=token['access_token']
  self.assertIn('sync_hot_watch',{x['name'] for x in mcp_reports.tools('reports:read')})
  result=self.http.call(access,'sync_hot_watch',{'is_test':True,'session_limit':1})[1]['result'];self.assertFalse(result['isError']);body=result['structuredContent']
  self.assertEqual(body['detail_level'],'status');self.assertEqual(body['open_sessions'][0]['watch_id'],self.req['watch_id']);self.assertEqual(body['open_sessions'][0]['ticker'],'MERC');self.assertNotIn('request',body['open_sessions'][0]);self.assertIn('worker_heartbeat_fresh',body)
  self.assertEqual(self.http.call(access,'sync_hot_watch',{'is_test':False})[1]['result']['structuredContent']['open_sessions'],[])
  self.assertIn('error',self.http.call(access,'control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'stop'})[1])
 def test_mcp_start_control_read_and_strategy_admin_scope(self):
  _,token,_=self.http.granted('reports:read reports:write hotwatch:read hotwatch:manage');access=token['access_token'];result=self.http.call(access,'start_hot_watch',self.req)[1]['result'];self.assertFalse(result['isError']);self.assertEqual(result['structuredContent']['session']['status'],'CREATED')
  read=self.http.call(access,'get_hot_watch_engine',{'is_test':True})[1]['result'];self.assertEqual(len(read['structuredContent']['sessions']),1);bad=self.http.call(access,'get_hot_watch_engine',{'limit':101})[1]['result'];self.assertTrue(bad['isError'])
  stopped=self.http.call(access,'control_hot_watch',{'watch_id':self.req['watch_id'],'is_test':True,'action':'stop'})[1]['result'];self.assertFalse(stopped['isError']);self.assertEqual(stopped['structuredContent']['session']['status'],'COMPLETED')
  d=copy.deepcopy(BASELINE);d['version']='1.2.0';self.assertEqual(self.http.request('/api/v1/hotwatch/strategies',d,{'Authorization':'Bearer '+access})[0],403)

