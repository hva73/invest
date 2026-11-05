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
 def test_ambiguous_symbol_is_not_created_and_retry_is_bounded(self):
  bad=lambda *_:{'choices':[{'symbol':'ONE.US','currency':'USD','isin':'US1234567890'},{'symbol':'TWO.US','currency':'USD','isin':'US1234567890'}]}
  self.assertEqual(self.tick(verify=self.verify,lookup=bad),'EODHD_IDENTITY_UNCERTAIN')
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('retried too soon'),lookup=bad))
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
 def test_runner_starts_the_automatic_holding_loop(self):
  runner=service.Runner(app.connect);calls=[]
  def activate(connect):
   calls.append(connect);runner.stop.set()
  with patch.object(service,'auto_holdings_tick',side_effect=activate),patch.object(runner,'drain',return_value=0):runner.run(interval=0.01)
  self.assertEqual(calls,[app.connect])
 def test_full_capacity_skips_external_lookups(self):
  with patch.object(engine,'capacity',return_value=0):
   status=self.tick(verify=lambda *_:self.fail('capacity must be checked first'),lookup=self.lookup)
  self.assertEqual(status,'CAPACITY_LIMIT')
 def test_missing_feed_key_stops_before_pluto_or_eodhd_lookup(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   status=service.auto_holdings_tick(app.connect,verify=lambda *_:self.fail('must not call Pluto'),lookup=lambda *_:self.fail('must not call EODHD'),now=self.now)
  self.assertEqual(status,'EODHD_KEY_NOT_CONFIGURED')
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
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
