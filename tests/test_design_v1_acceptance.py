"""Synthetic T01–T28 component/integration acceptance. Browser checks are separately required."""
import copy,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import app,portfolios,portfolio_data,report_ingest,dashboard_projection as dashboard,display_policy as policy,candidate_lifecycle
from test_position_reports import full_positions

NOW=datetime(2026,11,3,15,tzinfo=timezone.utc)
def observation(price='104',at=None):
 return {'asset_id':'synthetic-asset','source':'pluto','feed_type':'synthetic-verified','venue':'SYNTHETIC','currency':'USD','market_phase':'REGULAR','session_key':'synthetic-day','price_type':'last','adjustment_basis':'unadjusted','price':price,'event_time':(at or NOW).isoformat()}
def reference():
 r=observation('100',NOW-timedelta(days=1));r.update(kind='official_close',verification='verified',source_id='SYNTHETIC-CLOSE',reference_session='synthetic-prior-day',applies_to_session='synthetic-day');return r

class DesignAcceptance(unittest.TestCase):
 def setUp(self):
  self.old=app.DB;self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/db';app.init();app.create_user('test-password-long-enough')
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:synthetic-root','name':'Synthetic root','kind':'portfolio','can_trade':False},{'id':'collections:synthetic-ai','name':'Synthetic AI','kind':'collection','parent_external_id':'portfolios:synthetic-root'}]);self.ports=portfolios.list_owned(c,1)
  self.ports=[p for p in self.ports if p['source']=='pluto'];self.root=next(p for p in self.ports if p['kind']=='portfolio');self.child=next(p for p in self.ports if p['kind']=='collection')
  self.report=full_positions('design-acceptance-report',NOW.isoformat())
  for p in self.report['portfolios']:p['broker_reference']={'provider':'pluto','external_id':self.root['external_id'] if p['kind']=='portfolio' else self.child['external_id']}
  report_ingest.save(app.connect,1,self.report)
  for port,rpid,value in [(self.root,'test-main','1000'),(self.child,'test-child','300')]:
   ps=[p for p in self.report['positions'] if p['portfolio_id']==rpid]
   rows=portfolio_data.normalize_positions([{'assetId':p['asset_id'],'ticker':p['ticker'],'name':'SYNTHETIC '+p['ticker'],'quantity':'2','currency':'DKK','latestPrice':'50','value':'100','costBasis':'90','unrealisedPnL':'10','priceAsOf':NOW.isoformat()} for p in ps])
   for r in rows:
    meta=observation();r['market_context']={k:meta[k] for k in ['feed_type','venue','market_phase','session_key','price_type','adjustment_basis']}
    ref=reference();ref.update(asset_id=r['asset_id'],currency='DKK',price='49');r['official_close_reference']=ref
   payload={'source':'SYNTHETIC BROKER','observed':NOW.isoformat(),'kind':port['kind'],'value':{'value':{'amount':value,'currency':'DKK'},'source_time':NOW.isoformat(),'reported_result':{'amount':'55','currency':'DKK'}},'positions':rows,'positions_complete':True,'accounts':[],'pending_orders':[],'orders_complete':True,'complete':True,'errors':[]}
   with app.connect() as c:portfolio_data.save(c,1,port['id'],payload)
 def tearDown(self):app.DB=self.old;self.tmp.cleanup()
 def model(self,now=NOW):
  with app.connect() as c:snap=portfolio_data.snapshots(c,1)
  return dashboard.build(app.connect,1,self.ports,snap,now)
 def test_T01_positive_official_day(self):
  self.assertEqual(Decimal(policy.daily_change(observation(),reference())['percent']),Decimal(4));self.assertIsNone(policy.daily_change(observation(),None))
 def test_T02_negative_official_day(self):self.assertEqual(Decimal(policy.daily_change(observation('96'),reference())['percent']),Decimal(-4))
 def test_T03_positive_day_negative_unrealized(self):
  self.assertGreater(Decimal(policy.daily_change(observation(),reference())['percent']),0);p=policy.unrealized({'amount':'208','currency':'USD'},{'amount':'240','currency':'USD'},{'amount':'0','currency':'USD'});self.assertEqual(Decimal(p['amount']),-32)
 def test_T04_profit_independent_of_sell_assessment(self):
  d=copy.deepcopy(self.report);d.update(report_id='sell-assessment',generated_at=(NOW+timedelta(seconds=1)).isoformat());d['positions'][0]['assessment'].update(action='SÆLG',assessed_at=d['generated_at']);report_ingest.save(app.connect,1,d)
  r=next(r for r in self.model(NOW+timedelta(seconds=2))['positions'] if r['ticker']=='TSLA');self.assertEqual(r['action'],'SÆLG');self.assertTrue(r['critical']);self.assertGreater(Decimal(r['unrealized']['amount']),0)
 def test_T05_unknown_price_has_no_comparison(self):
  o=observation();o['price']=None;self.assertIsNone(policy.daily_change(o,reference()));self.assertIsNone(policy.comparison(o,observation('100',NOW-timedelta(seconds=60))))
 def test_T06_old_analysis_preserves_real_holdings(self):
  d=self.model(NOW+timedelta(hours=25));self.assertEqual(d['count'],12);self.assertTrue(all(r['analysis_freshness']['state']=='stale' for r in d['positions']))
 def test_T07_reject_does_not_hide_ownership(self):
  r={'lifecycle':{'status':'POSITION_OPEN'},'normalized_decision':'REJECT','has_confirmed_position':True};self.assertEqual(policy.candidate_group(r),'positions');self.assertEqual(self.model()['count'],12)
 def test_T08_partial_then_cancelled_preserves_actual_fill(self):
  from test_hotwatch_engine import tick
  cid=self.report['candidates'][0]['candidate_id'];ctx=tick(NOW,held=True)['context'];ctx['orders']=[{'order_id':'synthetic-cancelled','status':'CANCELLED','requested_quantity':'10','filled_quantity':'4','side':'BUY'}]
  with app.connect() as c:candidate_lifecycle.observe_pluto(c,1,False,cid,ctx,NOW.isoformat(),'SYNTHETIC PROVIDER','synthetic-cycle',synthetic=False)
  with app.connect() as c:r=c.execute("SELECT status,payload FROM candidate_execution_events WHERE order_id='synthetic-cancelled'").fetchone()
  self.assertEqual(r['status'],'CANCELLED');self.assertEqual(json.loads(r['payload'])['filled_quantity'],'4');self.assertEqual(policy.order_group('CANCELLED',NOW.isoformat(),NOW),'recent')
 def test_T09_terminal_candidates_are_history(self):
  for status in ['CLOSED','ARCHIVED']:self.assertEqual(policy.candidate_group({'lifecycle':{'status':status}}),'history')
 def test_T10_error_and_degraded_separate_from_lifecycle(self):
  self.assertEqual(policy.SESSION_GROUPS['ERROR'],'critical');self.assertEqual(policy.SESSION_GROUPS['DEGRADED'],'warning');self.assertEqual(policy.SESSION_GROUPS['PAUSED'],'paused')
 def test_T11_same_ticker_two_owned_depots(self):
  rows=[r for r in self.model()['positions'] if r['ticker']=='BTC'];self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['key'],rows[1]['key'])
 def test_T12_root_includes_ai_no_double_count(self):self.assertEqual(self.model()['totals'],[{'currency':'DKK','amount':'1000'}])
 def test_T13_missing_fx_keeps_original_currency(self):
  with app.connect() as c:
   snap=portfolio_data.snapshots(c,1)[str(self.root['id'])]['data'];snap['positions'][0]['value']={'amount':'100','currency':'USD'};portfolio_data.save(c,1,self.root['id'],snap)
  r=next(r for r in self.model()['positions'] if r['ticker']=='TSLA');self.assertEqual(r['value']['currency'],'USD');self.assertEqual(r['missing']['fx'],'DKK_CONVERSION_NOT_PROVIDED')
 def test_T14_waiting_is_separate_without_implicit_expiry(self):self.assertEqual(policy.candidate_group({'lifecycle':{'status':'WAITING_TRIGGER'},'normalized_decision':'WAIT'}),'waiting')
 def test_T15_omitted_candidate_remains_searchable(self):
  cid=self.report['candidates'][0]['candidate_id'];new=copy.deepcopy(self.report);new.update(report_id='omission',generated_at=(NOW+timedelta(minutes=1)).isoformat());new['candidates']=[];report_ingest.save(app.connect,1,new);self.assertTrue(report_ingest.candidate_history(app.connect,1,cid)['events'])
 def test_T16_status_append_only_and_readback(self):
  cid=self.report['candidates'][0]['candidate_id'];at=(NOW+timedelta(minutes=1)).isoformat()
  with app.connect() as c:candidate_lifecycle.record(c,1,False,cid,'HOT_WATCH',at,'SYNTHETIC','synthetic-origin','synthetic-cycle')
  at2=(NOW+timedelta(minutes=2)).isoformat()
  with app.connect() as c:candidate_lifecycle.record(c,1,False,cid,'WAITING_TRIGGER',at2,'SYNTHETIC trigger','synthetic-origin-2','synthetic-cycle')
  events=candidate_lifecycle.history(app.connect,1,cid)['events'];self.assertTrue({'HOT_WATCH','WAITING_TRIGGER'}<={e['status'] for e in events});self.assertEqual(report_ingest.item(app.connect,1,self.report['report_id'])['report']['data'],self.report)
 def test_T17_financial_signs_provided_without_changing_absolute_values(self):
  r=self.model()['positions'][0];self.assertEqual(r['value']['amount'],'100');self.assertGreater(Decimal(r['daily']['percent']),0);self.assertEqual(r['price']['amount'],'50')
 def test_collection_quote_history_reported_day_and_estimated_result(self):
  import asset_quotes
  with app.connect() as c:
   payload=portfolio_data.snapshots(c,1)[str(self.child['id'])]['data']
   row=portfolio_data.normalize_positions([{'assetId':'collection-test','ticker':'TEST','name':'Synthetic','quantity':'2','currency':'USD','costBasis':'90'}])[0]
   row['price']={'amount':'50','currency':'USD'};row['price_source']='Pluto get_asset · senest kendte pris';asset_quotes.calculate(row)
   payload['positions']=[row];payload['observed']=(NOW+timedelta(minutes=1)).isoformat();portfolio_data.save(c,1,self.child['id'],payload)
   row=copy.deepcopy(row);row['price']['amount']='55';row['value']['amount']='110';row['unrealized']['amount']='20';row['reported_daily']={'percent':'-2','amount':'-1','currency':'USD','from':None,'to':(NOW+timedelta(minutes=2)).isoformat(),'basis':'pluto_reported_daily_change','source_id':'Pluto get_asset'}
   payload['positions']=[row];payload['observed']=(NOW+timedelta(minutes=2)).isoformat();portfolio_data.save(c,1,self.child['id'],payload)
  item=next(r for r in self.model(NOW+timedelta(minutes=2))['positions'] if r['asset_id']=='collection-test')
  self.assertEqual(Decimal(item['since_last']['percent']),Decimal('10'));self.assertEqual(item['daily']['percent'],'-2');self.assertEqual(item['unrealized']['amount'],'20');self.assertTrue(item['unrealized_estimated']);self.assertEqual(item['unrealized']['currency'],'USD')
 def test_T18_incompatible_observations_rejected_per_dimension(self):
  a=observation();b=observation('100',NOW-timedelta(minutes=1));self.assertIsNotNone(policy.comparison(a,b))
  for key in ['asset_id','source','feed_type','venue','currency','market_phase','session_key','price_type','adjustment_basis']:
   with self.subTest(key=key):
    c=copy.deepcopy(a);c[key]='OTHER';self.assertIsNone(policy.comparison(c,b));c[key]=None;self.assertIsNone(policy.comparison(c,b))
 def test_T19_live_quote_threshold(self):
  for seconds in [59,60,61]:self.assertEqual(policy.freshness('live_quote',(NOW-timedelta(seconds=seconds)).isoformat(),NOW,{'status':'OPEN','verified':True})['state'],'stale' if seconds>60 else 'fresh')
 def test_T20_snapshot_threshold(self):
  for seconds in [299,300,301]:self.assertEqual(policy.freshness('snapshot',(NOW-timedelta(seconds=seconds)).isoformat(),NOW,{'status':'OPEN','verified':True})['state'],'stale' if seconds>300 else 'fresh')
 def test_T21_assessment_threshold_does_not_remove_positions(self):
  self.assertEqual(self.model(NOW+timedelta(seconds=86401))['count'],12);self.assertEqual(policy.freshness('analysis',NOW.isoformat(),NOW+timedelta(seconds=86401))['state'],'stale')
 def test_T22_calendar_coverage_weekend_holiday_and_unknown(self):
  calendar={'venue':'SYNTHETIC','verified':True,'coverage_from':'2026-11-01T00:00:00Z','coverage_to':'2026-11-30T23:59:59Z','sessions':[{'id':'regular','open':'2026-11-03T14:30:00Z','close':'2026-11-03T21:00:00Z'},{'id':'half','open':'2026-11-27T14:30:00Z','close':'2026-11-27T18:00:00Z'}]}
  self.assertEqual(policy.market_session(NOW,'SYNTHETIC',calendar)['status'],'OPEN')
  for at in ['2026-11-07T15:00:00Z','2026-11-26T15:00:00Z','2026-11-27T19:00:00Z']:self.assertEqual(policy.market_session(policy.stamp(at),'SYNTHETIC',calendar)['status'],'CLOSED')
  self.assertEqual(policy.market_session(NOW,'UNKNOWN',calendar)['status'],'UNKNOWN');self.assertEqual(policy.market_session(NOW,asset_class='verified_crypto_24x7')['status'],'OPEN')
  f=policy.freshness('snapshot','2026-11-03T21:00:00Z',policy.stamp('2026-11-07T15:00:00Z'),policy.market_session(policy.stamp('2026-11-07T15:00:00Z'),'SYNTHETIC',calendar),session_key='regular');self.assertEqual(f['state'],'session_close')
 def test_T23_twelve_owned_rows_not_twelve_report_cards(self):self.assertEqual(self.model()['count'],12);self.assertEqual(len({r['key'] for r in self.model()['positions']}),12)
 def test_T24_dashboard_read_model_is_serializable_for_all_viewports(self):
  d=self.model();self.assertEqual(json.loads(json.dumps(d))['count'],12) # actual width/layout assertions are in browser_design_v1.py
 def test_T25_archived_report_not_rewritten_by_projection(self):
  before=report_ingest.item(app.connect,1,self.report['report_id']);self.model();after=report_ingest.item(app.connect,1,self.report['report_id']);self.assertEqual(before,after)
 def test_T26_broker_quantity_wins_but_report_is_preserved(self):
  with app.connect() as c:
   snap=portfolio_data.snapshots(c,1)[str(self.root['id'])]['data'];snap['positions'][0]['quantity']='4';portfolio_data.save(c,1,self.root['id'],snap)
  r=next(r for r in self.model()['positions'] if r['ticker']=='TSLA');self.assertEqual(r['quantity'],'4');self.assertEqual(r['reported_position']['quantity'],'2');self.assertTrue(r['conflicts'])
 def test_T27_source_failure_keeps_last_known_positions_and_critical(self):
  with app.connect() as c:
   c.execute("UPDATE portfolio_snapshots SET last_error='SYNTHETIC ERROR' WHERE portfolio_id=?",(self.root['id'],))
  d=self.model();self.assertEqual(d['count'],12);self.assertTrue(d['warnings']);self.assertTrue(any(r['verification']=='last_known' for r in d['positions']));self.assertTrue(policy.journal_visible({'severity':'critical','resolved':False,'timestamp':'2000-01-01T00:00:00Z'},NOW))
 def test_T28_read_projection_never_changes_business_or_history_tables(self):
  def dump():
   with app.connect() as c:return list(c.iterdump())
  before=dump();self.model();self.assertEqual(before,dump())
 def test_percentage_uses_original_currency_broker_profit_when_display_is_dkk(self):
  with app.connect() as c:
   payload=portfolio_data.snapshots(c,1)[str(self.root['id'])]['data'];row=payload['positions'][0]
   row['unrealized']={'amount':'10','currency':'USD'};row['cost_basis']={'amount':'100','currency':'USD'};row['unrealized_in_portfolio_currency']={'amount':'70','currency':'DKK'}
   portfolio_data.save(c,1,self.root['id'],payload)
  result=next(r for r in self.model()['positions'] if r['portfolio_id']==self.root['id'] and r['asset_id']==row['asset_id'])
  self.assertEqual(Decimal(result['unrealized_percent']),10);self.assertEqual(result['unrealized']['currency'],'DKK')
 def test_snapshot_history_records_unknown_market_time_without_guessing(self):
  with app.connect() as c:rows=portfolio_data.snapshots(c,1)
  for port in [self.root,self.child]:
   payload=rows[str(port['id'])]['data'];payload['observed']=(NOW+timedelta(minutes=1)).isoformat()
   for row in payload['positions']:row['price_time']=None
   with app.connect() as c:portfolio_data.save(c,1,port['id'],payload)
  result=self.model(NOW+timedelta(minutes=2))
  self.assertTrue(all(r['since_last'] and r['since_last']['basis']=='pluto_snapshot_received_at' for r in result['positions']))
  self.assertTrue(all(r['price_time'] is None for r in result['positions']))
 def test_position_hotwatch_requires_verified_asset_portfolio_and_cycle(self):
  import hotwatch_engine
  port=self.root['id'];candidate='candidate-bayn-a';cycle='cycle-bayn-a';other='candidate-bayn-b'
  with app.connect() as c:
   for cid,aid,cyc in [(candidate,'pluto-asset-a',cycle),(other,'pluto-asset-b','cycle-bayn-b')]:
    req={'asset_id':aid,'candidate_id':cid,'trade_cycle_id':cyc,'portfolio_ids':[port]}
    c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,?,0,?,'exit','ACTIVE',?,'d','{}','{}',?,?,0)",(cid,cid,json.dumps(req),NOW.isoformat(),NOW.isoformat()))
   candidate_lifecycle.record(c,1,False,candidate,'POSITION_OPEN',NOW.isoformat(),'SYNTHETIC position link','synthetic-report',cycle)
   linked=dashboard.position_hotwatch(c,1,port,'pluto-asset-a',{'candidate_id':candidate,'trade_cycle_id':cycle})
   wrong_asset=dashboard.position_hotwatch(c,1,port,'pluto-asset-other',{'candidate_id':candidate,'trade_cycle_id':cycle})
   wrong_cycle=dashboard.position_hotwatch(c,1,port,'pluto-asset-a',{'candidate_id':candidate,'trade_cycle_id':'other-cycle'})
  self.assertEqual(linked['session']['watch_id'],candidate);self.assertEqual(linked['lifecycle']['status'],'POSITION_OPEN');self.assertIsNone(wrong_asset['session']);self.assertIsNone(wrong_cycle['session'])

if __name__=='__main__':unittest.main()
