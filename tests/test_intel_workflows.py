"""V2.2 synthetic acceptance scenarios. All databases are disposable."""
import copy,hashlib,json,tempfile,unittest
from unittest.mock import patch
import app,report_ingest,report_validation,mcp_reports,intel_workflows as flow,report_v2
from test_position_reports import full_positions

AT='2026-11-03T10:00:00Z'
def decision(status='AFVENT',at=AT):
 return {'status':status,'decided_at':at,'reason':'SYNTHETISK beslutning, ikke et råd','next_trigger':'Dokumenteret ny meddelelse','deadline':'2099-11-03T11:00:00Z','data_as_of':at,'source_ids':['synthetic-source'],'reactivation_reason':None,'buy_plan':None}
def merc_report(mode=False):
 d=full_positions('SYNTHETIC-MERC-BASE',AT);d['is_test']=mode;c=d['candidates'][0];c.update(ticker='MERC',company_name='SYNTHETISK MERC-ACCEPTTEST',decision=decision());p=d['positions'][0];p.update(ticker='MERC',candidate_id=c['candidate_id'],asset_id='synthetic-MERC',quantity='10',cost_basis={'amount':'70','currency':'USD'})
 d['orders']=[{'order_id':'synthetic-merc-stop','portfolio_id':p['portfolio_id'],'candidate_id':c['candidate_id'],'ticker':'MERC','status':'ACCEPTED','lifecycle':'pending','requested_quantity':'10','filled_quantity':'0','allocated':None,'as_of':AT,'source_ids':['synthetic-source'],'note':'SYNTHETISK; ingen ordre sendt','side':'SELL','order_type':'STOP','stop_price':{'amount':'6','currency':'USD'},'execution_source':'pluto','average_fill_price':None}]
 return d

def observation(report=None,oid='SYNTHETIC-MERC-OBS-1',at='2026-11-03T10:05:00Z'):
 r=report or merc_report();return {'observation_id':oid,'report_id':r['report_id'],'candidate_id':r['candidates'][0]['candidate_id'],'is_test':r['is_test'],'observed_at':at,'deadline':'2099-11-03T11:00:00Z','instrument':{'ticker':'MERC','exchange':'NASDAQ','asset_id':'synthetic-MERC'},'market':{'price':{'amount':'7.5','currency':'USD'},'price_at':at,'bid':{'amount':'7.4','currency':'USD'},'bid_at':at,'ask':{'amount':'7.6','currency':'USD'},'ask_at':at,'spread':{'amount':'0.2','currency':'USD'},'spread_percent':'2.6667','volume':'1000','volume_at':at,'volume_basis':'session cumulative · synthetic','intraday_percent':'1.5','momentum':'unknown','venue':'SYNTHETIC','feed_type':'synthetic fixture','delay_seconds':None,'verification':'verified','price_source':'pluto','source_ids':['synthetic-source']},'recent_trades':[],'decision':None,'next_trigger':'Syntetisk nyhedskontrol','position_ref':{'portfolio_id':'test-main','position_id':'test-main.TSLA'},'order_ids':['synthetic-merc-stop'],'position_action':None,'sources':copy.deepcopy(r['sources']),'note':'KUN SYNTETISK ACCEPTTEST I MIDLERTIDIG DATABASE. Ingen reel MERC-kurs eller handel.'}

