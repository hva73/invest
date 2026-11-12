"""Disposable database; all broker estimates mocked. Never creates real orders."""
import copy,json,unittest
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import app,report_ingest,hotwatch_engine as engine,hotwatch_buy_plan as plan,trade_service
from hotwatch_strategy import calculate,BASELINE
from hotwatch_contract import EngineError
import test_trade_service as fixtures
from test_hotwatch_engine import request,tick,good_metrics
from test_intel_workflows import merc_report

class BuyPlan(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.Trading();self.fixture.setUp();self.now=engine.utc();self.req=request(False);self.req.update(watch_mode='entry',portfolio_ids=[self.fixture.root]);self.req['risk'].update(proposed_quantity=None,stop_price=None)
  report_ingest.save(app.connect,1,merc_report(False));engine.create(app.connect,1,self.req,self.now)
  self.meta=patch('hotwatch_buy_plan.metadata',return_value={'buyBy':{'amount':True}});self.meta.start()
  self.data={'portfolio_id':self.fixture.root,'budget_dkk':'701','limit_price':'100','stop_price':'95'};self.calls=[]
 def tearDown(self):self.meta.stop();self.fixture.tearDown()
 def estimate(self,connect,uid,p,payload,kind,factory=None,**kwargs):
  self.calls.append(payload);o=payload['orders'][0];q=o.get('shares');cost=str(Decimal(q)*700) if q else o['amount']
  e={'side':'BUY','type':'LIMIT','asset':{'ticker':'MERC','currency':'USD'},'limitPrice':o['limitPrice'],'quantity':q,'commission':'1','commissionCurrency':'DKK','accountNotional':'0' if q else cost,'accountNotionalCurrency':'DKK','filledAccountNotional':cost,'filledAccountNotionalCurrency':'DKK','assetBankFx':{'base':'USD','quote':'DKK','rate':'7'}}
  return {'quote':{'estimate':e}}, {'asset':{'id':self.req['asset_id'],'ticker':'MERC','exchange':'NASDAQ','currency':'USD','type':'CS'},'buyBy':{'shares':True},'fractional':{'buy':True}}
 def prepare(self):
  with patch('trade_service.read_estimate',side_effect=self.estimate):return plan.prepare(app.connect,1,self.req['watch_id'],self.data)
 def row(self,c):return engine.row_for(c,1,self.req['watch_id'],False)
 def test_null_amount_quantity_is_resolved_by_bounded_limit_and_second_estimate(self):
  result=self.prepare();self.assertEqual(result['plan']['quantity'],'1.00000000');self.assertEqual(len(self.calls),2)
  self.assertEqual(self.calls[1]['orders'][0]['shares'],'1.00000000')
  with app.connect() as c:
   row=self.row(c);self.assertEqual(json.loads(row['state'])['signal'],'NO_DATA');self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_unknown_fx_fee_currency_and_quantity_block_save(self):
  for field,value in [('quantity',None),('commissionCurrency','USD'),('assetBankFx',None),('filledAccountNotional',None)]:
   def bad(*args,**kwargs):
    result,asset=self.estimate(*args,**kwargs)
    if 'shares' in args[3]['orders'][0]:result['quote']['estimate'][field]=value
    return result,asset
   with self.subTest(field=field),patch('trade_service.read_estimate',side_effect=bad):
    with self.assertRaises(EngineError):plan.prepare(app.connect,1,self.req['watch_id'],self.data)
 def test_wrong_instrument_cannot_seed_risk(self):
  def bad(*args):
   result,asset=self.estimate(*args);asset['asset']['currency']='EUR';return result,asset
  with patch('trade_service.read_estimate',side_effect=bad),self.assertRaises(EngineError):plan.prepare(app.connect,1,self.req['watch_id'],self.data)
 def test_same_currency_conversion_is_identity_but_foreign_fx_cannot_be_guessed(self):
  order={'shares':'1','limitPrice':'100'}
  raw={'estimate':{'side':'BUY','type':'LIMIT','asset':{'ticker':'MERC','currency':'DKK'},'limitPrice':'100','quantity':'1','commission':'0','commissionCurrency':'DKK','filledAccountNotional':'100','filledAccountNotionalCurrency':'DKK','assetBankFx':None}}
  values=plan.quote(raw,{**self.req,'quote_currency':'DKK'},order);self.assertEqual(values['fx_to_dkk'],'1')
  raw['estimate']['asset']['currency']='USD'
  with self.assertRaises(EngineError):plan.quote(raw,self.req,order)
 def test_whole_shares_are_rounded_down_not_invented(self):
  self.data['budget_dkk']='900'
  def whole(*args):
   result,asset=self.estimate(*args);asset['fractional']['buy']=False;return result,asset
  with patch('hotwatch_buy_plan.metadata',return_value={'buyBy':{'amount':False}}),patch('trade_service.read_estimate',side_effect=whole):r=plan.prepare(app.connect,1,self.req['watch_id'],self.data)
  self.assertEqual(r['plan']['quantity'],'1')
 def test_plan_cannot_resume_paused_watch_or_accept_bad_stop(self):
  self.data['stop_price']='100'
  with self.assertRaises(EngineError):self.prepare()
  self.data['stop_price']='95';engine.control(app.connect,1,self.req['watch_id'],False,'pause')
  with self.assertRaises(EngineError):self.prepare()
 def test_size_scope_price_currency_are_bound_at_proposal_boundary(self):
  p=self.prepare()['plan'];order=plan.order_for(self.req,p);payload={'orders':[order]}
  plan.check_proposal(app.connect,1,self.req['watch_id'],payload,self.fixture.root)
  for key,value in [('shares','2'),('limitPrice','101'),('currency','USD'),('orderType','MARKET')]:
   bad=copy.deepcopy(payload);bad['orders'][0][key]=value
   with self.subTest(key=key),self.assertRaises(trade_service.TradeError):plan.check_proposal(app.connect,1,self.req['watch_id'],bad,self.fixture.root)
  with self.assertRaises(trade_service.TradeError):plan.check_proposal(app.connect,1,self.req['watch_id'],payload,self.fixture.child)
 def test_changed_fee_or_fx_requires_new_plan_before_send(self):
  p=self.prepare()['plan'];payload={'orders':[plan.order_for(self.req,p)]};raw=self.estimate(None,None,None,payload,None)[0]['quote']
  raw['estimate']['commission']='2'
  with self.assertRaises(trade_service.TradeError):plan.check_proposal(app.connect,1,self.req['watch_id'],payload,self.fixture.root,raw)
 def test_risk_uses_limit_for_loss_and_size_and_expires_without_guesses(self):
  self.prepare()
  with app.connect() as c:
   row=self.row(c);req=json.loads(row['request']);sample=tick(self.now,price='99')
   valid,risk,p=plan.apply(c,row,req,sample,req['risk'],engine.utc())
   self.assertEqual(valid['context']['fees_dkk'],'1');self.assertEqual(risk['entry_price'],'100')
   late,risk2,_=plan.apply(c,row,req,sample,req['risk'],engine.utc()+timedelta(seconds=121))
   self.assertIsNone(late['context']['fx_to_dkk']);self.assertIsNone(late['context']['fees_dkk'])
  metrics=good_metrics();risk.update(entry_allowed=True,exit_allowed=False)
  result,_=calculate(valid,metrics,BASELINE,risk,{},self.now)
  self.assertNotIn('RISK_INPUTS_UNKNOWN',result['reason_codes'])
  risk['max_notional_dkk']='700';result,_=calculate(valid,metrics,BASELINE,risk,{},self.now)
  self.assertIn('POSITION_SIZE_LIMIT',result['reason_codes'])
  risk['max_loss_dkk']='30';result,_=calculate(valid,metrics,BASELINE,risk,{},self.now)
  self.assertIn('LOSS_BUDGET_LIMIT',result['reason_codes'])
 def test_limit_exceeded_and_missing_data_can_coexist_with_weak_signal(self):
  self.prepare()
  with app.connect() as c:
   row=self.row(c);req=json.loads(row['request']);sample=tick(self.now,price='101');sample['context']['portfolio_equity_dkk']=None
   sample,risk,_=plan.apply(c,row,req,sample,req['risk'],engine.utc())
  result,_=calculate(sample,{**good_metrics(),'breakout':False},BASELINE,risk,{},self.now)
  d=result['decision_diagnostics'];self.assertEqual(d['strategy'],'NOT_MET');self.assertIn('RISK_INPUTS_UNKNOWN',d['missing_data_codes']);self.assertIn('ENTRY_LIMIT_EXCEEDED',d['blocking_codes'])
 def test_plan_change_cancels_inflight_lease_and_signal_confirmation(self):
  with app.connect() as c:c.execute("UPDATE hw_sessions SET lease_owner='old',lease_until=?,state=?",((self.now+timedelta(seconds=100)).timestamp(),json.dumps({'signal':'BUY','confirmations':3})))
  self.prepare()
  with self.assertRaises(EngineError) as error:engine.ingest(app.connect,1,self.req['watch_id'],False,{},lease='old')
  self.assertEqual(error.exception.code,'lease_lost')

 def test_engine_to_explicit_proposal_rechecks_signal_plan_and_costs(self):
  p=self.prepare()['plan'];first=engine.utc()+timedelta(seconds=1);second=first+timedelta(seconds=32)
  with patch('hotwatch_engine.features',return_value=good_metrics()):
   for n,now in enumerate([first,first+timedelta(seconds=16),second]):
    sample=tick(now,n);sample['source']='pluto'
    engine.ingest(app.connect,1,self.req['watch_id'],False,sample,now)
  data={'report_id':'@hotwatch','expected_side':'BUY','candidate_id':self.req['watch_id'],'portfolio_id':self.fixture.root,'kind':'direct','asset_id':self.req['asset_id'],'size_mode':'shares','size':p['quantity'],'currency':'DKK','order_type':'LIMIT','time_in_force':'DAY','limit_price':p['limit_price']}
  with patch('hotwatch_engine.utc',return_value=second+timedelta(seconds=1)),patch('trade_service.read_estimate',side_effect=self.estimate):
   proposal=trade_service.estimate(app.connect,1,data,self.fixture.factory)['proposal']
   self.assertFalse(self.fixture.writes())
   # Even after explicit review, a different fee blocks before propose_orders.
   def changed(*args,**kwargs):
    result,asset=self.estimate(*args,**kwargs);result['quote']['estimate']['commission']='2';return result,asset
   with patch('trade_service.read_estimate',side_effect=changed),self.assertRaises(trade_service.TradeError):
    trade_service.send(app.connect,1,{'id':proposal['id'],'confirm':True,'review_token':proposal['review_token']},self.fixture.factory)
   self.assertFalse(self.fixture.writes())
   engine.control(app.connect,1,self.req['watch_id'],False,'pause',second+timedelta(seconds=1))
   with self.assertRaises(trade_service.TradeError):trade_service.send(app.connect,1,{'id':proposal['id'],'confirm':True,'review_token':proposal['review_token']},self.fixture.factory)
   self.assertFalse(self.fixture.writes())
 def test_refreshed_costs_cannot_leave_old_buy_signal_active(self):
  p=self.prepare()['plan'];at=engine.utc()+timedelta(seconds=1)
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET status='ACTIVE',state=?,last_data=?,last_calculation=?",(json.dumps({'signal':'BUY'}),at.isoformat(),at.isoformat()))
   p.update(verified_at=(at+timedelta(seconds=1)).isoformat())
   c.execute('UPDATE hw_buy_plans SET payload=?,verified=?',(json.dumps(p),(at+timedelta(seconds=1)).timestamp()))
   current=engine.view(c,self.row(c),at+timedelta(seconds=2))
  self.assertNotEqual(current['signal'],'BUY')

if __name__=='__main__':unittest.main()
