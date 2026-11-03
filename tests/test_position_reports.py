"""Synthetic 12-position snapshots; no actual portfolios, quotes or trades."""
import copy,json,tempfile,unittest
from pathlib import Path
import app,report_ingest,report_validation,position_reports,market_data

ROOT=Path(__file__).resolve().parents[1]
def full_positions(rid='synthetic-positions',at='2026-11-02T15:00:00Z'):
 d=json.loads((ROOT/'examples/report-v2-test.json').read_text());d.update(report_id=rid,is_test=False,generated_at=at,source='SYNTHETISK POSITIONSINTEGRATION');d['sources'][0].update(verification='verified',verified_at=at);d['data_quality'].update(status='mixed',as_of=at,note='Kun syntetiske tests. Ingen reelle investeringsvurderinger.');d['portfolios'][0].update(name='Syntetisk hovedportefølje',as_of=at,reported_result={'amount':'25','currency':'DKK'});d['portfolios'][1].update(name='Syntetisk AI Trader',as_of=at,role='ai_trader',reported_result={'amount':'-10','currency':'DKK'})
 template=d['candidates'][0];d['candidates']=[]
 for t in ['PLTR','VRTX','AMD','PFE','FCX','MP','AAPL','BAVA','MRVL','LITE','GMAB','MDLZ']:
  c=copy.deepcopy(template);c.update(candidate_id='synthetic-candidate-'+t,ticker=t,company_name='Syntetisk '+t,signal='OVERVÅG');d['candidates'].append(c)
 template=d['positions'][0];d['positions']=[]
 for pid,tickers in [('test-main',['TSLA','BTC','AMGN','GMAB','MDLZ','PEPE','FCX']),('test-child',['MSFT','TSM','BTC','ASML','NOVOB'])]:
  for ticker in tickers:
   p=copy.deepcopy(template);p.update(position_id=pid+'.'+ticker,portfolio_id=pid,asset_id='synthetic-asset-'+ticker,asset_name='Syntetisk '+ticker,ticker=ticker,candidate_id='synthetic-candidate-'+ticker if ticker in ['GMAB','MDLZ','FCX'] else None,quantity='2',value={'amount':'100','currency':'DKK'},unrealized_pnl={'amount':'10','currency':'DKK'},as_of=at,position_status='open',assessment={'action':'BEHOLD','reason':'Syntetisk individuel analyse af '+pid+' '+ticker,'risk_level':'medium','next_action':'Kontrollér nye officielle oplysninger; ingen faktisk handel','assessed_at':at,'source_ids':['synthetic-source'],'data_quality':{'status':'mixed','as_of':at,'note':'Syntetisk analyse, ikke et reelt råd'}})
   d['positions'].append(p)
 d['orders']=[];d['journal']=[];return d