class Workflows(unittest.TestCase):
 def setUp(self):
  self.old=app.DB;self.temp=tempfile.TemporaryDirectory();app.DB=self.temp.name+'/db';app.init();app.create_user('test-password-long-enough');self.r=merc_report();report_ingest.save(app.connect,1,self.r)
 def tearDown(self):app.DB=self.old;self.temp.cleanup()
 def check(self,d):
  with app.connect() as c:return flow.validate_observation(d,c,1)
 def snapshot(self):
  with app.connect() as c:return list(c.iterdump())
 def test_old_v1_v2_and_production_check_immutable(self):
  from test_report_delivery import synthetic
  d=synthetic(True);d['report_id']='escape-v2-production-check-001';report_ingest.save(app.connect,1,d)
  with app.connect() as c:before=tuple(c.execute('SELECT payload,digest FROM ingested_reports WHERE report_id=?',(d['report_id'],)).fetchone())
  app.init();flow.record(app.connect,1,observation(self.r))
  with app.connect() as c:self.assertEqual(before,tuple(c.execute('SELECT payload,digest FROM ingested_reports WHERE report_id=?',(d['report_id'],)).fetchone()))
  self.assertEqual(report_ingest.item(app.connect,1,d['report_id'],True)['report']['data'],d)
 def test_wait_is_active_reject_dormant_reactivation_requires_reason(self):
  self.assertTrue(any(x['candidate']['ticker']=='MERC' for x in report_ingest.desk(app.connect,1)['candidates']))
  rejected=copy.deepcopy(self.r);rejected.update(report_id='synthetic-rejected',generated_at='2026-11-03T10:10:00Z');rejected['candidates'][0]['decision']=decision('FRAVÆLG',rejected['generated_at']);report_ingest.save(app.connect,1,rejected)
  desk=report_ingest.desk(app.connect,1);self.assertFalse(any(x['candidate']['ticker']=='MERC' for x in desk['candidates']));self.assertEqual(desk['dormant_candidates'][0]['candidate']['candidate_id'],self.r['candidates'][0]['candidate_id'])
  again=copy.deepcopy(rejected);again.update(report_id='synthetic-reactivated',generated_at='2026-11-03T10:20:00Z');again['candidates'][0]['decision']=decision('AFVENT',again['generated_at']);self.assertIn('reactivation_evidence_required',{e['code'] for e in report_ingest.validation(app.connect,1,again)['errors']})
  again['candidates'][0]['decision']['reactivation_reason']='Syntetisk ny officiel katalysator';report_ingest.save(app.connect,1,again);self.assertEqual(len(report_ingest.desk(app.connect,1)['dormant_candidates']),0)
 def test_legacy_signal_does_not_override_documented_wait(self):
  new=copy.deepcopy(self.r);new.update(report_id='new-legacy-buy',generated_at='2026-11-03T10:30:00Z');del new['candidates'][0]['decision'];new['candidates'][0]['signal']='KØB';report_ingest.save(app.connect,1,new)
  c=next(x for x in report_ingest.desk(app.connect,1)['candidates'] if x['candidate']['ticker']=='MERC');self.assertEqual(c['decision']['status'],'AFVENT')
 def test_malformed_buy_plan_returns_diagnostics_without_crashing(self):
  d=copy.deepcopy(self.r);d['candidates'][0]['decision']['buy_plan']={'amount_dkk':['bad']};checked=report_ingest.validation(app.connect,1,d);self.assertFalse(checked['valid']);self.assertIn('candidates[0].decision.buy_plan.amount_dkk',{e['path'] for e in checked['errors']})
 def test_buy_requires_complete_plan_and_dkk(self):
  d=copy.deepcopy(self.r);d['report_id']='buy';d['candidates'][0]['decision']['status']='KØB';self.assertFalse(report_ingest.validation(app.connect,1,d)['valid'])
  plan={'max_limit_price':{'amount':'7','currency':'USD'},'amount_dkk':{'amount':'500','currency':'DKK'},'horizon':'2 dage','expires_at':'2026-11-03T11:00:00Z','risk_budget':{'amount':'50','currency':'DKK'},'upside':'10% syntetisk','downside':'5% syntetisk','exit_method':'Syntetisk exitregel','approval':'awaiting_approval'};d['candidates'][0]['decision'].update(buy_plan=plan,decided_at='2026-11-03T10:01:00Z');d['generated_at']='2026-11-03T10:01:00Z';self.assertTrue(report_ingest.validation(app.connect,1,d)['valid']);plan['amount_dkk']['currency']='USD';self.assertFalse(report_ingest.validation(app.connect,1,d)['valid'])
 def test_same_decision_time_conflicts_and_identical_events_deduplicate(self):
  d=copy.deepcopy(self.r);d['report_id']='repeat-decision';report_ingest.save(app.connect,1,d)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM candidate_decision_events').fetchone()[0],1)
  d['report_id']='conflict-decision';d['candidates'][0]['decision']['reason']='changed';self.assertIn('decision_conflict',{e['code'] for e in report_ingest.validation(app.connect,1,d)['errors']})
 def test_candidate_omitted_from_new_report_remains_active(self):
  new=copy.deepcopy(self.r);new.update(report_id='omitted',generated_at='2026-11-03T10:30:00Z');new['candidates']=[]
  report_ingest.save(app.connect,1,new);self.assertTrue(any(x['candidate']['ticker']=='MERC' for x in report_ingest.desk(app.connect,1)['candidates']))
 def test_hot_watch_merc_timeline_no_duplicate_candidates_or_mutated_reports(self):
  before=copy.deepcopy(self.r);a=observation(self.r);self.assertEqual(flow.record(app.connect,1,a)[0],201);self.assertTrue(flow.record(app.connect,1,a)[1]['duplicate'])
  b=observation(self.r,'SYNTHETIC-MERC-OBS-2','2026-11-03T10:10:00Z');b['market']['price']['amount']='8';b['market']['spread']['amount']='0.1';b['market']['ask']['amount']='7.5';b['market']['volume']='1400';b['market']['momentum']='accelerating';b['position_action']={'action':'SÆLG','reason':'Syntetisk salgsbeslutning; ikke udført','assessed_at':b['observed_at'],'source_ids':['synthetic-source']};flow.record(app.connect,1,b)
  groups=flow.watch(app.connect,1)['groups'];self.assertEqual(len(groups),1);g=groups[0];self.assertEqual(len(g['observations']),2);self.assertEqual(g['observations'][0]['changes']['price']['amount'],'0.5');self.assertEqual(g['observations'][0]['changes']['volume'],'400');self.assertEqual(g['orders'][0]['filled_quantity'],'0');self.assertIn('ingen bekræftet fyldning',g['orders'][0]['display_status']);self.assertEqual(g['positions'][0]['quantity'],'10');self.assertEqual(report_ingest.latest(app.connect,1)['report']['data'],before)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(DISTINCT candidate_id) FROM report_candidate_links').fetchone()[0],12)
 def test_observation_conflict_atomic_and_account_mode_isolated(self):
  d=observation(self.r);flow.record(app.connect,1,d);before=self.snapshot();d['note']='changed';self.assertEqual(flow.record(app.connect,1,d)[0],409);self.assertEqual(before,self.snapshot());self.assertEqual(flow.watch(app.connect,1,True)['groups'],[]);self.assertEqual(flow.watch(app.connect,2)['groups'],[])
  d['is_test']=True;self.assertIn('unknown_reference',{e['code'] for e in self.check(d)['errors']})
 def test_validation_is_select_only_all_structural_errors(self):
  d=observation(self.r);del d['market']['price_at'];d['market']['volume']=3;d['market']['delay_seconds']=-1;before=self.snapshot();v=self.check(d);self.assertFalse(v['valid']);self.assertGreaterEqual(len(v['errors']),3);self.assertEqual(before,self.snapshot())
 def test_invalid_references_and_unknown_data(self):
  d=observation(self.r);d['order_ids']=['missing'];d['position_ref']['portfolio_id']='other';d['market']['source_ids']=['missing'];self.assertGreaterEqual(len(self.check(d)['errors']),3)
  d=observation(self.r);m=d['market'];m.update({k:None for k in ['price','price_at','bid','bid_at','ask','ask_at','spread','spread_percent','volume','volume_at','intraday_percent']});m.update(verification='unknown',source_ids=[]);self.assertTrue(self.check(d)['valid']);flow.record(app.connect,1,d);self.assertIsNone(flow.watch(app.connect,1)['groups'][0]['observations'][0]['changes']['price'])
 def test_quantity_authority_and_order_lifecycle(self):
  o=copy.deepcopy(self.r['orders'][0]);self.assertIn('ingen bekræftet fyldning',flow.order_state(o));o.update(lifecycle='filled',filled_quantity='0');self.assertNotEqual(flow.order_state(o),'Fuldt udført');o.update(lifecycle='partial',filled_quantity='4');self.assertEqual(flow.order_state(o),'Delvist udført');o.update(lifecycle='filled',filled_quantity='10',status='FILLED');self.assertEqual(flow.order_state(o),'Fuldt udført');o.update(filled_quantity='0',status='EXPIRED');self.assertEqual(flow.order_state(o),'Udløbet')
 def test_consolidation_requires_identical_times_currency_and_method(self):
  r=copy.deepcopy(self.r);root,ai=r['portfolios'];root.update(value={'amount':'1000','currency':'DKK'},includes_collections=True,valuation_method='same-provider');ai.update(value={'amount':'200','currency':'DKK'},valuation_method='same-provider');p=flow.account_projection({'data':r});self.assertEqual(p['main_ex_ai']['amount'],'800');self.assertEqual(p['root']['value']['amount'],'1000')
  for field,value in [('valuation_method',None),('as_of','2026-11-03T09:59:00Z'),('value',{'amount':'200','currency':'USD'})]:
   bad=copy.deepcopy(r);bad['portfolios'][1][field]=value;self.assertIsNone(flow.account_projection({'data':bad})['main_ex_ai'])
 def test_delivery_requires_actual_readback_and_payload_unchanged(self):
  with app.connect() as c:
   row=c.execute('SELECT * FROM ingested_reports').fetchone();self.assertEqual(flow.delivery(c,row['id'])['status'],'stored');before=(row['payload'],row['digest'])
  report_ingest.item(app.connect,1,self.r['report_id'],record_readback=True)
  with app.connect() as c:self.assertEqual(flow.delivery(c,row['id'])['status'],'readback_verified');self.assertEqual(before,tuple(c.execute('SELECT payload,digest FROM ingested_reports').fetchone()))
 def test_coverage_and_schema_match(self):
  d=copy.deepcopy(self.r);d['report_id']='coverage';d['summary']['regions']=[{'region':r,'summary':'SYNTHETISK','source_ids':['synthetic-source'],'coverage':{'exchanges':[],'status':'IKKE KØRT','screening_count':None,'data_at':None,'news_checked_at':None,'new_signals':None,'pluto_verified':None,'excluded':None,'gaps':['Syntetisk dækningshul'],'basis':'unknown'}} for r in ['Europa / Norden','USA / Canada','Asien / Stillehav','Råvarer / Metaller']];self.assertTrue(report_ingest.validation(app.connect,1,d)['valid']);d['summary']['regions'][0]['coverage']['screening_count']=-1;self.assertFalse(report_ingest.validation(app.connect,1,d)['valid'])
 def test_verified_price_retained_when_later_observation_is_unknown(self):
  flow.record(app.connect,1,observation(self.r));unknown=observation(self.r,'synthetic-unknown','2026-11-03T10:10:00Z');m=unknown['market'];m.update({k:None for k in ['price','price_at','bid','bid_at','ask','ask_at','spread','spread_percent','volume','volume_at','intraday_percent']});m.update(verification='unknown',source_ids=[]);flow.record(app.connect,1,unknown)
  with app.connect() as c:record=flow.candidates(c,1,False,self.r['candidates'][0]['candidate_id'])[0]
  self.assertEqual(record['last_seen'],unknown['observed_at']);self.assertEqual(record['latest_verified_market']['price']['amount'],'7.5');self.assertEqual(record['latest_verified_market']['as_of'],'2026-11-03T10:05:00Z')
 def test_asset_identity_spread_and_future_evidence_rejected(self):
  d=observation(self.r);d['instrument']['asset_id']='wrong-asset';d['market']['spread']['amount']='0.1';d['market']['price_at']='2026-11-03T12:00:00Z';codes={e['code'] for e in self.check(d)['errors']};self.assertTrue({'identity_mismatch','inconsistent_spread','future_evidence'}<=codes)
 def test_mcp_contracts_scopes_and_no_broker_access(self):
  identity={'user_id':1,'scope':'reports:read reports:write'};args=observation(self.r)
  with patch('mcp_client.MCP',side_effect=AssertionError('Broker must not be accessed')):
   result=mcp_reports.rpc(app.connect,identity,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'record_hot_watch','arguments':args}})[1]['result'];self.assertFalse(result['isError']);self.assertTrue(result['structuredContent']['ok'])
  names={t['name'] for t in mcp_reports.tools('reports:read')};self.assertIn('get_hot_watch',names);self.assertNotIn('record_hot_watch',names)

