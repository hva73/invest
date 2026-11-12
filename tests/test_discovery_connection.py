"""Synthetic discovery handoff and provider failures; no broker writes."""
import os,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,report_ingest,hotwatch_engine as engine,hotwatch_service as service,trade_service
from hotwatch_adapters import DataUnavailable
from test_intel_workflows import merc_report
import test_trade_service as fixtures

class DiscoveryConnection(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.Trading();self.fixture.setUp();self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.report=merc_report(False);self.report.update(report_id='synthetic-discovery-connection',generated_at=self.now.isoformat(),positions=[],orders=[])
  self.candidate=self.report['candidates'][0];self.candidate.update(candidate_id='synthetic-candidate',ticker='TEST',company_name='Test Company',asset_id='synthetic-asset',exchange='NASDAQ')
  self.candidate['decision'].update(decided_at=self.now.isoformat(),data_as_of=self.now.isoformat(),deadline=(self.now+timedelta(hours=24)).isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,self.report)[1]['ok'])
 def tearDown(self):self.fixture.tearDown()
 def test_budget_retry_reuses_catalog_but_rechecks_identity(self):
  calls=[];first=[True]
  def request(client,method,params=None,notification=False):
   name=(params or {}).get('name');calls.append((method,name))
   if method=='initialize':return {'protocolVersion':'2025-06-18'}
   if method=='notifications/initialized':return None
   if method=='tools/list':return {'tools':[{'name':name,'inputSchema':spec['inputSchema'],'annotations':{'readOnlyHint':spec['readOnlyHint']}} for name,spec in trade_service.CONTRACT.items()]}
   if name=='search_assets':return {'structuredContent':{'assets':[{'id':'synthetic-asset','ticker':'TEST','name':'Test Company','exchange':'NASDAQ','currency':'USD'}]}}
   if name=='get_asset':
    if first[0]:first[0]=False;raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
    return {'structuredContent':{'asset':{'id':'synthetic-asset','ticker':'TEST','name':'Test Company','exchange':'NASDAQ','currency':'USD','type':'CS','isin':'US1234567890'}}}
   raise AssertionError(name)
  cache={};env={'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(self.now-timedelta(minutes=1)).isoformat()}
  with patch.dict(os.environ,env),patch('mcp_client.MCP.request',request),patch('hotwatch_adapters.reserve'),patch('hotwatch_engine.utc',return_value=self.now):
   service.auto_discover(app.connect,identity_cache=cache)
  with app.connect() as c:
   row=c.execute('SELECT status,watch_id FROM hw_discovery_attempts WHERE candidate_id=?',(self.candidate['candidate_id'],)).fetchone()
   self.assertEqual((row['status'],row['watch_id']),('PROVIDER_RATE_BUDGET',None))
  with patch.dict(os.environ,env),patch('mcp_client.MCP.request',request),patch('hotwatch_adapters.reserve'),patch('hotwatch_engine.utc',return_value=self.now+timedelta(seconds=61)):
   service.auto_discover(app.connect,identity_cache=cache)
  with app.connect() as c:
   row=c.execute('SELECT status,watch_id FROM hw_discovery_attempts WHERE candidate_id=?',(self.candidate['candidate_id'],)).fetchone()
   self.assertEqual(row['status'],'CREATED');self.assertIsNotNone(row['watch_id'])
  self.assertEqual(calls.count(('initialize',None)),1);self.assertEqual(calls.count(('tools/list',None)),1)
  self.assertEqual(calls.count(('tools/call','search_assets')),2);self.assertEqual(calls.count(('tools/call','get_asset')),2)
  self.assertFalse(self.fixture.writes())
  session=engine.item(app.connect,1,row['watch_id'],False)['session']
  self.assertIsNone(session['last_data_at']);self.assertNotEqual(session['signal'],'BUY')
 def test_budget_failure_keeps_only_complete_gateway(self):
  from hotwatch_adapters import PlutoAdapter
  for catalog,keep in [(None,False),([{'name':'synthetic'}],True)]:
   with self.subTest(keep=keep):
    adapter=PlutoAdapter(app.connect,1);gateway=type('Gateway',(),{'catalog':catalog})();adapter.gateway=gateway
    with patch('hotwatch_service.verified_discovery_instrument',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429)):
     result=service.auto_activate_candidate(app.connect,1,False,self.report,self.candidate,identity_adapter=adapter)
    self.assertEqual(result['status'],'PROVIDER_RATE_BUDGET');self.assertIs(adapter.gateway,gateway if keep else None)
  adapter=PlutoAdapter(app.connect,1);adapter.gateway=type('Gateway',(),{'catalog':[{'name':'synthetic'}]})()
  with patch('hotwatch_service.verified_discovery_instrument',side_effect=ConnectionError('synthetic')):
   result=service.auto_activate_candidate(app.connect,1,False,self.report,self.candidate,identity_adapter=adapter)
  self.assertEqual(result['status'],'DISCOVERY_VERIFICATION_FAILED');self.assertIsNone(adapter.gateway)
 def test_discovery_connections_are_separate_per_user_and_expire(self):
  with app.connect() as c:c.execute("INSERT INTO users(username,salt,hash) VALUES('other','synthetic','synthetic')")
  self.assertTrue(report_ingest.save(app.connect,2,self.report)[1]['ok'])
  expired=object();cache={1:(0,expired)};seen=[]
  def activate(connect,uid,mode,report,candidate,identity_adapter=None):
   seen.append((uid,identity_adapter));return {'status':'PROVIDER_RATE_BUDGET'}
  env={'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(self.now-timedelta(minutes=1)).isoformat()}
  with patch.dict(os.environ,env),patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_service.time.monotonic',return_value=300),patch('hotwatch_service.auto_activate_candidate',side_effect=activate):
   service.auto_discover(app.connect,identity_cache=cache)
  self.assertEqual({uid for uid,_ in seen},{1,2});self.assertIsNot(cache[1][1],expired);self.assertIsNot(cache[1][1],cache[2][1])
 def test_discovery_cache_does_not_bypass_kill_switch(self):
  with app.connect() as c:c.execute('UPDATE hw_system_control SET killed=1 WHERE id=1')
  cache={};env={'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':(self.now-timedelta(minutes=1)).isoformat()}
  with patch.dict(os.environ,env),patch('hotwatch_engine.utc',return_value=self.now),patch('hotwatch_adapters.PlutoAdapter.factory',side_effect=AssertionError('kill switch must prevent broker access')):
   service.auto_discover(app.connect,identity_cache=cache)
  with app.connect() as c:
   row=c.execute('SELECT status,watch_id FROM hw_discovery_attempts WHERE candidate_id=?',(self.candidate['candidate_id'],)).fetchone()
  self.assertEqual((row['status'],row['watch_id']),('operator_kill_switch',None));self.assertFalse(self.fixture.writes())