class Positions(unittest.TestCase):
 def setUp(self):
  self.prev=app.DB;self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/db';app.init();app.create_user('test-password-long-enough');self.d=full_positions()
 def tearDown(self):app.DB=self.prev;self.tmp.cleanup()
 def save(self,d=None):return report_ingest.save(app.connect,1,d or self.d)
 def view(self):return report_ingest.desk(app.connect,1)['positions']
 def flat(self):return [x for g in self.view()['groups'] for x in g['positions']]
 def test_all_12_and_btc_separate_independent_of_candidates(self):
  self.save();v=self.view();self.assertEqual(v['count'],12);self.assertEqual([len(g['positions']) for g in v['groups']],[7,5]);btc=[x for x in self.flat() if x['position']['ticker']=='BTC'];self.assertEqual(len(btc),2);self.assertNotEqual(position_reports.key(btc[0]['position']),position_reports.key(btc[1]['position']));self.assertEqual(btc[0]['position']['asset_id'],btc[1]['position']['asset_id']);self.assertTrue(all(x['assessment_status']=='BEHOLD' for x in self.flat()))
 def test_without_candidate_and_missing_assessment_never_copy_candidate_signal(self):
  p=self.d['positions'][0];self.assertIsNone(p['candidate_id']);self.d['positions'][3]['assessment']=None;self.d['candidates'][-2]['signal']='BEHOLD';self.save();v=self.flat();self.assertEqual(v[0]['assessment_status'],'BEHOLD');self.assertEqual(v[3]['assessment_status'],'DATA MANGLER');self.assertEqual(self.view()['count'],12);self.assertEqual(self.view()['missing'],1)
 def test_position_ids_can_repeat_across_portfolios_but_journal_must_disambiguate(self):
  self.d['positions'][1]['position_id']='btc';self.d['positions'][9]['position_id']='btc'
  entry={'entry_id':'btc-note','candidate_id':None,'position_id':'btc','order_id':None,'occurred_at':self.d['generated_at'],'kind':'analysis','text':'Syntetisk BTC-note','source_ids':['synthetic-source']};self.d['journal']=[entry]
  self.assertIn('ambiguous_reference',{e['code'] for e in report_ingest.validation(app.connect,1,self.d)['errors']})
  entry['portfolio_id']='test-main';self.save();self.assertEqual(self.view()['count'],12);self.assertEqual(len(position_reports.history(app.connect,1,'test-child','btc')['events']),1)
 def test_btc_assessments_can_differ_in_the_two_portfolios(self):
  self.d['positions'][9]['assessment']['action']='REDUCÉR';self.save();btc=[x for x in self.flat() if x['position']['ticker']=='BTC'];self.assertEqual([x['assessment_status'] for x in btc],['BEHOLD','REDUCÉR'])
 def test_new_fcx_in_both_sections_without_frontend_change(self):
  old=full_positions('before-fcx','2026-11-02T14:00:00Z');old['positions']=[p for p in old['positions'] if p['ticker']!='FCX'];self.save(old);self.save();desk=report_ingest.desk(app.connect,1);self.assertEqual(desk['positions']['count'],12);self.assertTrue(any(c['candidate']['ticker']=='FCX' for c in desk['candidates']));self.assertTrue(any(e['kind']=='new_position' and e['ticker']=='FCX' for e in desk['positions']['changes']))
 def test_closed_removed_but_payload_and_history_preserved(self):
  old=full_positions('old','2026-11-02T14:00:00Z');self.save(old)
  with app.connect() as c:before=tuple(c.execute('SELECT payload,digest FROM ingested_reports WHERE report_id=?',('old',)).fetchone())
  self.d['positions'][0].update(quantity='0',position_status='closed');self.save();self.assertEqual(self.view()['count'],11);self.assertEqual(self.view()['past'][0]['status'],'Lukket');history=position_reports.history(app.connect,1,'test-main','test-main.TSLA');self.assertEqual(len(history['events']),2)
  app.init()
  with app.connect() as c:self.assertEqual(before,tuple(c.execute('SELECT payload,digest FROM ingested_reports WHERE report_id=?',('old',)).fetchone()))
 def test_absence_is_not_a_sale_and_history_is_reachable(self):
  self.save(full_positions('old','2026-11-02T14:00:00Z'));self.d['positions']=self.d['positions'][1:];self.save();self.assertEqual(self.view()['count'],11);self.assertIn('not_reported',{e['kind'] for e in self.view()['changes']});self.assertEqual(self.view()['past'][0]['status'],'Ikke længere rapporteret')
 def test_closing_one_btc_preserves_the_other(self):
  self.save(full_positions('old','2026-11-02T14:00:00Z'));self.d['positions'][1].update(quantity='0',position_status='closed');self.save();btc=[x for x in self.flat() if x['position']['ticker']=='BTC'];self.assertEqual(len(btc),1);self.assertEqual(btc[0]['position']['portfolio_id'],'test-child');self.assertEqual(len(position_reports.history(app.connect,1,'test-main','test-main.BTC')['events']),2)
 def test_pending_and_partial_stop_never_reduce_holdings(self):
  def stop(lifecycle,filled):return {'order_id':'synthetic-stop','portfolio_id':'test-main','candidate_id':None,'asset_id':'synthetic-asset-TSLA','ticker':'TSLA','side':'SELL','order_type':'STOP','status':'ACTIVE_STOP','lifecycle':lifecycle,'requested_quantity':'2','filled_quantity':filled,'allocated':None,'as_of':self.d['generated_at'],'source_ids':['synthetic-source'],'note':'Syntetisk ordre, ikke sendt','stop_price':{'amount':'20','currency':'USD'}}
  old=full_positions('old','2026-11-02T14:00:00Z');old['orders']=[stop('pending','0')];self.save(old);self.d['orders']=[stop('pending','0')];self.save();self.assertEqual(self.view()['count'],12);self.assertFalse(any(e['kind']=='stop_fill_reported' for e in self.view()['changes']));self.assertEqual(self.flat()[0]['position']['quantity'],'2')
  next=copy.deepcopy(self.d);next.update(report_id='partial',generated_at='2026-11-02T16:00:00Z');next['orders']=[stop('partial','1')];self.save(next);self.assertEqual(self.view()['count'],12);self.assertIn('stop_fill_reported',{e['kind'] for e in self.view()['changes']})
  again=copy.deepcopy(next);again.update(report_id='unchanged-fill',generated_at='2026-11-02T17:00:00Z');self.save(again);self.assertFalse(any(e['kind']=='stop_fill_reported' for e in self.view()['changes']))
 def test_unchanged_actions_are_not_events_and_changed_actions_are(self):
  self.save(full_positions('old','2026-11-02T14:00:00Z'));self.save();self.assertEqual(self.view()['changes'],[])
  new=copy.deepcopy(self.d);new.update(report_id='changed',generated_at='2026-11-02T16:00:00Z');new['positions'][0]['assessment'].update(action='REDUCÉR',assessed_at=new['generated_at']);self.save(new);self.assertEqual(self.view()['changes'][0]['message'],'BEHOLD → REDUCÉR')
 def test_price_risk_and_candidate_changes_require_a_real_difference(self):
  old=full_positions('old','2026-11-02T14:00:00Z');market={'price':{'amount':'10','currency':'USD'},'daily_change':None,'daily_change_percent':None,'price_as_of':old['generated_at'],'change_as_of':None,'verification':'verified','source_ids':['synthetic-source']};old['positions'][0]['market']=copy.deepcopy(market);self.save(old)
  market['price']['amount']='12';market['price_as_of']=self.d['generated_at'];self.d['positions'][0]['market']=market;self.d['positions'][0]['assessment']['risk_level']='high';self.d['candidates'][0]['signal']='KØB';self.save();kinds={e['kind'] for e in self.view()['changes']};self.assertTrue({'price_changed','risk_changed','candidate_upgraded'}<=kinds)
  again=copy.deepcopy(self.d);again.update(report_id='no-change',generated_at='2026-11-02T16:00:00Z');self.save(again);self.assertEqual(self.view()['changes'],[])
 def test_deep_only_overlays_assessment_and_never_resurrects_sold(self):
  self.save();deep=copy.deepcopy(self.d);deep.update(report_id='deep',report_type='deep_analysis',generated_at='2026-11-02T16:00:00Z');deep['positions']=deep['positions'][:1];deep['positions'][0]['assessment'].update(action='REDUCÉR',assessed_at=deep['generated_at']);deep['positions'][0]['quantity']='99';self.save(deep);self.assertEqual(self.flat()[0]['assessment_status'],'REDUCÉR');self.assertEqual(self.flat()[0]['position']['quantity'],'2')
  closed=copy.deepcopy(self.d);closed.update(report_id='closed',generated_at='2026-11-02T17:00:00Z');closed['positions'][0].update(quantity='0',position_status='closed');self.save(closed);self.assertEqual(self.view()['count'],11)
 def test_archived_item_retains_its_own_assessment_while_desk_gets_deep(self):
  self.save();deep=copy.deepcopy(self.d);deep.update(report_id='later-deep-for-archive',report_type='deep_analysis',generated_at='2026-11-02T16:00:00Z');deep['positions'][0]['assessment'].update(action='REDUCÉR',assessed_at=deep['generated_at']);self.save(deep)
  archived=report_ingest.item(app.connect,1,self.d['report_id'])['report'];self.assertEqual(archived['positions_view']['groups'][0]['positions'][0]['assessment_status'],'BEHOLD');self.assertEqual(self.view()['groups'][0]['positions'][0]['assessment_status'],'REDUCÉR')
 def test_assessment_already_delivered_as_deep_is_not_a_new_main_event(self):
  self.save();deep=copy.deepcopy(self.d);deep.update(report_id='deep-assessment',report_type='deep_analysis',generated_at='2026-11-02T16:00:00Z');deep['positions'][0]['assessment'].update(action='REDUCÉR',assessed_at=deep['generated_at']);self.save(deep)
  new=copy.deepcopy(self.d);new.update(report_id='later-main',generated_at='2026-11-02T17:00:00Z');new['positions'][0]['assessment'].update(action='REDUCÉR',assessed_at=new['generated_at']);self.save(new);self.assertFalse(any(e['kind']=='assessment_changed' for e in self.view()['changes']))
 def test_old_v2_backfill_and_test_production_user_boundaries(self):
  old=json.loads((ROOT/'examples/report-v2-test.json').read_text());self.save(old);app.init();self.assertEqual(position_reports.history(app.connect,1,'test-child','test-position',True)['events'][0]['position'].get('assessment'),None);self.assertEqual(self.view()['count'],0);self.assertEqual(position_reports.history(app.connect,2,'test-child','test-position',True)['events'],[])
  self.save();self.assertEqual(self.view()['count'],12);self.assertEqual(position_reports.history(app.connect,1,'test-main','test-main.BTC',True)['events'],[])
 def test_structured_errors_atomicity_and_idempotency(self):
  self.d['positions'][0]['assessment'].update(action='KØB',source_ids=['missing']);del self.d['positions'][1]['assessment']['reason'];self.d['positions'][2]['assessment']['assessed_at']='2026-11-02T15:00:00'
  checked=report_ingest.validation(app.connect,1,self.d);paths={e['path'] for e in checked['errors']};self.assertTrue({'positions[0].assessment.action','positions[0].assessment.source_ids[0]','positions[1].assessment.reason','positions[2].assessment.assessed_at'}<=paths)
  with self.assertRaises(ValueError):self.save()
  with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM ingested_reports').fetchone()[0],0);self.assertEqual(c.execute('SELECT COUNT(*) FROM report_position_links').fetchone()[0],0)
  d=full_positions();self.save(d);self.assertTrue(self.save(d)[1]['duplicate']);d['positions'][0]['assessment']['reason']='Changed';self.assertEqual(self.save(d)[0],409)
 def test_position_quote_uses_owned_position_and_existing_read_contract(self):
  self.save();data={'report_id':self.d['report_id'],'position_id':'test-main.BTC','portfolio_id':'test-main','is_test':False};calls=[]
  raw=json.loads((ROOT/'tests/fixtures/pluto-series-synthetic.json').read_text());raw['asset']['id']='synthetic-asset-BTC';raw['price']['assetId']='synthetic-asset-BTC'
  import trade_service
  class Client:
   def __init__(self,token):pass
   def tools(self):return [{'name':'get_asset','inputSchema':trade_service.CONTRACT['get_asset']['inputSchema'],'annotations':{'readOnlyHint':True}}]
   def request(self,method,args):calls.append(args);return {'structuredContent':raw}
  from unittest.mock import patch
  with patch('trade_service.client',return_value=(Client(None),{'get_asset':Client(None).tools()[0]})):
   q=market_data.quote(app.connect,1,data);self.assertEqual(q['asset_id'],'synthetic-asset-BTC');self.assertEqual(calls[0]['name'],'get_asset')
   for bad in [dict(data,portfolio_id='test-child',position_id='test-main.BTC'),dict(data,is_test=True)]:
    with self.assertRaises(market_data.MarketError):market_data.quote(app.connect,1,bad)
   with self.assertRaises(market_data.MarketError):market_data.quote(app.connect,2,data)
  self.assertEqual(len(calls),1)
 def test_shared_asset_inflight_cache_is_pending_not_a_second_provider_read(self):
  import time
  self.save();data={'report_id':self.d['report_id'],'position_id':'test-main.BTC','portfolio_id':'test-main','is_test':False}
  with app.connect() as c:c.execute('INSERT INTO market_asset_cache(user_id,asset_id,attempted) VALUES(?,?,?)',(1,'synthetic-asset-BTC',time.time()))
  from unittest.mock import patch
  with patch('trade_service.client',side_effect=AssertionError('No duplicate broker read')):self.assertTrue(market_data.quote(app.connect,1,data)['pending'])
 def test_unverified_analysis_and_market_data_are_not_promoted(self):
  self.d['positions'][0]['assessment']['data_quality']['status']='unverified';self.save();self.assertEqual(self.flat()[0]['assessment_status'],'IKKE VURDERET')
  bad=full_positions('bad');bad['positions'][0]['market']={'price':{'amount':'10','currency':'USD'},'daily_change':None,'daily_change_percent':None,'price_as_of':None,'change_as_of':None,'verification':'unknown','source_ids':[]};self.assertFalse(report_ingest.validation(app.connect,1,bad)['valid'])
