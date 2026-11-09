"""Pilot identity and source provenance; all reports and quotes are synthetic."""
import copy,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import app,hotwatch_engine as engine,hotwatch_strategy,strategy_center,report_ingest,report_validation
from hotwatch_adapters import PlutoAdapter
from test_intel_workflows import merc_report
from test_hotwatch_engine import tick,request

class Pilot(unittest.TestCase):
 def setUp(self):
  self.old=app.DB;self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/db';app.init();app.create_user('test-password-long-enough')
  self.now=datetime.now(timezone.utc).replace(microsecond=0)+timedelta(seconds=2);self.report=merc_report(True);self.report['report_id']='pilot-report';self.report['generated_at']=self.now.isoformat();self.candidate=self.report['candidates'][0];self.candidate['decision'].update(decided_at=self.now.isoformat(),data_as_of=self.now.isoformat(),deadline=(self.now+timedelta(hours=2)).isoformat())
  self.candidate['strategy_proposal']={'strategy_id':'escape_early_catalyst','version':'1.0.0','reason':'Synthetic pilot','proposed_at':self.now.isoformat(),'source_ids':['synthetic-source'],'catalyst':{'kind':'earnings','published_at':self.now.isoformat(),'available_at':self.now.isoformat(),'source_ids':['synthetic-source']},'news_check':{'status':'verified_news','checked_at':self.now.isoformat(),'source_ids':['synthetic-source']}}
  self.report['sources'][0].update(verification='verified',published_at=self.now.isoformat(),verified_at=self.now.isoformat())
  report_ingest.save(app.connect,1,self.report);self.req=request();self.req.update(report_id='pilot-report',strategy_id='escape_early_catalyst',strategy_version='1.0.0');engine.create(app.connect,1,self.req,self.now)
 def test_automatic_reported_catalyst_priority_is_scheduling_only(self):
  req=copy.deepcopy(self.req);req.update(watch_id='pilot-priority',purpose='automatic discovery',watch_mode='entry')
  engine.create(app.connect,1,req,self.now)
  with app.connect() as c:
   state=json.loads(c.execute('SELECT state FROM hw_sessions WHERE watch_id=?',(req['watch_id'],)).fetchone()['state'])
  self.assertEqual(state['catalyst_priority_basis'],'sender_reported_news')
  self.assertEqual(state['catalyst_priority_until'],(self.now+timedelta(minutes=120)).timestamp())
  self.assertEqual(state['signal'],'NO_DATA')
 def tearDown(self):app.DB=self.old;self.tmp.cleanup()
 def test_pilot_observation_shows_claim_and_blocks_missing_evidence(self):
  sample=tick(self.now);sample['context'].update(instrument_type='CS',instrument_type_at=self.now.isoformat())
  result=engine.ingest(app.connect,1,self.req['watch_id'],True,sample,self.now)
  pilot=result['calculation']['early_catalyst'];m=result['calculation']['supporting_metrics']
  self.assertEqual(pilot['mode'],'live_pilot');self.assertEqual(pilot['watch_state'],'WAITING_FOR_EVIDENCE');self.assertEqual(pilot['reported_evidence']['verification'],'sender_reported')
  self.assertTrue(m['ordinary_share']);self.assertTrue(m['pluto_tradable']);self.assertTrue(m['catalyst_verified']);self.assertIsNone(m['reference_gain_pct']);self.assertIn('ikke uafhængigt',pilot['note']);self.assertNotEqual(result['calculation']['signal'],'BUY')
  self.assertEqual(result['session']['display_status'],'AFVENTER EARLY WATCH')
 def test_no_confirmation_from_unchecked_or_future_claim(self):
  p=self.candidate['strategy_proposal'];self.assertEqual(strategy_center._news_attestation(self.report,p,self.now),'verified_news')
  bad=copy.deepcopy(self.report);bad['sources'][0]['verification']='unverified';self.assertIsNone(strategy_center._news_attestation(bad,p,self.now))
  later=copy.deepcopy(p);later['news_check']['checked_at']=(self.now+timedelta(seconds=1)).isoformat();self.assertIsNone(strategy_center._news_attestation(self.report,later,self.now))
  news=copy.deepcopy(p);news['catalyst']['published_at']=(self.now-timedelta(minutes=1)).isoformat();self.assertIsNone(strategy_center._news_attestation(self.report,news,self.now))
 def test_reference_requires_same_prior_close_and_fresh_calendar(self):
  from datetime import datetime,timezone
  at=datetime(2026,11,9,10,0,tzinfo=timezone.utc);sample=tick(at);sample.update(source='eodhd',previous_close='100',price='102',close='102');req={**self.req,'provider_symbol':'MERC.US'}
  quote={'reference_close':{'price':{'amount':'100','currency':'USD'},'observed_at':'2026-11-06T16:00:00+00:00','available_at':'2026-11-06T16:00:01+00:00'},'news_session':'during_regular','catalyst':{}}
  schedule={'open':'09:00:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',at.isoformat(),'UTC',json.dumps(schedule)));row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone()
   self.assertEqual(strategy_center._reference(c,row,req,sample,quote,at),'2.00')
   self.assertIsNone(strategy_center._reference(c,row,req,{**sample,'previous_close':'99'},quote,at))
   self.assertIsNone(strategy_center._reference(c,row,req,sample,quote,at+timedelta(minutes=6)))
   early=copy.deepcopy(quote);early['reference_close']['observed_at']='2026-11-05T16:00:00+00:00';self.assertIsNone(strategy_center._reference(c,row,req,sample,early,at))
   after=copy.deepcopy(quote);after['news_session']='after_close';after['catalyst']={'published_at':'2026-11-06T15:30:00+00:00'};self.assertIsNone(strategy_center._reference(c,row,req,sample,after,at))
 def test_pre_news_price_requires_matching_local_observation(self):
  from hotwatch_contract import checksum
  news=self.now-timedelta(minutes=1);observed=news-timedelta(seconds=10);old=tick(observed,7,price='100');old['source']='eodhd';current=tick(self.now,8,price='102');req=self.req
  reported={'published_at':news.isoformat(),'pre_news_price':{'price':{'amount':'100','currency':'USD'},'observed_at':observed.isoformat(),'available_at':observed.isoformat(),'source_ids':['synthetic-source']}}
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(req['watch_id'],)).fetchone();c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],'eodhd',old['sample_id'],observed.timestamp(),observed.isoformat(),json.dumps(old),checksum(old)))
   self.assertEqual(strategy_center._pre_news(c,row,req,current,reported,self.now),'2.00')
   bad=copy.deepcopy(reported);bad['pre_news_price']['price']['amount']='90';self.assertIsNone(strategy_center._pre_news(c,row,req,current,bad,self.now))
   bad=copy.deepcopy(reported);bad['pre_news_price']['observed_at']=(news+timedelta(seconds=1)).isoformat();self.assertIsNone(strategy_center._pre_news(c,row,req,current,bad,self.now))
 def test_news_session_is_derived_from_fresh_exchange_calendar(self):
  at=datetime(2026,11,9,18,0,tzinfo=timezone.utc);req={**self.req,'provider_symbol':'MERC.US'};schedule={'open':'09:00:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',at.isoformat(),'UTC',json.dumps(schedule)))
   self.assertEqual(strategy_center._news_session(c,req,{'published_at':'2026-11-09T15:00:00+00:00'},at),'during_regular')
   self.assertEqual(strategy_center._news_session(c,req,{'published_at':'2026-11-09T16:30:00+00:00'},at),'after_close')
   self.assertIsNone(strategy_center._news_session(c,req,{'published_at':'2026-11-09T16:30:00+00:00'},at+timedelta(minutes=6)))
 def test_news_cannot_be_verified_just_by_text(self):
  proposal=copy.deepcopy(self.candidate['strategy_proposal']);proposal.pop('news_check');self.assertIsNone(strategy_center._news_attestation(self.report,proposal,self.now))
  proposal['news_check']={'status':'no_verified_news','checked_at':self.now.isoformat(),'source_ids':['synthetic-source']};self.assertEqual(strategy_center._news_attestation(self.report,proposal,self.now),'no_verified_news')
 def test_buy_is_withdrawn_from_current_view_when_evidence_changes(self):
  from test_hotwatch_engine import good_metrics
  valid={'value':True}
  def input_metrics(c,row,req,sample,metrics,now):
   metrics.update(ordinary_share=True,pluto_tradable=True,catalyst_verified=valid['value'],catalyst_age_minutes='1',earnings_previous_session=False,no_verified_news=False,reference_gain_pct='2',news_reaction_pct='1',consolidating=False,new_breakout=False,new_setup=False)
   return {'mode':'live_pilot','watch_state':'WAITING_FOR_EVIDENCE','missing':[],'reported_evidence':None,'note':'Synthetic'}
  metrics={**good_metrics(),'sample_count':20,'return_window_pct':'0.6','relative_volume':'2','acceleration_pct_s2':'0.1','spread_pct':'0.5','macd_histogram':None}
  start=self.now;later=start+timedelta(seconds=16)
  with patch('hotwatch_engine.features',return_value=metrics.copy()),patch('strategy_center.early_inputs',side_effect=input_metrics):
   engine.ingest(app.connect,1,self.req['watch_id'],True,tick(start,1),start)
   final=engine.ingest(app.connect,1,self.req['watch_id'],True,tick(later,2),later);self.assertEqual(final['calculation']['signal'],'BUY')
   with app.connect() as c:
    row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone();self.assertEqual(engine.view(c,row,later)['signal'],'BUY')
    valid['value']=False;current=engine.view(c,row,later+timedelta(seconds=1));self.assertNotEqual(current['signal'],'BUY');self.assertIn('EARLY_EVIDENCE_STALE',current['display_reason_codes'])
 def test_source_attributed_watch_and_buy_still_obey_risk_and_confirmation(self):
  from datetime import datetime,timezone
  from test_hotwatch_engine import good_metrics
  from hotwatch_strategy import calculate
  at=max(datetime(2026,11,9,10,0,tzinfo=timezone.utc),self.now+timedelta(minutes=20));news=at-timedelta(minutes=10);checked=at-timedelta(minutes=8);proposed=at-timedelta(minutes=7)
  doc=copy.deepcopy(self.report);doc['report_id']='synthetic-live-conditions';doc['generated_at']=(at-timedelta(minutes=6)).isoformat();candidate=doc['candidates'][0];candidate['decision'].update(decided_at=doc['generated_at'],data_as_of=doc['generated_at'],deadline=(at+timedelta(hours=2)).isoformat());p=candidate['strategy_proposal'];p.update(proposed_at=proposed.isoformat(),news_session='during_regular',catalyst={'kind':'news','published_at':news.isoformat(),'available_at':news.isoformat(),'source_ids':['synthetic-source']},news_check={'status':'verified_news','checked_at':checked.isoformat(),'source_ids':['synthetic-source']},reference_close={'price':{'amount':'100','currency':'USD'},'observed_at':'2026-11-06T16:00:00+00:00','available_at':'2026-11-06T16:00:01+00:00','source_ids':['synthetic-source']})
  doc['sources'][0].update(published_at=news.isoformat(),verified_at=(at-timedelta(minutes=9)).isoformat());report_ingest.save(app.connect,1,doc)
  schedule={'open':'09:00:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]};sample=tick(at,price='102');sample.update(source='eodhd',previous_close='100');sample['context'].update(instrument_type='CS',instrument_type_at=at.isoformat())
  req={**self.req,'provider_symbol':'MERC.US'};metrics={**good_metrics(),'sample_count':20,'return_window_pct':'0.6','relative_volume':'2','acceleration_pct_s2':'0.1','spread_pct':'0.5','macd_histogram':None}
  with app.connect() as c:
   c.execute('INSERT INTO hw_exchange_calendar VALUES(?,?,?,?)',('US',at.isoformat(),'UTC',json.dumps(schedule)));row=c.execute('SELECT * FROM hw_sessions WHERE watch_id=?',(self.req['watch_id'],)).fetchone();pilot=strategy_center.early_inputs(c,row,req,sample,metrics,at)
  self.assertTrue(metrics['ordinary_share']);self.assertTrue(metrics['catalyst_verified']);self.assertEqual(metrics['reference_gain_pct'],'2.00');self.assertIn('ikke uafhængigt',pilot['note'])
  risk={**req['risk'],'entry_allowed':True,'exit_allowed':False};first,state=calculate(sample,metrics,hotwatch_strategy.EARLY_CATALYST_V1,risk,{},at);self.assertEqual(first['signal'],'WAIT')
  later=at+timedelta(seconds=16);sample['event_time']=later.isoformat();sample['context']['as_of']=later.isoformat();second,_=calculate(sample,metrics,hotwatch_strategy.EARLY_CATALYST_V1,risk,state,later);self.assertEqual(second['signal'],'BUY')
  blocked,_=calculate(sample,{**metrics,'spread_pct':'1.01'},hotwatch_strategy.EARLY_CATALYST_V1,risk,state,later);self.assertNotEqual(blocked['signal'],'BUY')
 def test_structured_mcp_evidence_round_trip(self):
  import mcp_reports
  doc=copy.deepcopy(self.report);doc['report_id']='pilot-mcp-structured';p=doc['candidates'][0]['strategy_proposal'];p.update(news_session='during_regular',reference_close={'price':{'amount':'100','currency':'USD'},'observed_at':(self.now-timedelta(days=1)).isoformat(),'available_at':(self.now-timedelta(days=1)).isoformat(),'source_ids':['synthetic-source']},pre_news_price={'price':{'amount':'101','currency':'USD'},'observed_at':(self.now-timedelta(seconds=10)).isoformat(),'available_at':(self.now-timedelta(seconds=10)).isoformat(),'source_ids':['synthetic-source']})
  identity={'user_id':1,'scope':'reports:read reports:write'}
  def call(name,args):return mcp_reports.rpc(app.connect,identity,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})[1]['result']
  validation=call('validate_report',doc)['structuredContent'];self.assertTrue(validation['valid'],validation)
  receipt=call('send_report',doc)['structuredContent'];self.assertTrue(receipt['ok']);self.assertEqual(receipt['strategy_proposals'][0]['qualification'],'PILOT')
  read=call('get_latest_report',{'is_test':True})['structuredContent']['report']['data'];self.assertEqual(read,doc)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_only_untampered_builtin_is_pilot(self):
  with app.connect() as c:
   row=c.execute("SELECT * FROM hw_strategies WHERE owner_id=0 AND strategy_id='escape_early_catalyst' AND version='1.0.0'").fetchone();self.assertEqual(strategy_center.deployment(row),'PILOT')
   altered=json.loads(row['payload']);altered['description']='tampered';c.execute('UPDATE hw_strategies SET payload=? WHERE owner_id=0 AND strategy_id=? AND version=?',(json.dumps(altered),row['strategy_id'],row['version']))
   row=c.execute("SELECT * FROM hw_strategies WHERE owner_id=0 AND strategy_id='escape_early_catalyst' AND version='1.0.0'").fetchone();self.assertEqual(strategy_center.deployment(row),'UNQUALIFIED')
 def test_private_pilot_rules_cannot_remove_safety_structure(self):
  bad=copy.deepcopy(hotwatch_strategy.EARLY_CATALYST_V1);bad['strategy_id']='custom-forged';bad['entry_rules']={'all':[{'metric':'price','operator':'>','value':'0'}]}
  engine.upload_strategy(app.connect,1,'test',bad)
  with app.connect() as c:
   row=c.execute("SELECT * FROM hw_strategies WHERE owner_id=1 AND strategy_id='custom-forged'").fetchone();self.assertEqual(strategy_center.deployment(row),'UNQUALIFIED')
  with self.assertRaises(ValueError):strategy_center.save(app.connect,1,{'mode':'manual','strategy_id':'custom-forged','version':'1.0.0'},app.now())
 def test_report_evidence_rejects_future_prices_and_missing_catalyst(self):
  data=copy.deepcopy(self.report);p=data['candidates'][0]['strategy_proposal'];p['pre_news_price']={'price':{'amount':'10','currency':'USD'},'observed_at':(self.now+timedelta(seconds=1)).isoformat(),'available_at':(self.now+timedelta(seconds=1)).isoformat(),'source_ids':['synthetic-source']}
  errors=report_validation.validate(data)['errors'];self.assertIn('future_information',{e['code'] for e in errors})
  del p['pre_news_price'];p['catalyst']=None;errors=report_validation.validate(data)['errors'];self.assertIn('required_evidence',{e['code'] for e in errors})
 def test_pluto_type_evidence_is_retrieved_from_broker_not_report(self):
  adapter=PlutoAdapter(app.connect,1);r=request(False);portfolio={'id':1};asset={'asset':{'id':r['asset_id'],'ticker':r['ticker'],'currency':'USD','exchange':'NASDAQ','type':'CS'},'buyBy':{'shares':True}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=asset),patch('trade_service.fresh_permission'):
   status,at=adapter.tradability(r,'USD',[portfolio])
  self.assertEqual(status,'available');self.assertEqual(adapter.permission_cache[adapter.permission_key(r,'USD',[portfolio])]['instrument_type'],'CS');self.assertIsNotNone(at)
if __name__=='__main__':unittest.main()
