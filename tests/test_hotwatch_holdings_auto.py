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
 def test_reference_errors_are_specific_without_exception_content(self):
  import sqlite3
  for error,expected in [(KeyError('secret'),'REFERENCE_FIELD_MISSING'),(TypeError('secret'),'REFERENCE_TYPE_ERROR'),(ValueError('secret'),'REFERENCE_VALUE_ERROR'),(sqlite3.OperationalError('secret'),'REFERENCE_DATABASE_ERROR')]:
   self.assertEqual(service.reference_error_code(error),expected)
   self.assertNotIn('secret',service.reference_error_code(error))
 def test_saved_share_class_alias_evidence_stays_verified_and_cannot_switch_class(self):
  instrument={'asset_id':'synthetic-berkshire','ticker':'BRK.B','name':'Berkshire Hathaway Class B','exchange':'NYSE','currency':'USD','type':'CS','isin':None}
  listing={'Code':'BRK-B','Name':'Berkshire Hathaway Inc','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US0846707026'}
  choices=[{'symbol':'BRK-B.US','exchange':'US','currency':'USD','isin':'US0846707026'}]
  catalog={'received_at':self.now.isoformat(),'rows':[listing]}
  with patch('eodhd_us_reference.get_reference',return_value=catalog):evidence=service.cxe_verified_match(instrument,choices,self.now,app.connect,1)
  self.assertEqual(evidence['symbol'],'BRK-B.US')
  service.remember_verified_feed(app.connect,1,dict(instrument,isin=evidence['isin']),evidence['symbol'],self.now,cxe_evidence=evidence)
  req={'asset_id':instrument['asset_id'],'ticker':'BRK.B','exchange':'NYSE','quote_currency':'USD','provider_symbol':'BRK-B.US'}
  with app.connect() as c:
   self.assertTrue(engine.valid_cxe_evidence(c,1,req,self.now))
   self.assertFalse(engine.valid_cxe_evidence(c,1,dict(req,ticker='BRK.A'),self.now))
   self.assertFalse(engine.valid_cxe_evidence(c,1,dict(req,provider_symbol='BRK-A.US'),self.now))
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
 def test_accepted_proposal_does_not_attribute_a_preexisting_holding(self):
  import hotwatch_strategy
  entry={'asset_id':self.holding['asset_id'],'watch_mode':'entry','trade_cycle_id':'cycle-original'}
  with app.connect() as c:
   c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,'entry-origin',0,'candidate-original','automatic discovery','ACTIVE',?,'synthetic',?,'{}',?,?,0)",(json.dumps(entry),json.dumps(hotwatch_strategy.EARLY_CATALYST_V1),self.now.isoformat(),self.now.isoformat()))
   payload={'orders':[{'assetId':self.holding['asset_id'],'side':'BUY'}]}
   response={'orderIntentId':'intent-synthetic','status':'ACCEPTED'}
   c.execute("INSERT INTO broker_proposals(user_id,fingerprint,report_id,candidate_id,kind,portfolio_id,payload,status,created,intent_id,response) VALUES(1,'synthetic','@hotwatch','entry-origin','direct',?,?,'sent',?,'intent-synthetic',?)",(self.pid,json.dumps(payload),self.now.timestamp(),json.dumps(response)))
   self.assertIsNone(service.holding_origin(c,1,self.pid,self.holding['asset_id']))
   c.execute("UPDATE broker_proposals SET response=?",(json.dumps({'orderIntentId':'intent-synthetic','status':'PENDING'}),))
   self.assertIsNone(service.holding_origin(c,1,self.pid,self.holding['asset_id']))
  def read_only_check(connect,uid,proposal_id):
   with connect() as c:c.execute('UPDATE broker_proposals SET response=? WHERE id=?',(json.dumps(response),proposal_id))
  with patch('trade_service.check',side_effect=read_only_check) as check:
   service.refresh_holding_origin(app.connect,1,self.pid,self.holding['asset_id']);self.assertEqual(check.call_count,1)
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute("SELECT request FROM hw_sessions WHERE purpose='automatic holding watch'").fetchone();req=json.loads(row['request'])
   self.assertNotIn('origin_candidate_id',req);self.assertNotIn('origin_trade_cycle_id',req);self.assertEqual(req['strategy_id'],'escape_momentum');self.assertEqual(req['portfolio_ids'],[self.pid]);self.assertEqual(req['watch_mode'],'exit')
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
 def test_eodhd_budget_has_separate_default_and_respects_explicit_settings(self):
  with patch.dict(os.environ,{},clear=True):
   self.assertEqual(engine.provider_request_limit('eodhd'),30)
   self.assertEqual(engine.provider_request_limit('pluto'),12)
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'40'},clear=True):
   self.assertEqual(engine.provider_request_limit('eodhd'),40)
   self.assertEqual(engine.provider_request_limit('pluto'),12)
 def test_pluto_budget_preserves_room_for_scan_and_identity_in_either_order(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET request=json_set(request,'$.provider','pluto'),next_due=?",(self.now.timestamp(),))
   c.execute("UPDATE hw_holding_autowatch SET status='VERIFYING'")
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):
   for at,first,second in [(self.now,'scan','identity'),(self.now+timedelta(minutes=1),'identity','scan')]:
    amounts={'scan':5,'identity':7}
    for _ in range(amounts[first]):reserve(app.connect,1,'pluto',at,purpose=first)
    with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',at,purpose=first)
    for _ in range(amounts[second]):reserve(app.connect,1,'pluto',at,purpose=second)
    with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',at,purpose=second)
 def test_old_discovery_attempt_does_not_permanently_reserve_pluto_budget(self):
  with app.connect() as c:
   c.execute('INSERT INTO hw_discovery_attempts VALUES(?,?,?,?,?,?,?,?)',(1,0,'old-candidate','old-report','PROVIDER_RATE_BUDGET',self.now.isoformat(),self.now.timestamp(),None))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(12):reserve(app.connect,1,'pluto',self.now,purpose='scan')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',self.now,purpose='scan')
 def test_candidate_and_holding_checks_take_turns_when_both_wait(self):
  with app.connect() as c:
   c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','VERIFYING',None,self.now.timestamp()+300,self.now.isoformat()))
   c.execute('INSERT INTO hw_discovery_attempts VALUES(?,?,?,?,?,?,?,?)',(1,0,self.fixture.report['candidates'][0]['candidate_id'],'trade-source','PROVIDER_RATE_BUDGET',self.now.isoformat(),self.now.timestamp(),None))
  at=self.now
  if int(at.timestamp()//60)%2:at+=timedelta(minutes=1)
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):
   reserve(app.connect,1,'pluto',at,purpose='candidate_identity')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',at,purpose='holding_identity')
   at+=timedelta(minutes=1)
   reserve(app.connect,1,'pluto',at,purpose='holding_identity')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',at,purpose='candidate_identity')
 def test_candidates_waiting_for_capacity_do_not_block_existing_identity_recovery(self):
  with app.connect() as c:
   c.execute('INSERT INTO hw_discovery_attempts VALUES(?,?,?,?,?,?,?,?)',(1,0,self.fixture.report['candidates'][0]['candidate_id'],'trade-source','global_capacity_limit',self.now.isoformat(),self.now.timestamp(),None))
  at=self.now
  if int(at.timestamp()//60)%2:at+=timedelta(minutes=1)
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(12):reserve(app.connect,1,'pluto',at,purpose='holding_identity')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',at,purpose='holding_identity')
 def test_exchange_check_gets_one_reserved_call_without_increasing_budget(self):
  with app.connect() as c:c.execute('INSERT INTO hw_exchange_status(exchange,next_attempt) VALUES(?,?)',('CO',self.now.timestamp()+60))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(11):reserve(app.connect,1,'eodhd',self.now)
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now)
   reserve(app.connect,1,'eodhd',self.now,purpose='exchange_status')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now,purpose='exchange_status')
 def test_feed_recovery_has_reserved_eodhd_capacity(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT id FROM hw_sessions').fetchone()
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(row['id'],self.now.timestamp(),'PLUTO_ISIN_MISSING',self.now.isoformat()))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(10):reserve(app.connect,1,'eodhd',self.now)
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now)
   for _ in range(2):reserve(app.connect,1,'eodhd',self.now,purpose='holding_identity')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now,purpose='holding_identity')
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
 def test_reset_prioritizes_uncovered_holdings_and_retries_capacity_promptly(self):
  with app.connect() as c:
   self.assertTrue(service.pending_holding_slots(c,1,self.now))
   c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','CAPACITY_LIMIT',None,self.now.timestamp()+300,self.now.isoformat()))
  engine.reset_automatic_candidates(app.connect,1,self.now)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT next_attempt FROM hw_holding_autowatch').fetchone()[0],self.now.timestamp())
   self.assertTrue(service.pending_holding_slots(c,1,self.now))
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:self.assertFalse(service.pending_holding_slots(c,1,self.now))
 def test_candidate_waits_for_known_holding_after_reset(self):
  import report_ingest
  from test_intel_workflows import merc_report
  report=merc_report(False);report.update(report_id='priority-report',generated_at=self.now.isoformat(),positions=[],orders=[])
  candidate=report['candidates'][0];candidate.update(candidate_id='priority-scho',ticker='SCHO',company_name='Schouw & Co A/S',asset_id='priority-asset',exchange='CHIX')
  candidate['decision'].update(decided_at=self.now.isoformat(),data_as_of=self.now.isoformat(),deadline=(self.now+timedelta(hours=24)).isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,report)[1]['ok'])
  engine.reset_automatic_candidates(app.connect,1,self.now-timedelta(seconds=1))
  with patch.object(engine,'capacity',return_value=1):blocked=service.auto_activate_candidate(app.connect,1,False,report,candidate,verify=lambda *_:self.fail('last slot belongs to owned holding'))
  self.assertEqual(blocked['status'],'HOLDINGS_PRIORITY')
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  instrument={'asset_id':'priority-asset','ticker':'SCHO','name':'Schouw & Co A/S','exchange':'CHIX','currency':'DKK','type':'CS','isin':None}
  result=service.auto_activate_candidate(app.connect,1,False,report,candidate,verify=lambda *_:instrument)
  self.assertEqual(result['status'],'CREATED')
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
 def test_crypto_search_candidate_does_not_enable_unverified_price_feed(self):
  instrument={'asset_id':'synthetic-asset','ticker':'BTC','name':'Bitcoin','exchange':'WINTERMUTE','currency':'USD','type':'CRYPTO','isin':None}
  holding=dict(self.holding,ticker='BTC',name='Bitcoin')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  choices={'choices':[{'symbol':'BTC-USD.CC','name':'Bitcoin','exchange':'CC','currency':'USD','isin':None}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()['request'])['provider'],'pluto')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_verified_feed_links').fetchone()[0],0)
 def test_owner_approved_btc_mapping_preserves_two_depots_and_existing_history(self):
  from test_hotwatch_engine import tick
  from hotwatch_adapters import EODHDAdapter
  aid='54368e0b-2d53-401e-bf68-1033a5b84b08';instrument={'asset_id':aid,'ticker':'BTC','name':'Bitcoin','type':'CRYPTO','exchange':'WINTERMUTE','currency':'USD','isin':None}
  quantities={self.fixture.root:'0.00019026',self.fixture.child:'0.0001914'}
  with app.connect() as c:
   for pid,qty in quantities.items():
    data={'positions_complete':True,'complete':True,'observed':self.now.isoformat(),'positions':[{'kind':'holding','asset_id':aid,'ticker':'BTC','name':'Bitcoin','quantity':qty}]}
    import portfolio_data
    portfolio_data.save(c,1,pid,data)
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  with app.connect() as c:
   before=c.execute('SELECT * FROM hw_sessions ORDER BY id').fetchall();self.assertEqual(len(before),2)
   for row in before:
    s=tick(self.now-timedelta(seconds=20),held=True);s.update(source='pluto',asset_id=aid,ticker='BTC',sample_id='historical-'+str(row['id']),market_status='UNKNOWN',session_key='legacy',bid=None,ask=None)
    c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],'pluto',s['sample_id'],(self.now-timedelta(seconds=20)).timestamp(),self.now.isoformat(),json.dumps(s),engine.checksum(s)))
    c.execute('UPDATE hw_sessions SET last_data=? WHERE id=?',(s['event_time'],row['id']))
  quote={'status':'OK','price':'75946.0234375','event_time':(self.now-timedelta(seconds=10)).isoformat()}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('eodhd_feeds.EODHDFeeds.snapshot',return_value=quote):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),2)
  with app.connect() as c:
   after=c.execute('SELECT * FROM hw_sessions ORDER BY id').fetchall();self.assertEqual([r['watch_id'] for r in after],[r['watch_id'] for r in before])
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],2)
   self.assertEqual(c.execute('SELECT count(*) FROM hw_verified_feed_links').fetchone()[0],1)
   self.assertEqual({tuple(json.loads(r['request'])['portfolio_ids']) for r in after},{(self.fixture.root,),(self.fixture.child,)})
   for row in after:
    req=json.loads(row['request']);self.assertEqual(req['provider_symbol'],'BTC-USD.CC');self.assertTrue(engine.valid_cxe_evidence(c,1,req,self.now))
   with patch.dict(os.environ,{'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'0','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_FUSE_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'30'}):
    self.assertEqual(engine.effective_poll_interval(c,req),60)
    self.assertEqual(engine.effective_poll_interval(c,dict(req,asset_id='other-asset')),300)
    self.assertEqual(req['risk']['max_quote_age_s'],120)
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):return json.dumps({'code':'BTC-USD','timestamp':int(self.now.timestamp())-10,'close':'75946.0234375','currency':'USD'}).encode()
  outer=self
  class Opener:
   def open(self,*args,**kwargs):
    response=Response();response.now=outer.now;return response
  adapter=EODHDAdapter(app.connect,1,Opener())
  def context(req,currency):
   ctx=tick(self.now,held=True)['context'];ctx['quantity']=quantities[req['portfolio_ids'][0]];return ctx
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic','ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'0','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'30','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}),patch('hotwatch_adapters.reserve'),patch.object(adapter.pluto,'safe_context',side_effect=context):
   for row in after:
    req=json.loads(row['request']);sample=adapter.poll({'id':row['id'],'request_data':req,'state':row['state']})
    self.assertEqual(sample['currency'],'USD');self.assertEqual(sample['context']['quantity'],quantities[req['portfolio_ids'][0]])
    out=engine.ingest(app.connect,1,row['watch_id'],False,sample,self.now)
    self.assertEqual(out['calculation']['signal'],'NO_DATA')
    self.assertEqual(out['session']['display_status'],'KURS MODTAGET · MARKEDSSTATUS UKENDT')
    self.assertEqual(out['session']['effective_min_interval_s'],60)
    self.assertEqual((engine.stamp(out['session']['next_due_at'])-self.now).total_seconds(),60)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],4)
   import dashboard_projection
   for row in after:
    pid=json.loads(row['request'])['portfolio_ids'][0]
    displayed=dashboard_projection.position_hotwatch(c,1,pid,aid,None)['session']
    self.assertEqual(displayed['display_status'],'WARMUP');self.assertEqual(displayed['warmup']['count'],1);self.assertTrue(displayed['warmup']['market_status_unknown']);self.assertNotIn('historical',displayed['warmup'])
  from hotwatch_warmup import refresh
  end=self.now.replace(second=0,microsecond=0)
  bars=[{'bar_open_at':(end-timedelta(minutes=34-i)).isoformat(),'open':'100','high':'102','low':'99','close':'101','volume':'20'} for i in range(34)]
  class History:
   def intraday(self,symbol,interval,start,end):
    self.assertion=(symbol,interval);return {'status':'OK','bars':bars}
  feed=History();job=dict(after[-1]);job['request_data']=json.loads(job['request'])
  from unittest.mock import Mock
  runner=service.Runner(app.connect);adapter_stub=Mock();adapter_stub.poll.return_value=sample;runner.adapters[(1,'eodhd')]=adapter_stub;runner.health=Mock();runner.log=Mock()
  runner_job=dict(job,lease_owner='test-lease')
  with patch('hotwatch_service.engine.claim',return_value=runner_job),patch('hotwatch_service.engine.ingest',return_value={'calculation':{'signal':'NO_DATA'}}),patch('hotwatch_warmup.refresh') as refresh_call:
   self.assertTrue(runner.once(self.now));self.assertEqual(refresh_call.call_count,1)
  class ChangingIdentity:
   def intraday(self,symbol,interval,start,end):
    with app.connect() as c:c.execute('UPDATE hw_verified_feed_links SET verified_epoch=verified_epoch+1 WHERE asset_id=?',(aid,))
    return {'status':'OK','bars':bars}
  self.assertIsNone(refresh(app.connect,job,self.now,ChangingIdentity()))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_warmup_history').fetchone()[0],0)
   c.execute('UPDATE hw_verified_feed_links SET verified_epoch=verified_epoch-1 WHERE asset_id=?',(aid,))
  self.assertEqual(refresh(app.connect,job,self.now,feed),'OK');self.assertEqual(feed.assertion,('BTC-USD.CC','1m'))
  with app.connect() as c:
   current=c.execute('SELECT * FROM hw_sessions WHERE id=?',(job['id'],)).fetchone();view=engine.view(c,current,self.now);warm=view['data_status']['analysis_warmup']
   self.assertEqual(warm['state'],'WARMUP COMPLETE');self.assertEqual(warm['count'],34);self.assertEqual(warm['freshness'],'FRESH');self.assertIsNotNone(warm['metrics']['ema_long']);self.assertEqual(view['signal'],'NO_DATA')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],4)
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
   displayed=dashboard_projection.position_hotwatch(c,1,json.loads(job['request'])['portfolio_ids'][0],aid,None)['session'];self.assertTrue(displayed['warmup']['complete']);self.assertTrue(displayed['warmup']['market_status_unknown'])
  class WrongSymbol:
   def intraday(self,symbol,interval,start,end):return {'status':'OK','bars':[dict(bars[-1],symbol='OTHER-USD.CC')]}
  self.assertEqual(refresh(app.connect,job,self.now+timedelta(seconds=301),WrongSymbol()),'NO_VALID_BARS')
  with app.connect() as c:
   saved=c.execute('SELECT bars,status FROM hw_warmup_history WHERE watch_row_id=?',(job['id'],)).fetchone();self.assertEqual(len(json.loads(saved['bars'])),34);self.assertEqual(saved['status'],'NO_VALID_BARS')
  class PartialHistory:
   def intraday(self,symbol,interval,start,end):return {'status':'OK','bars':bars[-3:]}
  partial_job=dict(after[0]);partial_job['request_data']=json.loads(partial_job['request'])
  self.assertEqual(refresh(app.connect,partial_job,self.now,PartialHistory()),'OK')
  with app.connect() as c:
   for i in (1,2):
    at=end+timedelta(minutes=i);live=dict(sample,event_time=at.isoformat(),sample_id='future-fixture-'+str(i),price='102')
    c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(partial_job['id'],'eodhd',live['sample_id'],at.timestamp(),at.isoformat(),json.dumps(live),engine.checksum(live)))
   current=c.execute('SELECT * FROM hw_sessions WHERE id=?',(partial_job['id'],)).fetchone()
   from hotwatch_warmup import status as warmup_status
   partial=warmup_status(c,current,partial_job['request_data'],end+timedelta(minutes=2,seconds=1))
   self.assertEqual(partial['count'],5);self.assertEqual(partial['state'],'WARMUP');self.assertEqual(partial['remaining'],29)
  with app.connect() as c:
   current=c.execute('SELECT * FROM hw_sessions WHERE id=?',(after[-1]['id'],)).fetchone();stale=engine.view(c,current,self.now+timedelta(seconds=131))
   self.assertEqual(stale['data_status']['quote_freshness'],'STALE');self.assertEqual(stale['signal'],'NO_DATA')
   c.execute('DELETE FROM hw_cxe_feed_evidence')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch.object(adapter.pluto,'safe_context',return_value=tick(self.now,held=True)['context']):
   with self.assertRaisesRegex(DataUnavailable,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):adapter.poll({'id':after[-1]['id'],'request_data':req,'state':after[-1]['state']})
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):engine.ingest(app.connect,1,after[-1]['watch_id'],False,sample,self.now)
 def test_pepe_is_a_provisional_reference_and_cannot_use_external_prices(self):
  aid='4cde5f75-df03-4abc-9063-cfc588e31c11';instrument={'asset_id':aid,'ticker':'PEPE','name':'Pepe','type':'CRYPTO','exchange':'UKENDT','currency':'USD','isin':None}
  with app.connect() as c:
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[{'kind':'holding','asset_id':aid,'ticker':'PEPE','quantity':'1'}]}),))
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('eodhd_feeds.EODHDFeeds.snapshot',side_effect=AssertionError('PEPE must not use external quotes')):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();self.assertEqual(json.loads(row['request'])['provider'],'pluto')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_verified_feed_links').fetchone()[0],0)
  data=engine.item(app.connect,1,row['watch_id'],False)['session']['data_status'];self.assertEqual(data['reference_candidate']['symbol'],'PEPE24478-USD.CC');self.assertFalse(data['reference_candidate']['verified'])
  with app.connect() as c:
   req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='PEPE24478-USD.CC');c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(req),row['id']))
  from hotwatch_warmup import refresh
  pepe_job=dict(row);pepe_job['request_data']=req
  self.assertIsNone(refresh(app.connect,pepe_job,self.now,client=object()))
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_UNVERIFIED'):engine.ingest(app.connect,1,row['watch_id'],False,{},self.now)
 def test_complete_broker_identity_does_not_spend_second_lookup_for_missing_isin(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','name':'Test Inc','exchange':'NASDAQ','currency':'USD','type':'CS'}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw) as call:
   instrument=service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'))
  self.assertIsNone(instrument['isin']);self.assertEqual(instrument['type'],'CS');self.assertEqual(call.call_count,1)
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
 def test_pluto_nested_isin_is_used_only_when_unambiguous(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ','currency':'USD','identifiers':[{'type':'ISIN','value':'US1234567890'}]}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw):
   self.assertEqual(service.holding_instrument(app.connect,1,self.holding)['isin'],'US1234567890')
  raw['asset']['isin']='US9999999999';diagnostic={}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw):
   self.assertIsNone(service.holding_instrument(app.connect,1,self.holding,diagnostic))
  self.assertEqual(diagnostic['code'],'PLUTO_ASSET_METADATA_MISSING')
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
 def test_empty_automatic_session_recovers_only_from_recent_verified_identity(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   old=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(old['request']);req.update(watch_mode='entry',purpose='candidate',watch_id='historical-candidate',candidate_id='historical-candidate')
   c.execute("UPDATE hw_sessions SET watch_id=?,candidate_id=?,purpose=?,request=?,status='COMPLETED' WHERE id=?",('historical-candidate','historical-candidate','candidate',json.dumps(req),old['id']))
   c.execute('DELETE FROM hw_holding_autowatch')
   sample={'verification':'verified','asset_id':'synthetic-asset','ticker':'TEST','currency':'USD'}
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(old['id'],'eodhd','evidence',self.now.timestamp(),self.now.isoformat(),json.dumps(sample),'digest'))
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=None):
   with app.connect() as c:c.execute('DELETE FROM hw_verified_feed_links')
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   service.remember_verified_feed(app.connect,1,self.instrument,'TEST.US',self.now)
   with app.connect() as c:c.execute("UPDATE hw_verified_feed_links SET verified_epoch=?",((self.now-timedelta(days=8)).timestamp(),))
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   with app.connect() as c:
    c.execute("UPDATE hw_verified_feed_links SET verified_epoch=?,currency='EUR'",(self.now.timestamp(),))
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   with app.connect() as c:
    c.execute("UPDATE hw_verified_feed_links SET currency='USD'")
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   row=c.execute("SELECT * FROM hw_sessions WHERE purpose='automatic holding watch'").fetchone();req=json.loads(row['request'])
   self.assertEqual((req['provider'],req['provider_symbol']),('eodhd','TEST.US'))
   self.assertEqual(c.execute("SELECT count(*) FROM hw_events WHERE watch_row_id=? AND event_type='PROVIDER_CHANGED'",(row['id'],)).fetchone()[0],1)
 def test_feed_recovery_chooses_oldest_due_attempt_before_session_id(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   first=dict(c.execute('SELECT * FROM hw_sessions').fetchone());first_id=first.pop('id')
   req=json.loads(first['request']);req.update(asset_id='synthetic-second',ticker='SECOND',watch_id='second-watch',candidate_id='second-candidate')
   first.update(watch_id='second-watch',candidate_id='second-candidate',request=json.dumps(req),digest='second-digest')
   cols=list(first);c.execute('INSERT INTO hw_sessions('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',tuple(first.values()))
   second_id=c.execute("SELECT id FROM hw_sessions WHERE watch_id='second-watch'").fetchone()['id']
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(first_id,self.now.timestamp()-1,'PROVIDER_RATE_BUDGET',self.now.isoformat()))
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(second_id,self.now.timestamp()-120,'PROVIDER_RATE_BUDGET',self.now.isoformat()))
  seen=[]
  def check(connect,uid,holding):seen.append(holding['ticker']);return None
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',side_effect=check):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  self.assertEqual(seen,['SECOND'])
 def test_recovery_matches_isin_and_currency_without_prior_observation(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  choices={'choices':[{'symbol':'TEST.US','isin':self.instrument['isin'],'currency':'USD'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=self.instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT request FROM hw_sessions').fetchone();self.assertEqual(json.loads(row['request'])['provider_symbol'],'TEST.US')
 def test_recovery_does_not_guess_ambiguous_isin_match(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  choices={'choices':[{'symbol':'TEST.US','isin':self.instrument['isin'],'currency':'USD'},{'symbol':'TEST.X','isin':self.instrument['isin'],'currency':'USD'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=self.instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_feed_recovery').fetchone()['status'],'EODHD_IDENTITY_UNCERTAIN')
   self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()['request'])['provider'],'pluto')
 def test_recovery_reports_missing_isin_without_guessing(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  instrument=dict(self.instrument,isin=None)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=AssertionError('cannot match without ISIN')):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_feed_recovery').fetchone()['status'],'PLUTO_ISIN_MISSING')
 def test_provisional_match_requires_unique_issuer_ticker_currency_and_market(self):
  novo={'ticker':'NOVOB','name':'Novo Nordisk A/S','currency':'DKK','exchange':'CHIX'}
  choices=[{'symbol':'NVO.US','name':'Novo Nordisk A/S','exchange':'US','currency':'USD'},{'symbol':'NOVO-B.CO','name':'Novo Nordisk A/S','exchange':'CO','currency':'DKK'}]
  self.assertEqual(service.provisional_feed_match(novo,choices)['symbol'],'NOVO-B.CO')
  tsm={'ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Ltd.','currency':'USD','exchange':'NYSE'}
  us={'symbol':'TSM.US','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD'}
  self.assertEqual(service.provisional_feed_match(tsm,[us])['symbol'],'TSM.US')
  self.assertIsNone(service.provisional_feed_match(tsm,[us,dict(us)]))
  self.assertIsNone(service.provisional_feed_match(tsm,[dict(us,name='Different Company')]))
  self.assertIsNone(service.provisional_feed_match(tsm,[dict(us,currency='EUR')]))
  self.assertIsNone(service.provisional_feed_match(dict(tsm,exchange='UKENDT'),[us]))
  self.assertIsNone(service.provisional_feed_match(dict(tsm,ticker='TSMA'),[us]))
  asml={'ticker':'ASML','name':'ASML Holding NV','currency':'EUR','exchange':'CHIX'}
  amsterdam={'symbol':'ASML.AS','name':'ASML Holding NV','exchange':'AS','currency':'EUR'}
  frankfurt={'symbol':'ASML.F','name':'ASML Holding NV','exchange':'F','currency':'EUR'}
  self.assertEqual(service.provisional_feed_match(asml,[amsterdam])['symbol'],'ASML.AS')
  self.assertIsNone(service.provisional_feed_match(asml,[amsterdam,frankfurt]))
 def test_provisional_quote_is_visible_but_cannot_generate_a_signal_or_false_stop(self):
  from test_hotwatch_engine import tick
  holding=dict(self.holding,ticker='TSM')
  with app.connect() as c:
   payload={'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps(payload),))
  instrument={'asset_id':'synthetic-asset','ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Ltd.','exchange':'NYSE','currency':'USD','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  choices={'choices':[{'symbol':'TSM.US','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='TSM.US');req['risk']['stop_price']='105';c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(req),row['id']))
   c.execute('INSERT INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],'TSM.US',json.dumps({'pluto_venue':'NYSE','eodhd_venue':'US'}),self.now.isoformat()))
   self.assertEqual(req['provider_symbol'],'TSM.US')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links WHERE watch_row_id=?',(row['id'],)).fetchone()[0],1)
  from hotwatch_adapters import EODHDAdapter,unknown_context
  calls=[]
  class Feed:
   def snapshot(self,symbol):calls.append(symbol);return {'status':'OK','event_time':self_now.isoformat(),'price':'100','volume':None}
   def capture(self,*args,**kwargs):raise AssertionError('unverified source must use one snapshot')
  self_now=self.now;adapter=EODHDAdapter(app.connect,1)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch.object(adapter,'feeds',return_value=Feed()),patch.object(adapter.pluto,'context',return_value=unknown_context()):
   with self.assertRaisesRegex(DataUnavailable,'EODHD_INSTRUMENT_UNVERIFIED'):
    adapter.poll({'id':row['id'],'request_data':req,'state':'{}'})
  self.assertEqual(calls,[])
  sample=tick(self.now,1,price='100',held=True)
  sample.update(source='eodhd',ticker='TSM',asset_id='synthetic-asset',market_status='UNKNOWN',session_key='test:UNKNOWN',feed_type='synthetic EODHD snapshot',bid=None,ask=None)
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_UNVERIFIED'):
   engine.ingest(app.connect,1,req['watch_id'],False,sample,self.now)
  # Simulate an already persisted observation from an older installed version.
  sample['verification']='unverified'
  with app.connect() as c:
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],'eodhd',sample['sample_id'],self.now.timestamp(),self.now.isoformat(),json.dumps(sample),engine.checksum(sample)))
   c.execute('UPDATE hw_sessions SET last_data=? WHERE id=?',(self.now.isoformat(),row['id']))
   stored=json.loads(c.execute('SELECT payload FROM hw_samples').fetchone()['payload'])
  result=engine.item(app.connect,1,req['watch_id'],False)
  self.assertEqual(stored['verification'],'unverified')
  self.assertEqual(result['session']['signal'],'NO_DATA')
  self.assertIn('DATA_UNVERIFIED',result['session']['display_reason_codes'])
  self.assertIsNone(result['session']['data_status']['price'])
  self.assertEqual(result['session']['data_status']['price_status'],'UNVERIFIED')
  self.assertEqual(result['session']['display_status'],'KURSKILDE IKKE BEKRÆFTET')
  import dashboard_projection
  with app.connect() as c:
   position=dashboard_projection.position_hotwatch(c,1,self.pid,'synthetic-asset',None)
  self.assertEqual(position['session']['display_status'],'KURSKILDE IKKE BEKRÆFTET')
  self.assertIsNone(position['session']['warmup'])
  synced=engine.sync(app.connect,1,False,summary_only=True)
  self.assertEqual(synced['open_sessions'][0]['identity_verification'],'unverified')
  self.assertEqual(synced['open_sessions'][0]['last_data_at'],self.now.isoformat())
  verified=dict(instrument,isin='US1234567890');check_at=self.now+timedelta(minutes=6)
  with app.connect() as c:c.execute('UPDATE hw_feed_recovery SET next_attempt=0')
  wrong={'choices':[{'symbol':'DIFFERENT.US','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD','isin':'US1234567890'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=verified),patch('hotwatch_adapters.search_eodhd_symbols',return_value=wrong):
   self.assertEqual(service.verify_provisional_feeds(app.connect,check_at),0)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links').fetchone()[0],1)
   recovery=c.execute('SELECT next_attempt FROM hw_feed_recovery').fetchone()
   self.assertEqual(recovery['next_attempt'],check_at.timestamp()+300)
   # Existing installations may still have a six-hour retry from older code.
   c.execute("UPDATE hw_feed_recovery SET next_attempt=?,status='CXE_REFERENCE_INVALID'",(check_at.timestamp()+21600,))
  right={'choices':[{'symbol':'TSM.US','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD','isin':'US1234567890'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=verified),patch('hotwatch_adapters.search_eodhd_symbols',return_value=right):
   self.assertEqual(service.verify_provisional_feeds(app.connect,check_at+timedelta(minutes=4)),0)
   self.assertEqual(service.verify_provisional_feeds(app.connect,check_at+timedelta(minutes=6)),1)
  self.assertEqual(engine.sync(app.connect,1,False,summary_only=True)['open_sessions'][0]['identity_verification'],'unverified')
  at=check_at+timedelta(minutes=7);new_sample=tick(at,2,price='101',held=True)
  new_sample.update(source='eodhd',ticker='TSM',asset_id='synthetic-asset',market_status='UNKNOWN',session_key='test:UNKNOWN',feed_type='synthetic EODHD snapshot',bid=None,ask=None)
  refreshed=engine.ingest(app.connect,1,req['watch_id'],False,new_sample,at)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],2)
   self.assertEqual(json.loads(c.execute('SELECT payload FROM hw_samples ORDER BY id DESC LIMIT 1').fetchone()['payload'])['verification'],'verified')
  self.assertEqual(refreshed['calculation']['supporting_metrics']['sample_count'],1)
  self.assertEqual(engine.sync(app.connect,1,False,summary_only=True)['open_sessions'][0]['identity_verification'],'verified')
 def test_asml_cxe_recovery_revalidates_and_blocks_changed_identity(self):
  holding=dict(self.holding,ticker='ASML')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  instrument={'asset_id':'synthetic-asset','ticker':'ASML','name':'ASML Holding NV','exchange':'CHIX','currency':'EUR','type':'CS','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  with app.connect() as c:before=c.execute('SELECT watch_id FROM hw_sessions').fetchone()['watch_id']
  from cxe_reference import parse_reference
  raw=('environment=PROD,created='+self.now.strftime('%Y-%m-%d')+',time='+self.now.strftime('%H:%MZ')+',warning=\n'
       'company_name,bats_name,isin,currency,mic,bloomberg_primary,asset_class,live,corporate_action_status\n'
       'ASML Holding NV,ASMLa,NL0010273215,EUR,XAMS,ASML NA Equity,EQTY,t,\n').encode()
  reference=parse_reference(raw,self.now)
  choices={'choices':[{'symbol':'ASML.AS','exchange':'AS','currency':None,'isin':'NL0010273215'},{'symbol':'ASML.F','exchange':'F','currency':'EUR','isin':'NL0010273215'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',return_value=reference):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);self.assertEqual(row['watch_id'],before);self.assertEqual(req['provider_symbol'],'ASML.AS')
   evidence=c.execute('SELECT * FROM hw_cxe_feed_evidence').fetchone();self.assertEqual(evidence['status'],'MATCHED');self.assertEqual(json.loads(evidence['payload'])['isin'],'NL0010273215');self.assertEqual(json.loads(evidence['payload'])['currency_basis'],'cxe_primary_listing')
   c.execute('UPDATE hw_cxe_feed_evidence SET next_attempt=0')
  from test_hotwatch_engine import tick
  sample=tick(self.now,1,held=True);sample.update(source='eodhd',ticker='ASML',asset_id='synthetic-asset',currency='EUR',venue='EODHD:AS',market_status='UNKNOWN',feed_type='synthetic EODHD quote',bid=None,ask=None)
  engine.ingest(app.connect,1,before,False,sample,self.now)
  state=engine.item(app.connect,1,before,False)['session']['data_status']
  self.assertEqual((state['holding_verified'],state['instrument_match_verified'],state['quote_feed_verified'],state['quote_freshness']),(True,True,True,'FRESH'))
  with app.connect() as c:
   original=c.execute('SELECT payload FROM hw_cxe_feed_evidence').fetchone()['payload'];tampered=json.loads(original);tampered['pluto']['currency']='USD'
   c.execute('UPDATE hw_cxe_feed_evidence SET payload=?',(json.dumps(tampered),))
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):
   engine.ingest(app.connect,1,before,False,dict(sample,sample_id='tampered-evidence'),self.now)
  with app.connect() as c:c.execute('UPDATE hw_cxe_feed_evidence SET payload=?',(original,))
  from cxe_reference import ReferenceUnavailable
  with patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',side_effect=ReferenceUnavailable('CXE_REFERENCE_UNAVAILABLE')):
   self.assertEqual(service.verify_cxe_feeds(app.connect,self.now+timedelta(minutes=1)),0)
  with app.connect() as c:
   retry=c.execute('SELECT status,payload FROM hw_cxe_feed_evidence').fetchone();self.assertEqual(retry['status'],'MATCHED');self.assertEqual(json.loads(retry['payload'])['last_revalidation_error'],'CXE_REFERENCE_UNAVAILABLE')
   c.execute('UPDATE hw_cxe_feed_evidence SET next_attempt=0')
  with patch('hotwatch_service.holding_instrument',return_value=dict(instrument,type='ADRC')),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.verify_cxe_feeds(app.connect,self.now+timedelta(minutes=1)),0)
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_cxe_feed_evidence').fetchone()['status'],'CONFLICT')
  failed=engine.item(app.connect,1,before,False)['session'];self.assertFalse(failed['data_status']['instrument_match_verified']);self.assertFalse(failed['data_status']['quote_feed_verified']);self.assertEqual(failed['signal'],'NO_DATA')
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):
   engine.ingest(app.connect,1,before,False,dict(sample,sample_id='inflight-after-conflict'),self.now+timedelta(minutes=1))
  from hotwatch_adapters import EODHDAdapter,unknown_context
  adapter=EODHDAdapter(app.connect,1)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch.object(adapter.pluto,'context',return_value=unknown_context()):
   with self.assertRaisesRegex(DataUnavailable,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):adapter.poll({'id':row['id'],'request_data':req,'state':'{}'})
 def test_observed_fcx_recovery_uses_exact_pluto_asset_and_catalog(self):
  aid='bea4a183-d3aa-4893-8071-87b85385e281';holding=dict(self.holding,asset_id=aid,ticker='FCX')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  instrument={'asset_id':aid,'ticker':'FCX','name':'Freeport-McMoran Inc.','exchange':'NYSE','currency':'USD','type':'CS','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  catalog={'received_at':self.now.isoformat(),'rows':[{'Code':'FCX','Name':'Freeport-McMoran Copper & Gold Inc','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US35671D8570'}]}
  choices={'choices':[{'symbol':'FCX.US','exchange':'US','currency':'USD','isin':'US35671D8570'},{'symbol':'FCX.MX','exchange':'MX','currency':'MXN','isin':None}]}
  with app.connect() as c:before=c.execute('SELECT watch_id FROM hw_sessions').fetchone()['watch_id']
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('eodhd_us_reference.get_reference',return_value=catalog):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();request=json.loads(row['request']);self.assertEqual(row['watch_id'],before);self.assertEqual(request['provider_symbol'],'FCX.US')
   self.assertTrue(engine.valid_cxe_evidence(c,1,request,self.now))
   c.execute('INSERT INTO hw_exchange_status(exchange,received,is_open,next_attempt) VALUES(?,?,?,?)',('US',self.now.isoformat(),0,self.now.timestamp()+300))
   view=engine.view(c,row,self.now);self.assertEqual(view['display_status'],'MARKED LUKKET (ORDINÆR HANDEL)');self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['data_status']['price'])
  from hotwatch_warmup import refresh
  end=self.now.replace(second=0,microsecond=0)
  bars=[{'bar_open_at':(end-timedelta(minutes=34-i)).isoformat(),'open':'100','high':'102','low':'99','close':'101','volume':'20'} for i in range(34)]
  class Feed:
   def intraday(self,symbol,interval,start,end):return {'status':'OK','bars':bars}
  job=dict(row);job['request_data']=request;self.assertEqual(refresh(app.connect,job,self.now,Feed()),'OK')
  with app.connect() as c:
   actual=c.execute('SELECT * FROM hw_sessions WHERE id=?',(row['id'],)).fetchone();view=engine.view(c,actual,self.now)
   self.assertEqual(view['data_status']['analysis_warmup']['state'],'WARMUP COMPLETE');self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['latest_calculation'])
 def test_tsm_adr_recovers_from_us_catalog_and_preserves_adr_evidence(self):
  holding=dict(self.holding,ticker='TSM')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  instrument={'asset_id':'synthetic-asset','ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Ltd.','exchange':'NYSE','currency':'USD','type':'ADRC','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  reference={'created_at':self.now.isoformat(),'rows':[{'symbol':'TSFAd','name':'Taiwan Semiconductor Manufacturing Co Ltd','isin':'US8740391003','currency':'EUR','instrument_type':'EQTY','mic':'XFRA'}]}
  catalog={'received_at':self.now.isoformat(),'rows':[{'Code':'TSM','Name':'Taiwan Semiconductor Manufacturing','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US8740391003'}]}
  choices={'choices':[{'symbol':'TSM.US','exchange':'US','currency':'USD','isin':'US8740391003'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',side_effect=AssertionError('US listing must not depend on Cboe')),patch('eodhd_us_reference.get_reference',return_value=catalog):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();request=json.loads(row['request']);self.assertEqual(request['provider_symbol'],'TSM.US')
   evidence=json.loads(c.execute('SELECT payload FROM hw_cxe_feed_evidence').fetchone()['payload']);self.assertEqual(evidence['pluto_type'],'ADRC');self.assertEqual(evidence['catalog_type'],'Common Stock');self.assertIn('ADR',evidence['type_note'])
  current=engine.item(app.connect,1,row['watch_id'],False)['session']['data_status']
  self.assertTrue(current['instrument_match_verified']);self.assertEqual(current['identity_verification'],'verified');self.assertFalse(current['quote_feed_verified'])
  reused=service.verified_existing_feed(app.connect,1,{'asset_id':'synthetic-asset','ticker':'TSM','currency':'USD'},self.now)
  self.assertEqual(reused['provider_symbol'],'TSM.US')
  self.assertIsNone(service.verified_existing_feed(app.connect,1,{'asset_id':'synthetic-asset','ticker':'TSM','currency':'EUR'},self.now))
  with app.connect() as c:
   original=c.execute('SELECT payload FROM hw_cxe_feed_evidence').fetchone()['payload'];legacy=json.loads(original)
   legacy.update(basis='pluto_asset_us_catalog_cxe_security_isin',reference_source='https://accounteu.cboe.com/cxe/market_data/symbol_listing/csv/',reference_created_at=(self.now-timedelta(days=5)).isoformat(),cxe_symbols=['TSFAd'])
   c.execute('UPDATE hw_cxe_feed_evidence SET payload=?',(json.dumps(legacy),))
  self.assertTrue(engine.item(app.connect,1,row['watch_id'],False)['session']['data_status']['instrument_match_verified'])
  with app.connect() as c:c.execute('UPDATE hw_cxe_feed_evidence SET payload=?',(original,))
  from test_hotwatch_engine import tick
  sample=tick(self.now,1,held=True);sample.update(source='eodhd',ticker='TSM',asset_id='synthetic-asset',currency='USD',venue='EODHD:US',market_status='UNKNOWN',feed_type='synthetic EODHD quote',bid=None,ask=None)
  engine.ingest(app.connect,1,row['watch_id'],False,sample,self.now)
  status=engine.sync(app.connect,1,False,summary_only=True)['open_sessions'][0]
  self.assertTrue(status['instrument_match_verified']);self.assertTrue(status['quote_feed_verified']);self.assertEqual(status['instrument_match_evidence']['pluto_type'],'ADRC')
  self.assertEqual(status['status'],'DEGRADED')
  calculation=engine.item(app.connect,1,row['watch_id'],False)['session']['latest_calculation']
  self.assertEqual(calculation['signal'],'NO_DATA');self.assertIn('MARKET_STATUS_UNKNOWN',calculation['reason_codes'])
 def test_existing_novob_provisional_is_rechecked_without_losing_history(self):
  holding=dict(self.holding,ticker='NOVOB')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  instrument={'asset_id':'synthetic-asset','ticker':'NOVOB','name':'Novo Nordisk A/S','exchange':'CHIX','currency':'DKK','type':'CS','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='NOVO-B.CO')
   c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(req),row['id']))
   c.execute('INSERT INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],'NOVO-B.CO','{}',self.now.isoformat()))
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(row['id'],self.now.timestamp()+21600,'PLUTO_ISIN_MISSING',self.now.isoformat()))
  reference={'created_at':self.now.isoformat(),'rows':[{'symbol':'NOVOBc','primary_ticker':'NOVOB','name':'Novo Nordisk A/S','isin':'DK0062498333','currency':'DKK','instrument_type':'EQTY','mic':'XCSE'}]}
  choices={'choices':[{'symbol':'NOVO-B.CO','exchange':'CO','currency':'DKK','isin':'DK0062498333'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',return_value=reference):
   self.assertEqual(service.verify_provisional_feeds(app.connect,self.now),1)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT watch_id FROM hw_sessions').fetchone()['watch_id'],row['watch_id'])
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT isin FROM hw_verified_feed_links').fetchone()['isin'],'DK0062498333')
   self.assertTrue(c.execute("SELECT 1 FROM hw_events WHERE event_type='INSTRUMENT_VERIFIED'").fetchone())
 def test_recovery_respects_global_and_user_kill_switches(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',side_effect=AssertionError('must not call provider')):
   with app.connect() as c:c.execute('UPDATE hw_system_control SET killed=1 WHERE id=1')
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   with app.connect() as c:
    c.execute('UPDATE hw_system_control SET killed=0 WHERE id=1')
    c.execute("INSERT INTO hw_control VALUES(1,1,'test',?) ON CONFLICT(user_id) DO UPDATE SET killed=1",(self.now.isoformat(),))
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
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
 def test_budget_blocked_broker_context_does_not_discard_timestamped_price(self):
  from hotwatch_adapters import PlutoAdapter
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:req=json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()['request'])
  quote={'asset_id':'synthetic-asset','ticker':'TEST','currency':'USD','exchange':'NASDAQ','price':'100','price_time':self.now.isoformat()}
  with patch('market_data.quote',return_value=quote),patch.object(PlutoAdapter,'context',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429)):
   sample=PlutoAdapter(app.connect,1).poll({'request_data':req})
  self.assertEqual(sample['price'],'100');self.assertEqual(sample['event_time'],self.now.isoformat())
  self.assertEqual(sample['context']['status'],'unknown');self.assertEqual(sample['context']['tradability'],'unknown')
  self.assertEqual(sample['context']['diagnostic'],'PROVIDER_RATE_BUDGET')
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