class HotWatchHTTP(unittest.TestCase):
 def setUp(self):
  import test_mcp_reports
  self.http=test_mcp_reports.McpReports();self.http.setUp();self.r=merc_report();report_ingest.save(app.connect,1,self.r)
 def tearDown(self):self.http.tearDown()
 def test_http_auth_csrf_owner_and_category(self):
  d=observation(self.r);self.assertEqual(self.http.request('/api/reports/hot-watch',d)[0],401);auth=self.http.login();self.assertEqual(self.http.request('/api/reports/hot-watch',d,{'Cookie':auth['Cookie']})[0],403);status,receipt,_=self.http.request('/api/reports/hot-watch',d,auth);self.assertEqual(status,201);self.assertTrue(receipt['ok'])
  self.assertEqual(self.http.request('/api/reports/hot-watch',None)[0],401)
  status,result,_=self.http.request('/api/reports/hot-watch?is_test=false',None,auth);self.assertEqual(status,200);self.assertEqual(len(result['groups']),1)
  self.assertEqual(self.http.request('/api/reports/hot-watch?is_test=true',None,auth)[1]['groups'],[]);self.assertEqual(self.http.request('/api/reports/hot-watch?is_test=bad',None,auth)[0],400)
 def test_mcp_receive_readback_and_immutable_conflict(self):
  _,tokens,_=self.http.granted();d=observation(self.r);result=self.http.call(tokens['access_token'],'record_hot_watch',d)[1]['result'];self.assertFalse(result['isError']);self.assertEqual(self.http.call(tokens['access_token'],'get_hot_watch',{'is_test':False})[1]['result']['structuredContent']['groups'][0]['observations'][0]['data'],d)
  before=self.snapshot();d['note']='Changed';result=self.http.call(tokens['access_token'],'record_hot_watch',d)[1]['result'];self.assertTrue(result['isError']);self.assertIn('observation_id_conflict',{e['code'] for e in result['structuredContent']['errors']})
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hot_watch_observations').fetchone()[0],1)
 def snapshot(self):
  with app.connect() as c:return list(c.iterdump())
