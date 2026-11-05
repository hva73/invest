"""Automatic holding watches use synthetic owned snapshots and no provider calls."""
import json,os,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,hotwatch_engine as engine,hotwatch_service as service
from hotwatch_adapters import reserve,DataUnavailable
import test_trade_service as fixtures

class HoldingAutowatch(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.Trading();self.fixture.setUp();self.pid=self.fixture.root
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.holding={'kind':'holding','asset_id':'synthetic-asset','ticker':'TEST','name':'Test Company','quantity':'1'}
  with app.connect() as c:
   data={'positions_complete':True,'observed':self.now.isoformat(),'positions':[self.holding]}
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(self.pid,1,self.now.isoformat(),json.dumps(data),self.now.isoformat()))
  self.instrument={'asset_id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  self.verify=lambda *_:self.instrument
  self.lookup=lambda *_:{'choices':[{'symbol':'TEST.US','currency':'USD','isin':'US1234567890'}]}
 def tearDown(self):self.fixture.tearDown()
 def tick(self,**kwargs):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_CAPACITY':'40','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}):return service.auto_holdings_tick(app.connect,now=self.now,**kwargs)
 def test_verified_holding_creates_exit_only_session_and_never_restarts_stopped(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute("SELECT * FROM hw_sessions WHERE purpose='automatic holding watch'").fetchone();data=json.loads(row['request'])
   self.assertEqual(data['watch_mode'],'exit');self.assertEqual(data['portfolio_ids'],[self.pid]);self.assertEqual(data['provider_symbol'],'TEST.US')
   import dashboard_projection
   link=dashboard_projection.position_hotwatch(c,1,self.pid,self.holding['asset_id'],{'candidate_id':'other-candidate','trade_cycle_id':'other-cycle'})
   self.assertEqual(link['session']['watch_id'],row['watch_id']);self.assertEqual(link['link_basis'],'unique_asset_and_portfolio_scope')
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
  engine.control(app.connect,1,row['watch_id'],False,'stop',self.now)
  self.assertIsNone(self.tick(verify=self.verify,lookup=self.lookup))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_holding_autowatch').fetchone()[0],'STOPPED')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],1)
 def test_entry_only_watch_does_not_replace_position_monitoring(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT id,request FROM hw_sessions').fetchone();req=json.loads(row['request']);req['watch_mode']='entry';req['watch_id']='manual-entry-only';req['candidate_id']='manual-candidate';req['purpose']='manual entry'
   c.execute('UPDATE hw_sessions SET watch_id=?,candidate_id=?,purpose=?,request=? WHERE id=?',('manual-entry-only','manual-candidate','manual entry',json.dumps(req),row['id']))
   c.execute('DELETE FROM hw_holding_autowatch')
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   modes=[json.loads(row['request'])['watch_mode'] for row in c.execute('SELECT request FROM hw_sessions')]
  self.assertEqual(sorted(modes),['entry','exit'])
 def test_manual_pause_is_preserved(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:wid=c.execute('SELECT watch_id FROM hw_sessions').fetchone()[0]
  engine.control(app.connect,1,wid,False,'pause',self.now)
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('paused watch must not be replaced'),lookup=self.lookup))
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_sessions').fetchone()[0],'PAUSED')
 def test_exit_watch_ends_only_on_fresh_complete_absence_and_reopens_on_new_holding(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   old=c.execute('SELECT watch_id FROM hw_sessions').fetchone()[0]
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':False,'observed':self.now.isoformat(),'positions':[]}),))
  self.assertEqual(service.reconcile_closed_holdings(app.connect,self.now),0)
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[]}),))
  self.assertEqual(service.reconcile_closed_holdings(app.connect,self.now),1)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_sessions WHERE watch_id=?',(old,)).fetchone()[0],'COMPLETED')
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[self.holding]}),))
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   sessions=c.execute('SELECT watch_id,status FROM hw_sessions ORDER BY id').fetchall();self.assertEqual(len(sessions),2);self.assertNotEqual(sessions[0]['watch_id'],sessions[1]['watch_id'])
 def test_ambiguous_eodhd_symbol_uses_verified_pluto_instead(self):
  bad=lambda *_:{'choices':[{'symbol':'ONE.US','currency':'USD','isin':'US1234567890'},{'symbol':'TWO.US','currency':'USD','isin':'US1234567890'}]}
  self.assertEqual(self.tick(verify=self.verify,lookup=bad),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT request FROM hw_sessions').fetchone();self.assertEqual(json.loads(row['request'])['provider'],'pluto')
 def test_failed_incomplete_or_stale_scope_does_not_start(self):
  with app.connect() as c:c.execute("UPDATE portfolio_snapshots SET last_error='unavailable'")
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('must not look up'),lookup=self.lookup))
  with app.connect() as c:c.execute("UPDATE portfolio_snapshots SET last_error=NULL,payload=?",(json.dumps({'positions_complete':False,'positions':[self.holding]}),))
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('must not look up'),lookup=self.lookup))
 def test_identity_reserves_two_calls_without_increasing_shared_limit(self):
  with app.connect() as c:c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','VERIFYING',None,self.now.timestamp()+300,self.now.isoformat()))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(10):reserve(app.connect,1,'eodhd',self.now)
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now)
   for _ in range(2):reserve(app.connect,1,'eodhd',self.now,purpose='holding_identity')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now,purpose='holding_identity')
 def test_exchange_check_gets_one_reserved_call_without_increasing_budget(self):
  with app.connect() as c:c.execute('INSERT INTO hw_exchange_status(exchange,next_attempt) VALUES(?,?)',('CO',self.now.timestamp()+60))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(11):reserve(app.connect,1,'eodhd',self.now)
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now)
   reserve(app.connect,1,'eodhd',self.now,purpose='exchange_status')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now,purpose='exchange_status')
 def test_runner_starts_the_automatic_holding_loop(self):
  runner=service.Runner(app.connect);calls=[]
  def activate(connect):
   calls.append(connect);runner.stop.set()
  with patch.object(service,'exchange_status_tick',return_value=None),patch.object(service,'auto_holdings_tick',side_effect=activate),patch.object(runner,'drain',return_value=0):runner.run(interval=0.01)
  self.assertEqual(calls,[app.connect])
 def test_full_capacity_skips_external_lookups(self):
  with patch.object(engine,'capacity',return_value=0):
   status=self.tick(verify=lambda *_:self.fail('capacity must be checked first'),lookup=self.lookup)
  self.assertEqual(status,'CAPACITY_LIMIT')
 def test_missing_eodhd_key_uses_verified_pluto_without_eodhd_lookup(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   status=service.auto_holdings_tick(app.connect,verify=self.verify,lookup=lambda *_:self.fail('must not call EODHD'),now=self.now)
  self.assertEqual(status,'LINKED')
  with app.connect() as c:self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()[0])['provider'],'pluto')
 def test_missing_isin_does_not_prevent_verified_pluto_identity(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ','currency':'USD'}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw):
   instrument=service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'))
  self.assertIsNone(instrument['isin']);self.assertEqual(instrument['asset_id'],'synthetic-asset')
  self.assertEqual(self.tick(verify=lambda *_:instrument,lookup=lambda *_:self.fail('No ISIN means no automatic EODHD match')),'LINKED')
  with app.connect() as c:self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()[0])['provider'],'pluto')
 def test_missing_exchange_is_recovered_only_from_same_pluto_asset_id(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','currency':'USD'}}
  matches=[{'id':'another-asset','ticker':'TEST','exchange':'OTHER','currency':'USD'},{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ','currency':'USD'}]
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,matches]):
   instrument=service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'))
  self.assertEqual(instrument['exchange'],'NASDAQ');self.assertEqual(instrument['asset_id'],'synthetic-asset')
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,matches[:1]]):
   self.assertEqual(service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'))['exchange'],'UKENDT')
 def test_flat_pluto_asset_format_and_unknown_exchange_still_allow_position_monitoring(self):
  raw={'assetId':'synthetic-asset','ticker':'TEST','currency':'USD'}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,[]]):
   instrument=service.holding_instrument(app.connect,1,self.holding)
  self.assertEqual(instrument['asset_id'],'synthetic-asset');self.assertEqual(instrument['exchange'],'UKENDT')
  self.assertEqual(self.tick(verify=lambda *_:instrument,lookup=lambda *_:self.fail('No verified ISIN')),'LINKED')
  with app.connect() as c:self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()[0])['provider'],'pluto')
 def test_identity_diagnostics_explain_missing_and_conflicting_currency(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ'}};diagnostic={}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,[]]):self.assertIsNone(service.holding_instrument(app.connect,1,self.holding,diagnostic))
  self.assertEqual(diagnostic['code'],'PLUTO_CURRENCY_MISSING')
  diagnostic={};raw['asset']['currency']='EUR'
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,[]]):self.assertIsNone(service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'),diagnostic))
  self.assertEqual(diagnostic['code'],'PLUTO_CURRENCY_MISMATCH')
  diagnostic={}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value={'assetId':'different-asset','ticker':'TEST','currency':'USD'}):self.assertIsNone(service.holding_instrument(app.connect,1,self.holding,diagnostic))
  self.assertEqual(diagnostic['code'],'PLUTO_ASSET_ID_MISMATCH')
 def test_holding_worker_records_specific_failure_without_fabricating_a_session(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ'}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,[]]):
   self.assertEqual(self.tick(),'PLUTO_CURRENCY_MISSING')
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_holding_autowatch').fetchone()[0],'PLUTO_CURRENCY_MISSING')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
 def test_verified_existing_candidate_feed_creates_separate_holding_watch(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(watch_mode='entry',purpose='candidate',watch_id='existing-candidate',candidate_id='existing-candidate')
   c.execute('UPDATE hw_sessions SET watch_id=?,candidate_id=?,purpose=?,request=? WHERE id=?',('existing-candidate','existing-candidate','candidate',json.dumps(req),row['id']))
   c.execute('DELETE FROM hw_holding_autowatch')
   sample={'verification':'verified','asset_id':'synthetic-asset','ticker':'TEST','currency':'USD'}
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],'eodhd','identity-evidence',self.now.timestamp(),self.now.isoformat(),json.dumps(sample),'digest'))
  with patch('hotwatch_service.holding_instrument',side_effect=AssertionError('reuse existing verified identity')),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=AssertionError('reuse existing verified feed')):
   self.assertEqual(self.tick(),'LINKED')
  with app.connect() as c:
   requests=[json.loads(r['request']) for r in c.execute('SELECT request FROM hw_sessions ORDER BY id')]
  self.assertEqual([r['watch_mode'] for r in requests],['entry','exit']);self.assertEqual(requests[1]['provider_symbol'],'TEST.US')
 def test_rate_budget_retry_waits_until_next_minute_not_five_minutes(self):
  def blocked(*_):raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
  self.assertEqual(self.tick(verify=self.verify,lookup=blocked),'PROVIDER_RATE_BUDGET')
  with app.connect() as c:row=c.execute('SELECT next_attempt FROM hw_holding_autowatch').fetchone()
  self.assertGreater(row['next_attempt'],self.now.timestamp());self.assertLessEqual(row['next_attempt']-self.now.timestamp(),61)
 def test_existing_budget_delay_is_shortened_safely_on_startup(self):
  with app.connect() as c:c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','PROVIDER_RATE_BUDGET',None,self.now.timestamp()+300,self.now.isoformat()))
  with patch('hotwatch_engine.utc',return_value=self.now):app.init()
  with app.connect() as c:row=c.execute('SELECT status,next_attempt FROM hw_holding_autowatch').fetchone()
  self.assertEqual(row['status'],'PROVIDER_RATE_BUDGET');self.assertGreater(row['next_attempt'],self.now.timestamp());self.assertLessEqual(row['next_attempt']-self.now.timestamp(),61)
 def test_old_identity_failures_retry_promptly_after_upgrade(self):
  with app.connect() as c:c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','IDENTITY_UNVERIFIED',None,self.now.timestamp()+300,self.now.isoformat()))
  with patch('hotwatch_engine.utc',return_value=self.now):app.init()
  with app.connect() as c:row=c.execute('SELECT status,next_attempt FROM hw_holding_autowatch').fetchone()
  self.assertEqual(row['status'],'IDENTITY_UNVERIFIED');self.assertEqual(row['next_attempt'],self.now.timestamp()+10)
 def test_pluto_fallback_reads_exact_owned_position_and_source_time(self):
  from hotwatch_adapters import PlutoAdapter,unknown_context
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request'])
  quote={'asset_id':'synthetic-asset','ticker':'TEST','currency':'USD','exchange':'NASDAQ','price':'100','price_time':self.now.isoformat()}
  with patch('market_data.quote',return_value=quote) as get_quote,patch.object(PlutoAdapter,'context',return_value=unknown_context()):
   sample=PlutoAdapter(app.connect,1).poll({'request_data':req})
  self.assertEqual(sample['source'],'pluto');self.assertEqual(sample['event_time'],self.now.isoformat());self.assertEqual(get_quote.call_args.args[2],{'holding_portfolio_id':self.pid,'holding_asset_id':'synthetic-asset'})
 def test_old_snapshot_is_not_used(self):
  with app.connect() as c:
   payload={'positions_complete':True,'observed':(self.now-timedelta(minutes=6)).isoformat(),'positions':[self.holding]}
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps(payload),))
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('stale snapshot'),lookup=self.lookup))
 def test_global_kill_and_disabled_setting_prevent_activation(self):
  with app.connect() as c:c.execute('UPDATE hw_system_control SET killed=1 WHERE id=1')
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('kill switch'),lookup=self.lookup))
  with app.connect() as c:c.execute('UPDATE hw_system_control SET killed=0 WHERE id=1')
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'0'}):self.assertIsNone(service.auto_holdings_tick(app.connect,verify=lambda *_:self.fail('disabled'),lookup=self.lookup,now=self.now))
 def test_existing_watch_is_reused_and_kill_switch_respected(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('duplicate lookup'),lookup=self.lookup))
  with app.connect() as c:
   c.execute("INSERT INTO hw_control VALUES(1,1,'stop',?) ON CONFLICT(user_id) DO UPDATE SET killed=1",(self.now.isoformat(),))
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('kill switch'),lookup=self.lookup))
