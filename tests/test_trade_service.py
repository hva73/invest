"""Synthetic proposal responses only. Never accesses a broker."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import app,oauth,portfolio_data,portfolios,report_ingest,trade_service as trade
ROOT=Path(__file__).resolve().parents[1]
class Trading(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.previous=app.DB;app.DB=self.tmp.name+'/db';app.init();app.create_user('test-password-long-enough')
  self.env=patch.dict('os.environ',{'ESCAPE_TOKEN_KEY_FILE':self.tmp.name+'/token.key'});self.env.start();oauth.setup_key()
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:root','name':'Root','kind':'portfolio','can_trade':True},{'id':'collections:child','name':'Child','kind':'collection','parent_external_id':'portfolios:root'}])
   self.root=c.execute("SELECT id FROM portfolios WHERE kind='portfolio'").fetchone()[0];self.child=c.execute("SELECT id FROM portfolios WHERE kind='collection'").fetchone()[0]
   c.execute('INSERT INTO oauth_tokens VALUES(?,?,?,?)',(1,oauth.seal(1,{'token':{'access_token':'synthetic'}}),time.time()+3600,time.time()))
  self.report=json.loads((ROOT/'examples/report-v2-test.json').read_text());self.report.update(report_id='trade-source',is_test=False);self.report['data_quality']['status']='mixed';self.report['candidates'][0]['signal']='KØB';report_ingest.save(app.connect,1,self.report)
  self.request={'report_id':'trade-source','candidate_id':self.report['candidates'][0]['candidate_id'],'portfolio_id':self.root,'kind':'direct','asset_id':'asset-test','size_mode':'shares','size':'2','currency':'DKK','order_type':'LIMIT','time_in_force':'DAY','limit_price':'100.50'}
  self.account_data={'accounts':[{'currency':'DKK','balance':'1000','buyingPower':'900','reservedForOrders':'100'}]};self.calls=[];self.can_trade=True;self.write_result={'orderIntentId':'synthetic-intent'};self.fail_send=False;self.changed=False
  case=self
  class Client:
   def __init__(self,token):assert token=='synthetic'
   def tools(self):
    tools=[{'name':name,'inputSchema':spec['inputSchema'],'annotations':{'readOnlyHint':spec['readOnlyHint']}} for name,spec in trade.CONTRACT.items()]
    tools.extend({'name':n,'inputSchema':{'type':'object','properties':{}},'annotations':{'readOnlyHint':True}} for n in ['list_portfolios','list_collections'])
    if case.changed:next(t for t in tools if t['name']=='propose_orders')['inputSchema']={'type':'object'}
    return tools
   def request(self,method,args):
    case.calls.append(args);name=args['name']
    if name=='list_portfolios':result=[{'id':'root','name':'Root','canTrade':case.can_trade}]
    elif name=='list_collections':result=[{'id':'child','name':'Child','portfolioId':'root'}]
    elif name=='get_accounts':result=case.account_data
    elif name=='list_orders':result={'orders':[]}
    elif name=='get_asset':result={'assetId':'asset-test','name':'Synthetic asset','currency':'USD'}
    elif name.startswith('estimate_'):result={'estimatedAmount':'201','currency':'DKK','commission':'0','note':'Synthetic estimate only'}
    elif name.startswith('propose_'):
     if case.fail_send:raise TimeoutError('Synthetic timeout after request')
     result=case.write_result
    elif name=='get_order_intent':result=case.intent_result
    elif name=='search_assets':result={'assets':[{'id':'asset-test','name':'Synthetic asset','ticker':'TEST','isin':'SYNTHETIC','currency':'USD'}]}
    else:raise AssertionError(name)
    return {'structuredContent':result}
  self.factory=Client
  self.intent_result={'orderIntentId':'synthetic-intent','status':'accepted'}
 def tearDown(self):self.env.stop();app.DB=self.previous;self.tmp.cleanup()
 def estimate(self,request=None):return trade.estimate(app.connect,1,request or self.request,self.factory)['proposal']
 def send(self,proposal):return trade.send(app.connect,1,{'id':proposal['id'],'review_token':proposal['review_token'],'confirm':True},self.factory)['proposal']
 def writes(self):return [c for c in self.calls if c['name'].startswith('propose_')]
 def test_buying_power_checked_per_currency_without_guessing(self):
  self.account_data={'accounts':[{'currency':'DKK','buyingPower':'100.127','cash':'500'},{'currency':'EUR','buyingPower':'25','cash':'100'},{'currency':'USD','cash':'200','withdrawalPower':'10'}]}
  request=dict(self.request,report_id='@manual-buy',candidate_id='',size_mode='amount',order_type='MARKET',currency='DKK',size='101')
  with self.assertRaises(trade.InsufficientBuyingPower) as caught:self.estimate(request)
  self.assertEqual((caught.exception.available,caught.exception.currency),('100.12','DKK'))
  self.assertFalse(any(c['name']=='estimate_order' for c in self.calls));self.assertFalse(self.writes())
  request.update(currency='EUR',size='26')
  with self.assertRaises(trade.InsufficientBuyingPower) as caught:self.estimate(request)
  self.assertEqual((caught.exception.available,caught.exception.currency),('25.00','EUR'))
  request.update(currency='USD',size='150');self.assertEqual(self.estimate(request)['status'],'estimated')
  self.assertFalse(self.writes())
 def test_explicit_override_still_requires_pluto_estimate_and_confirmation(self):
  request=dict(self.request,report_id='@manual-buy',candidate_id='',size_mode='amount',order_type='MARKET',size='1000')
  with self.assertRaises(trade.InsufficientBuyingPower):self.estimate(request)
  proposal=self.estimate(dict(request,allow_insufficient=True))
  self.assertTrue(any(c['name']=='estimate_order' for c in self.calls));self.assertFalse(self.writes())
  with self.assertRaises(trade.InsufficientBuyingPower):self.send(proposal)
  sent=trade.send(app.connect,1,{'id':proposal['id'],'review_token':proposal['review_token'],'confirm':True,'allow_insufficient':True},self.factory)['proposal']
  self.assertEqual(sent['status'],'sent');self.assertEqual(len(self.writes()),1)
 def test_override_cannot_bypass_pluto_rejection(self):
  self.account_data={'accounts':[{'currency':'DKK','buyingPower':'25'}]}
  original=self.factory
  class Rejects(original):
   def request(client,method,args):
    if args['name']=='estimate_order':return {'isError':True,'content':[{'type':'text','text':'Not enough buying power: this order needs 200.00 DKK but the DKK account has 26.94 DKK. Choose another currency account or a smaller amount.'}]}
    return super().request(method,args)
  request=dict(self.request,report_id='@manual-buy',candidate_id='',size_mode='amount',order_type='MARKET',size='200',allow_insufficient=True)
  with self.assertRaises(trade.InsufficientBuyingPower) as caught:trade.estimate(app.connect,1,request,Rejects)
  self.assertIn('Not enough buying power',caught.exception.provider_message);self.assertFalse(self.writes())
 def test_buying_power_rechecked_before_send(self):
  request=dict(self.request,report_id='@manual-buy',candidate_id='',size_mode='amount',order_type='MARKET',size='500')
  proposal=self.estimate(request)
  self.account_data={'accounts':[{'currency':'DKK','buyingPower':'100'}]}
  with self.assertRaises(trade.InsufficientBuyingPower) as caught:self.send(proposal)
  self.assertEqual(caught.exception.available,'100.00');self.assertFalse(self.writes())
 def test_ambiguous_or_partial_cash_is_not_treated_as_buying_power(self):
  payload={'orders':[{'side':'BUY','amount':'500','currency':'DKK'}]}
  for accounts in [{'accounts':[{'currency':'DKK','cash':'5','withdrawalPower':'5'}]}, {'accounts':[{'currency':'DKK','buyingPower':'5'},{'currency':'DKK','buyingPower':'5'}]}, {'accounts':[{'currency':'DKK','buyingPower':'5'}],'nextToken':'more'}, {'accounts':[{'currency':'EUR','buyingPower':'5'}]}]:
   trade.check_buying_power(accounts,payload,'direct')
 def test_percentage_sell_uses_fresh_holding_and_rechecks_before_send(self):
  holding={'positions_complete':True,'observed':'2026-11-08T00:00:00Z','positions':[{'kind':'holding','asset_id':'asset-test','quantity':'2.50000001'}]}
  request=dict(self.request,size_mode='percent',size='40',order_type='MARKET')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}),patch('portfolio_data.read',return_value=holding):
   proposal=self.estimate(request)
   self.assertEqual(proposal['payload']['orders'][0]['shares'],'1')
   self.assertEqual(proposal['sell_basis']['percentage'],'40')
   self.assertFalse(self.writes())
   holding['positions'][0]['quantity']='2'
   with self.assertRaisesRegex(trade.TradeError,'ændret'):self.send(proposal)
   self.assertFalse(self.writes())
 def test_percentage_sell_rejects_ambiguous_or_incomplete_holdings(self):
  request=dict(self.request,size_mode='percent',size='50')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}),patch('portfolio_data.read',return_value={'positions_complete':False,'positions':[]}):
   with self.assertRaisesRegex(trade.TradeError,'ufuldstændig'):self.estimate(request)
  self.assertFalse(self.writes())
 def test_percentage_sell_sends_only_the_calculated_number_of_shares(self):
  holding={'positions_complete':True,'observed':'2026-11-08T00:00:00Z','positions':[{'kind':'holding','asset_id':'asset-test','quantity':'8'}]}
  request=dict(self.request,size_mode='percent',size='25',order_type='MARKET')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}),patch('portfolio_data.read',return_value=holding):
   proposal=self.estimate(request);sent=self.send(proposal)
  self.assertEqual(sent['status'],'sent')
  self.assertEqual(self.writes()[0]['arguments']['orders'][0]['shares'],'2')
  self.assertEqual(self.writes()[0]['arguments']['orders'][0]['side'],'SELL')
 def test_manual_sell_uses_actual_holding_and_chosen_percentage(self):
  holding={'positions_complete':True,'observed':'2026-11-08T00:00:00Z','positions':[{'kind':'holding','asset_id':'asset-test','quantity':'8'}]}
  request=dict(self.request,report_id='@manual-sell',candidate_id='',size_mode='percent',size='25',order_type='MARKET')
  with patch('portfolio_data.read',return_value=holding):
   proposal=self.estimate(request);self.assertEqual(proposal['payload']['orders'][0]['shares'],'2');self.assertEqual(self.send(proposal)['status'],'sent')
  self.assertEqual(self.writes()[0]['arguments']['orders'][0]['side'],'SELL')
 def test_percentage_sell_reads_and_normalizes_real_provider_shape(self):
  original=self.factory
  count=None
  class PositionClient(original):
   def tools(client):
    return super().tools()+[{'name':'get_positions','inputSchema':{'type':'object','properties':{'portfolioId':{'type':'string'}},'required':['portfolioId']},'annotations':{'readOnlyHint':True}}]
   def request(client,method,args):
    if args['name']=='get_positions':return {'structuredContent':{'positions':[{'assetId':'asset-test','ticker':'TEST','quantity':'8','currency':'USD'}],**({'totalCount':count} if count is not None else {})}}
    if args['name']=='get_portfolio_value':return {'structuredContent':{'value':'1000','currency':'DKK'}}
    return super().request(method,args)
  request=dict(self.request,size_mode='percent',size='25',order_type='MARKET')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}),patch('pending_orders.enrich'):
   # A positive fixture needs the completeness evidence required in production.
   # Without it the unchanged trading gate must still refuse an estimate.
   with self.assertRaisesRegex(trade.TradeError,'ufuldstændig'):
    trade.estimate(app.connect,1,request,PositionClient)
   self.assertFalse(self.writes())
   count=1
   proposal=trade.estimate(app.connect,1,request,PositionClient)['proposal']
  self.assertEqual(proposal['payload']['orders'][0]['shares'],'2')
  self.assertFalse(self.writes())
 def test_percentage_sell_rejects_truncated_pluto_position_list(self):
  original=self.factory
  class Truncated(original):
   def tools(client):
    return super().tools()+[{'name':'get_positions','inputSchema':{'type':'object','properties':{'portfolioId':{'type':'string'}},'required':['portfolioId']},'annotations':{'readOnlyHint':True}}]
   def request(client,method,args):
    if args['name']=='get_positions':return {'structuredContent':{'positions':[{'assetId':'asset-test','ticker':'TEST','quantity':'8','currency':'USD'}],'totalCount':2}}
    if args['name']=='get_portfolio_value':return {'structuredContent':{'value':'1000','currency':'DKK'}}
    return super().request(method,args)
  request=dict(self.request,size_mode='percent',size='25',order_type='MARKET')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}),patch('pending_orders.enrich'):
   display=portfolio_data.read(app.connect,1,self.root,client_factory=Truncated)
   self.assertTrue(display['positions_complete'])
   self.assertEqual(len(display['positions']),1)
   with self.assertRaisesRegex(trade.TradeError,'ufuldstændig'):trade.estimate(app.connect,1,request,Truncated)
  self.assertFalse(self.writes())
 def test_pluto_total_includes_separate_collections(self):
  original=self.factory
  class WithCollection(original):
   def tools(client):
    return super().tools()+[{'name':'get_positions','inputSchema':{'type':'object','properties':{'portfolioId':{'type':'string'}},'required':['portfolioId']},'annotations':{'readOnlyHint':True}}]
   def request(client,method,args):
    if args['name']=='get_positions':
     positions=[{'assetId':'asset-test','ticker':'TEST','quantity':'8','currency':'USD'}]+[{'assetId':'other-'+str(i),'ticker':'T'+str(i),'quantity':'1','currency':'USD'} for i in range(12)]
     return {'structuredContent':{'positions':positions,'collections':[{'collectionId':'child'}],'totalCount':14}}
    if args['name']=='get_portfolio_value':return {'structuredContent':{'value':'1000','currency':'DKK'}}
    return super().request(method,args)
  request=dict(self.request,size_mode='percent',size='25',order_type='MARKET')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}),patch('pending_orders.enrich'):
   proposal=trade.estimate(app.connect,1,request,WithCollection)['proposal']
  self.assertEqual(proposal['payload']['orders'][0]['shares'],'2')
  self.assertFalse(self.writes())
 def test_hotwatch_signal_is_rechecked_and_asset_is_bound(self):
  session={'status':'ACTIVE','signal':'BUY','display_status':'KØBSSIGNAL','request':{'asset_id':'asset-test','ticker':'TEST','portfolio_ids':[self.root]}}
  request=dict(self.request,report_id='@hotwatch',candidate_id='watch-1',expected_side='BUY',size_mode='amount',size='100',order_type='MARKET')
  # This test isolates source direction; plan binding is tested against real
  # disposable sessions in test_hotwatch_buy_plan.
  with patch('hotwatch_engine.item',return_value={'session':session}),patch('hotwatch_buy_plan.check_proposal'):
   with self.assertRaisesRegex(trade.TradeError,'Aktivet svarer ikke'):self.estimate(dict(request,asset_id='wrong'))
   proposal=self.estimate(request);self.assertFalse(self.writes())
   session['signal']='SELL';session['display_status']='SÆLGSSIGNAL'
   with self.assertRaisesRegex(trade.TradeError,'retning'):self.send(proposal)
  self.assertFalse(self.writes())
 def test_exit_watch_with_unknown_buy_permission_still_requires_sell_review(self):
  # Exit watches deliberately do not check buy permission. They may reach a
  # sell estimate only through a fresh, complete direct holding and permission.
  session={'status':'ACTIVE','signal':'SELL','display_status':'SÆLGSSIGNAL','request':{'asset_id':'asset-test','ticker':'TEST','portfolio_ids':[self.root]},'latest_context':{'status':'verified','position':'held','tradability':'unknown'}}
  request=dict(self.request,report_id='@hotwatch',candidate_id='watch-1',expected_side='SELL',size_mode='percent',size='25',order_type='MARKET')
  holding={'positions_complete':True,'observed':'2026-11-12T20:00:00Z','positions':[{'kind':'holding','asset_id':'asset-test','quantity':'8'}]}
  with patch('hotwatch_engine.item',return_value={'session':session}),patch('portfolio_data.read',return_value=holding):
   proposal=self.estimate(request)
   self.assertEqual(proposal['payload']['orders'][0]['shares'],'2')
   self.assertEqual(proposal['payload']['orders'][0]['side'],'SELL')
   self.assertFalse(self.writes())
   session.update(signal='WAIT',display_status='AFVENT')
   with self.assertRaises(trade.TradeError):self.send(proposal)
   self.assertFalse(self.writes())
 def test_exit_watch_denied_permission_and_collection_do_not_propose(self):
  session={'status':'ACTIVE','signal':'SELL','display_status':'SÆLGSSIGNAL','request':{'asset_id':'asset-test','ticker':'TEST','portfolio_ids':[self.root]}}
  request=dict(self.request,report_id='@hotwatch',candidate_id='watch-1',expected_side='SELL',size_mode='percent',size='25',order_type='MARKET')
  holding={'positions_complete':True,'observed':'2026-11-12T20:00:00Z','positions':[{'kind':'holding','asset_id':'asset-test','quantity':'8'}]}
  with patch('hotwatch_engine.item',return_value={'session':session}),patch('portfolio_data.read',return_value=holding):
   self.can_trade=False
   with self.assertRaisesRegex(trade.TradeError,'handelsadgang'):self.estimate(request)
   session['request']['portfolio_ids']=[self.child]
   with self.assertRaises(trade.TradeError):self.estimate(dict(request,portfolio_id=self.child))
   with self.assertRaises(trade.TradeError):self.estimate(dict(request,portfolio_id=self.child,kind='collection_sell',size_mode='shares'))
   self.assertFalse(self.writes())
 def test_hotwatch_estimate_binds_direction_before_and_after_position_lookup(self):
  request=dict(self.request,report_id='@hotwatch',candidate_id='watch-1',expected_side='SELL',size_mode='percent',size='25',order_type='MARKET')
  sell={'signal':'SÆLG','asset_id':'asset-test','portfolio_ids':[self.root]};buy={**sell,'signal':'KØB'}
  with patch('trade_service.signal_source',side_effect=[sell,buy]),patch('trade_service.direct_sell_basis',return_value={'shares':'2','quantity':'8','percentage':'25'}):
   with self.assertRaisesRegex(trade.TradeError,'retning er ændret'):self.estimate(request)
  self.assertFalse(any(c['name']=='estimate_order' for c in self.calls));self.assertFalse(self.writes())
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
 def test_hotwatch_estimate_requires_the_selected_direction(self):
  request=dict(self.request,report_id='@hotwatch',candidate_id='watch-1',size_mode='shares',size='2')
  sell={'signal':'SÆLG','asset_id':'asset-test','portfolio_ids':[self.root]}
  with patch('trade_service.signal_source',return_value=sell):
   with self.assertRaisesRegex(trade.TradeError,'retning mangler'):self.estimate(request)
   with self.assertRaisesRegex(trade.TradeError,'retning er ændret'):self.estimate(dict(request,expected_side='BUY'))
  self.assertFalse(self.calls);self.assertFalse(self.writes())
 def test_report_percentage_sell_cannot_become_buy_between_reads(self):
  request=dict(self.request,size_mode='percent',size='25',order_type='MARKET')
  with patch('trade_service.signal_source',side_effect=[{'signal':'SÆLG'},{'signal':'KØB'}]),patch('trade_service.direct_sell_basis',return_value={'shares':'2','quantity':'8','percentage':'25'}):
   with self.assertRaisesRegex(trade.TradeError,'retning er ændret'):self.estimate(request)
  self.assertFalse(any(c['name']=='estimate_order' for c in self.calls));self.assertFalse(self.writes())
 def test_signal_reversal_during_provider_estimate_is_not_returned_as_reviewable(self):
  request=dict(self.request,report_id='@hotwatch',candidate_id='watch-1',expected_side='BUY',size_mode='amount',size='100',order_type='MARKET')
  buy={'signal':'KØB','asset_id':'asset-test','portfolio_ids':[self.root]};sell={**buy,'signal':'SÆLG'}
  with patch('trade_service.signal_source',side_effect=[buy,sell]),patch('trade_service.read_estimate',return_value=({'quote':{}},{})),patch('hotwatch_buy_plan.check_proposal'):
   with self.assertRaisesRegex(trade.TradeError,'retning'):self.estimate(request)
  with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM broker_proposals WHERE status='estimated'").fetchone()[0],0)
  self.assertFalse(self.writes())
 def test_report_signal_reversal_cannot_send_the_old_order(self):
  proposal=self.estimate()
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}):
   with self.assertRaisesRegex(trade.TradeError,'retning'):self.send(proposal)
  self.assertFalse(self.writes())
 def test_manual_buy_requires_asset_amount_review_and_can_only_buy(self):
  request=dict(self.request,report_id='@manual-buy',candidate_id='',size_mode='amount',size='20',order_type='MARKET')
  proposal=self.estimate(request)
  self.assertEqual(proposal['candidate_id'],'asset-test')
  self.assertEqual(proposal['payload']['orders'][0]['side'],'BUY')
  self.assertEqual(proposal['payload']['orders'][0]['amount'],'20')
  self.assertFalse(self.writes())
  with self.assertRaises(trade.TradeError):trade.send(app.connect,1,{'id':proposal['id'],'confirm':False,'review_token':proposal['review_token']},self.factory)
  self.assertFalse(self.writes())
  self.assertEqual(self.send(proposal)['status'],'sent')
  self.assertEqual(len(self.writes()),1)
  with self.assertRaises(trade.TradeError):self.estimate(dict(request,size_mode='shares'))
 def test_test_signal_is_scoped_temporary_and_does_not_trade(self):
  from tasks.pepe_test_signal import enable
  enable(app.DB,'owner','Root',now=1000)
  with app.connect() as c:
   signal=trade.active_test_signal(c,1,now=1001)
   self.assertEqual((signal['ticker'],signal['side'],signal['portfolio_id']),('PEPE','BUY',self.root))
   self.assertIsNone(trade.active_test_signal(c,1,now=4601))
   self.assertIsNone(trade.active_test_signal(c,2,now=1001))
  with self.assertRaises(ValueError):enable(app.DB,'owner','Unknown',now=1000)
  self.assertFalse(self.writes());self.assertEqual(trade.history(app.connect,1),[])
 def test_pluto_batch_reference_matches_exact_order(self):
  order={'assetId':'known','side':'BUY','orderType':'MARKET','timeInForce':'DAY'}
  raw={'orderIntents':[{**order,'orderIntentId':'intent-1'}]}
  self.assertEqual(trade.intent_reference(raw,{'orders':[order]}),'intent-1')
  self.assertIsNone(trade.intent_reference(raw,{'orders':[{**order,'assetId':'other'}]}))
  self.assertIsNone(trade.intent_reference({'orderIntents':raw['orderIntents']*2},{'orders':[order]}))
  row={'payload':json.dumps({'orders':[order]}),'response':json.dumps(raw),'estimate':None,'asset':None,'sell_basis':None,'status':'uncertain','intent_id':None,'error':'uafklaret'}
  self.assertEqual(trade.view(row)['status'],'sent');self.assertEqual(trade.view(row)['intent_id'],'intent-1')
 def test_cancel_only_own_pending_intent_and_confirm_provider_status(self):
  proposal=self.send(self.estimate());original=self.factory;state={'status':'PENDING','calls':0}
  class CancelClient(original):
   def request(client,method,args):
    if args['name']=='get_order_intent':return {'structuredContent':{'orderIntentId':'synthetic-intent','status':state['status']}}
    if args['name']=='cancel_order_intent':state['calls']+=1;state['status']='CANCELLED';return {'structuredContent':{'success':True}}
    return super().request(method,args)
  result=trade.cancel_intent(app.connect,1,proposal['id'],CancelClient)
  self.assertTrue(result['cancelled']);self.assertEqual(result['proposal']['response']['status'],'CANCELLED');self.assertEqual(state['calls'],1)
  self.assertTrue(trade.cancel_intent(app.connect,1,proposal['id'],CancelClient)['already_final']);self.assertEqual(state['calls'],1)
  with self.assertRaises(trade.TradeError):trade.cancel_intent(app.connect,2,proposal['id'],CancelClient)
  state['status']='ACCEPTED';result=trade.cancel_intent(app.connect,1,proposal['id'],CancelClient)
  self.assertFalse(result['cancelled']);self.assertEqual(state['calls'],1)
 def test_preview_provider_error_and_credentials(self):
  original=self.factory
  class Failed(original):
   token='synthetic-secret-token'
   def request(client,method,args):
    if args['name']=='estimate_order':return {'isError':True,'content':[{'type':'text','text':'Amount orders are not supported for this asset. Bearer synthetic-secret-token'}]}
    return super().request(method,args)
  request=dict(self.request,side='BUY',size_mode='amount',size='100',order_type='MARKET')
  with self.assertRaises(trade.TradeError) as caught:trade.preview(app.connect,1,request,Failed)
  message=str(caught.exception);self.assertIn('Amount orders are not supported',message);self.assertNotIn('synthetic-secret-token',message);self.assertNotIn('listen er bevaret',message)
  self.assertFalse(self.writes());self.assertEqual(trade.history(app.connect,1),[])
  permission=trade.estimate_error({'structuredContent':{'error':{'message':'This connection may only read. Reconnect Pluto and tick Also let it propose orders.'}}},Failed('synthetic'))
  self.assertIn('kun læseadgang',permission);self.assertIn('Forbindelser',permission)
  hidden=trade.estimate_error({'structuredContent':{'error':{'message':'password="two secret words"'}}},Failed('synthetic'))
  self.assertNotIn('secret words',hidden)
 def test_observed_pluto_insufficient_funds_message_is_used_before_submission(self):
  self.account_data={'accounts':[{'currency':'DKK','cash':'26.94','withdrawalPower':'26.94'}]}
  original=self.factory
  class Failed(original):
   def request(client,method,args):
    if args['name']=='estimate_order':return {'isError':True,'content':[{'type':'text','text':'Not enough buying power: this order needs 200.00 DKK but the DKK account has 26.94 DKK. Choose another currency account or a smaller amount.'}]}
    return super().request(method,args)
  request=dict(self.request,side='BUY',size_mode='amount',size='200',order_type='MARKET')
  with self.assertRaises(trade.InsufficientBuyingPower) as caught:trade.preview(app.connect,1,request,Failed)
  self.assertEqual((caught.exception.available,caught.exception.currency),('26.94','DKK'))
  self.assertIsNone(trade.provider_buying_power_error('Not enough buying power: this order needs 200.00 DKK but the EUR account has 26.94 EUR.',{'side':'BUY','currency':'DKK','amount':'200'}))
  self.assertFalse(self.writes());self.assertEqual(trade.history(app.connect,1),[])
 def test_preview_structured_rejection_and_asset_capabilities(self):
  original=self.factory
  class Failed(original):
   def request(client,method,args):
    if args['name']=='estimate_order':return {'structuredContent':{'success':False,'error':{'message':'Insufficient buying power'}}}
    return super().request(method,args)
  request=dict(self.request,side='BUY')
  with self.assertRaisesRegex(trade.TradeError,'Insufficient buying power'):trade.preview(app.connect,1,request,Failed)
  class Unsupported(original):
   def request(client,method,args):
    if args['name']=='get_asset':return {'structuredContent':{'asset':{'id':'asset-test'},'buyBy':{'amount':False,'shares':True}}}
    if args['name']=='estimate_order':raise AssertionError('Unsupported sizing must stop before estimate')
    return super().request(method,args)
  with self.assertRaisesRegex(trade.TradeError,'størrelsestype'):trade.preview(app.connect,1,dict(request,size_mode='amount'),Unsupported)
  self.assertFalse(self.writes());self.assertEqual(trade.history(app.connect,1),[])
 def test_quote_review_send_and_no_execution(self):
  q=self.estimate();self.assertEqual(q['status'],'estimated');self.assertFalse(self.writes());self.assertEqual(q['payload']['orders'][0]['limitPrice'],'100.5')
  result=self.send(q);self.assertEqual(result['status'],'sent');self.assertEqual(result['intent_id'],'synthetic-intent');self.assertEqual(len(self.writes()),1)
  self.assertTrue(trade.send(app.connect,1,{'id':q['id']},self.factory)['duplicate']);self.assertEqual(len(self.writes()),1)
  checked=trade.check(app.connect,1,q['id'],self.factory)['proposal'];self.assertEqual(checked['response']['status'],'accepted');self.assertEqual(checked['status'],'sent')
  self.assertEqual(set(c['name'] for c in self.calls),{'list_portfolios','get_accounts','list_orders','get_asset','estimate_order','propose_orders','get_order_intent'})
 def test_check_rejects_unverified_identity_and_preserves_prior_record(self):
  self.write_result.update(status='PENDING',orderId='original-order')
  proposal=self.send(self.estimate())
  pid=proposal['id'];prior=dict(trade.get(app.connect,1,pid))
  valid={'orderIntentId':'synthetic-intent','portfolioId':'root','assetId':'asset-test','side':'BUY','orderId':'original-order','status':'accepted'}
  replies=[[],{'status':'accepted'},dict(valid,orderIntentId='other-intent'),dict(valid,portfolioId='other-depot'),
           dict(valid,assetId='other-asset'),dict(valid,side='SELL'),dict(valid,orderId='other-order'),
           {key:value for key,value in valid.items() if key!='orderId'}]
  for reply in replies:
   with self.subTest(reply=reply):
    self.intent_result=reply
    with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
     trade.check(app.connect,1,pid,self.factory)
    self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
  self.intent_result=valid
  calls=len(self.calls)
  with self.assertRaisesRegex(trade.TradeError,'din konto'):
   trade.check(app.connect,2,pid,self.factory)
  self.assertEqual(len(self.calls),calls)
  self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
  checked=trade.check(app.connect,1,pid,self.factory)['proposal']
  self.assertEqual(checked['response'],valid)
  self.assertEqual(checked['status'],'sent')
  self.assertEqual(checked['report_id'],proposal['report_id'])
  self.assertEqual(len(self.writes()),1)
 def test_check_recovers_from_unrelated_historical_response(self):
  pid=self.send(self.estimate())['id']
  valid={'orderIntentId':'synthetic-intent','status':'PENDING'}
  for response in (
      {'orderIntentId':'other-intent','status':'ACCEPTED'},
      {'orderIntentId':'other-intent','status':'ACCEPTED','orderId':'other-order'},
      {'status':'ACCEPTED','orderId':'other-order'}):
   with self.subTest(response=response):
    with app.connect() as c:
     c.execute('UPDATE broker_proposals SET response=? WHERE id=?',(json.dumps(response),pid))
    prior=dict(trade.get(app.connect,1,pid))
    for reply in ({'status':'PENDING'},dict(valid,orderId='other-order')):
     self.intent_result=reply
     with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
      trade.check(app.connect,1,pid,self.factory)
     self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
    self.intent_result=valid
    checked=trade.check(app.connect,1,pid,self.factory)['proposal']
    self.assertEqual(checked['response'],valid)
    self.assertEqual(checked['status'],'sent')

 def test_check_recovers_from_contradicted_request_identity(self):
  pid=self.send(self.estimate())['id']
  accepted={'orderIntentId':'synthetic-intent','status':'ACCEPTED'}
  for identity,correction in (
      ({'portfolioId':'other-depot'},{'portfolioId':'root'}),
      ({'portfolioId':'other-depot','orderId':'unrelated'},{'portfolioId':'root'}),
      ({'portfolioId':'root','orderIntents':[dict(accepted,portfolioId='other-depot')]},{'portfolioId':'root'}),
      ({'portfolioId':'other-depot','orderIntents':[{'orderIntentId':'other-intent','orderId':'unrelated'}]},
       {'portfolioId':'root'}),
      ({'side':'SELL','orderId':'unrelated'},{'side':'BUY'}),
      ({'portfolioId':'other-depot','assetId':'other-asset'},{'portfolioId':'root','assetId':'asset-test'})):
   with self.subTest(identity=identity):
    valid=dict(accepted,**correction)
    response={'orderIntentId':'synthetic-intent','status':'PENDING',**identity}
    with app.connect() as c:
     c.execute('UPDATE broker_proposals SET response=? WHERE id=?',(json.dumps(response),pid))
    prior=dict(trade.get(app.connect,1,pid))
    incomplete=[{key:value for key,value in valid.items() if key!=field} for field in correction]
    for reply in [dict(valid,portfolioId='other-depot'),dict(valid,orderId='unrelated'),*incomplete]:
     self.intent_result=reply
     with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
      trade.check(app.connect,1,pid,self.factory)
     self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
    self.intent_result=valid
    checked=trade.check(app.connect,1,pid,self.factory)['proposal']
    self.assertEqual(checked['response'],valid)
    self.assertEqual(checked['status'],'sent')

 def test_conflicting_response_cannot_supply_its_own_recovery_reference(self):
  pid=self.send(self.estimate())['id']
  previous={'orderIntentId':'synthetic-intent','portfolioId':'other-depot','status':'PENDING'}
  with app.connect() as c:
   c.execute("UPDATE broker_proposals SET intent_id=NULL,status='uncertain',response=? WHERE id=?",
             (json.dumps(previous),pid))
  prior=dict(trade.get(app.connect,1,pid))
  self.intent_result=dict(previous,portfolioId='root',status='ACCEPTED')
  with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
   trade.check(app.connect,1,pid,self.factory)
  self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)

 def test_check_only_reuses_order_id_from_compatible_prior_identity(self):
  self.write_result['orderId']='original-order'
  pid=self.send(self.estimate())['id']
  intent={'orderIntentId':'synthetic-intent','orderId':'original-order'}
  self.intent_result=dict(intent,status='ACCEPTED')
  for identity_fields,conflicting in (
      ({'portfolioId':'other-depot'},True),
      ({'portfolioId':'root','orderIntents':[dict(intent,portfolioId='other-depot')]},True),
      ({'assetId':'other-asset'},True),
      ({'assetId':'asset-test','orderIntents':[dict(intent,assetId='other-asset')]},True),
      ({'portfolioId':'root','assetId':'asset-test'},False),
      ({'orderIntents':[dict(intent,assetId='asset-test')]},False),
      ({},False)):
   with self.subTest(identity_fields=identity_fields):
    response=dict(intent,status='PENDING',**identity_fields)
    with app.connect() as c:
     c.execute('UPDATE broker_proposals SET response=? WHERE id=?',(json.dumps(response),pid))
    prior=dict(trade.get(app.connect,1,pid))
    if conflicting:
     with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
      trade.check(app.connect,1,pid,self.factory)
     self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
    else:
     checked=trade.check(app.connect,1,pid,self.factory)['proposal']
     self.assertEqual(checked['response'],self.intent_result)
     self.assertEqual(checked['status'],'sent')

 def test_check_rejects_all_conflicting_historical_identity_fields(self):
  proposal=self.estimate()
  pid=self.send(proposal)['id']
  intent={'orderIntentId':'synthetic-intent','orderId':'original-order'}
  order=proposal['payload']['orders'][0]
  conflicts={'portfolioId':'other-depot','collectionId':'other-collection',
             'assetId':'other-asset','side':'SELL','orderType':'invalid-type',
             'timeInForce':'invalid-tif'}
  self.intent_result=dict(intent,status='ACCEPTED')
  for field,value in conflicts.items():
   for nested in (False,True):
    with self.subTest(field=field,nested=nested):
     response=dict(intent,status='PENDING')
     if nested:response['orderIntents']=[dict(intent,**{field:value})]
     else:response[field]=value
     with app.connect() as c:
      c.execute('UPDATE broker_proposals SET response=? WHERE id=?',(json.dumps(response),pid))
     prior=dict(trade.get(app.connect,1,pid))
     with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
      trade.check(app.connect,1,pid,self.factory)
     self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)

 def test_check_cannot_bind_a_new_order_id(self):
  self.write_result['status']='PENDING'
  pid=self.send(self.estimate())['id'];prior=dict(trade.get(app.connect,1,pid))
  valid={'orderIntentId':'synthetic-intent','status':'ACCEPTED'}
  for reply in (dict(valid,orderId='unrelated'),dict(valid,orderId=None),
                dict(valid,orderIntents=[{'orderIntentId':'synthetic-intent','orderId':'unrelated'}])):
   with self.subTest(reply=reply):
    self.intent_result=reply
    with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
     trade.check(app.connect,1,pid,self.factory)
    self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
  self.intent_result=valid
  self.assertEqual(trade.check(app.connect,1,pid,self.factory)['proposal']['response'],valid)

 def test_unchecked_history_cannot_corroborate_additional_ids(self):
  direct=self.send(self.estimate())
  self.write_result={'orderIntentId':'collection-intent'}
  request=dict(self.request,portfolio_id=self.child,kind='collection_sell',size='25')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}):
   collection=self.send(self.estimate(request))
  for proposal,field,value in ((direct,'orderId','unrelated'),(collection,'portfolioId','other-depot')):
   pid=proposal['id'];accepted={'orderIntentId':proposal['intent_id'],'status':'ACCEPTED'}
   for nested in (True,False):
    with self.subTest(field=field,nested=nested):
     identity={'orderIntentId':proposal['intent_id'],field:value}
     history=dict(accepted,status='PENDING')
     if nested:history['orderIntents']=[identity]
     else:history.update(identity)
     with app.connect() as c:
      c.execute('UPDATE broker_proposals SET response=?,sent_identity=NULL WHERE id=?',(json.dumps(history),pid))
     prior=dict(trade.get(app.connect,1,pid))
     self.intent_result=dict(accepted,**{field:value})
     with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
      trade.check(app.connect,1,pid,self.factory)
     self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
     self.intent_result=accepted
     self.assertEqual(trade.check(app.connect,1,pid,self.factory)['proposal']['response'],accepted)

 def test_collection_receipt_cannot_corroborate_another_depot_or_its_order(self):
  request=dict(self.request,portfolio_id=self.child,kind='collection_sell',size='25')
  self.write_result.update(portfolioId='other-depot',collectionId='child',orderId='other-order')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}):
   pid=self.send(self.estimate(request))['id']
  prior=dict(trade.get(app.connect,1,pid))
  valid={'orderIntentId':'synthetic-intent','collectionId':'child','status':'ACCEPTED'}
  for field in ('portfolioId','orderId'):
   with self.subTest(field=field):
    self.intent_result=dict(valid,**{field:self.write_result[field]})
    with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
     trade.check(app.connect,1,pid,self.factory)
    self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
  self.intent_result=valid
  self.assertEqual(trade.check(app.connect,1,pid,self.factory)['proposal']['response'],valid)

 def test_verified_reply_recovers_from_malformed_historical_nesting(self):
  pid=self.send(self.estimate())['id']
  valid={'orderIntentId':'synthetic-intent','portfolioId':'root','status':'ACCEPTED'}
  for malformed in ([{}],[{'assetId':'unrelated'}],[],None,[1,2]):
   with self.subTest(malformed=malformed):
    history=dict(valid,status='PENDING',orderIntents=malformed)
    with app.connect() as c:
     c.execute('UPDATE broker_proposals SET response=? WHERE id=?',(json.dumps(history),pid))
    prior=dict(trade.get(app.connect,1,pid))
    self.intent_result=dict(valid,orderIntents=malformed)
    with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
     trade.check(app.connect,1,pid,self.factory)
    self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
    self.intent_result=valid
    checked=trade.check(app.connect,1,pid,self.factory)['proposal']
    self.assertEqual((checked['response'],checked['status']),(valid,'sent'))

 def test_check_validates_nested_order_identity_before_replacing_evidence(self):
  estimated=self.estimate()
  item={**estimated['payload']['orders'][0],'orderIntentId':'synthetic-intent','orderId':'original-order'}
  self.write_result={'orderIntents':[item]}
  pid=self.send(estimated)['id'];prior=dict(trade.get(app.connect,1,pid))
  valid={'orderIntentId':'synthetic-intent','status':'ACCEPTED','orderIntents':[item]}
  for conflict in ({'orderIntentId':'other-intent'},{'assetId':'other-asset'},
                   {'portfolioId':'other-depot'},{'orderId':'other-order'},{'orderIntentId':None}):
   with self.subTest(conflict=conflict):
    self.intent_result=dict(valid,orderIntents=[dict(item,**conflict)])
    with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
     trade.check(app.connect,1,pid,self.factory)
    self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
  self.intent_result=valid
  self.assertEqual(trade.check(app.connect,1,pid,self.factory)['proposal']['response'],valid)

 def test_check_collection_sell_uses_historical_depot_after_reparenting(self):
  request=dict(self.request,portfolio_id=self.child,kind='collection_sell',size='25')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}):
   estimated=self.estimate(request)
   self.write_result.update(portfolioId='root',collectionId='child',status='PENDING')
   pid=self.send(estimated)['id']
  with app.connect() as c:
   c.execute("UPDATE portfolios SET parent_external_id='portfolios:new-root' WHERE id=?",(self.child,))
  prior=dict(trade.get(app.connect,1,pid))
  valid=dict(self.write_result,status='ACCEPTED')
  for reply in (dict(valid,portfolioId='new-root'),{'orderIntentId':'synthetic-intent','status':'ACCEPTED'}):
   with self.subTest(reply=reply):
    self.intent_result=reply
    with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
     trade.check(app.connect,1,pid,self.factory)
    self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
  self.intent_result=valid
  self.assertEqual(trade.check(app.connect,1,pid,self.factory)['proposal']['response'],valid)

 def test_collection_sell_readback_cannot_bind_unverified_depot(self):
  request=dict(self.request,portfolio_id=self.child,kind='collection_sell',size='25')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}):
   pid=self.send(self.estimate(request))['id']
  with app.connect() as c:
   c.execute("UPDATE portfolios SET parent_external_id='portfolios:other-root' WHERE id=?",(self.child,))
  prior=dict(trade.get(app.connect,1,pid))
  valid={'orderIntentId':'synthetic-intent','collectionId':'child','status':'ACCEPTED'}
  for reply in (dict(valid,portfolioId='root'),dict(valid,portfolioId='other-root'),
                dict(valid,portfolioId=None),dict(valid,collectionId='other'),
                dict(valid,orderIntents=[{'orderIntentId':'synthetic-intent','portfolioId':'root'}])):
   with self.subTest(reply=reply):
    self.intent_result=reply
    with self.assertRaisesRegex(trade.TradeError,'forslagsidentiteten'):
     trade.check(app.connect,1,pid,self.factory)
    self.assertEqual(dict(trade.get(app.connect,1,pid)),prior)
  self.intent_result=valid
  self.assertEqual(trade.check(app.connect,1,pid,self.factory)['proposal']['response'],valid)

 def test_isolation_confirmation_and_expiry(self):
  q=self.estimate()
  with self.assertRaises(trade.TradeError):trade.send(app.connect,2,{'id':q['id'],'confirm':True,'review_token':q['review_token']},self.factory)
  with self.assertRaises(trade.TradeError):trade.send(app.connect,1,{'id':q['id'],'confirm':True,'review_token':'wrong'},self.factory)
  with app.connect() as c:c.execute('UPDATE broker_proposals SET estimated=?',(time.time()-121,))
  with self.assertRaises(trade.TradeError):self.send(q)
  self.assertFalse(self.writes());self.assertEqual(trade.history(app.connect,2),[])
 def test_changed_permission_or_contract_stops_before_send(self):
  q=self.estimate();self.can_trade=False
  with self.assertRaises(trade.TradeError):self.send(q)
  self.can_trade=True;self.changed=True
  with self.assertRaises(trade.TradeError):self.send(q)
  self.assertFalse(self.writes())
 def test_timeout_and_unknown_reply_are_not_retried(self):
  q=self.estimate();self.fail_send=True;self.assertEqual(self.send(q)['status'],'uncertain')
  self.assertTrue(trade.send(app.connect,1,{'id':q['id']},self.factory)['duplicate']);self.assertEqual(len(self.writes()),1)
  self.assertEqual(self.estimate()['status'],'uncertain');self.assertEqual(len(self.writes()),1)
 def test_unknown_reply_stays_uncertain(self):
  self.write_result={'message':'synthetic unknown envelope'};self.assertEqual(self.send(self.estimate())['status'],'uncertain')
 def test_no_test_history_or_old_signal(self):
  request=dict(self.request,report_id=self.report['report_id']+'-test')
  test=copy.deepcopy(self.report);test.update(report_id=request['report_id'],is_test=True);report_ingest.save(app.connect,1,test)
  with self.assertRaises(trade.TradeError):self.estimate(request)
  changed=copy.deepcopy(self.report);changed.update(report_id='newer-report',generated_at='2027-01-01T00:00:00Z');changed['candidates'][0]['signal']='AFVENT';report_ingest.save(app.connect,1,changed)
  with self.assertRaises(trade.TradeError):self.estimate()
 def test_input_validation_and_collections_are_distinct(self):
  for change in [{'size':'NaN'},{'size':'-1'},{'size':'1,5'},{'limit_price':'1.001'},{'order_type':'MARKET','time_in_force':'GTC'},{'portfolio_id':self.child}]:
   with self.assertRaises(trade.TradeError):self.estimate(dict(self.request,**change))
  q=self.estimate(dict(self.request,portfolio_id=self.child,kind='collection_buy',size='100'))
  self.assertEqual(q['payload'],{'collectionId':'child','currency':'DKK','portfolioId':'root','amount':'100'})
  self.send(q);self.assertEqual(self.writes()[0]['name'],'propose_buy_collection')
 def test_collection_sell_percentage_and_direct_sell_shares(self):
  sell=copy.deepcopy(self.report);sell.update(report_id='sell-report',generated_at='2027-01-01T00:00:00Z');sell['candidates'][0]['signal']='SÆLG';report_ingest.save(app.connect,1,sell)
  req=dict(self.request,report_id='sell-report',portfolio_id=self.child,kind='collection_sell',size='25')
  q=self.estimate(req);self.assertEqual(q['payload']['percentage'],25);self.send(q);self.assertEqual(self.writes()[0]['name'],'propose_sell_collection')
  with self.assertRaises(trade.TradeError):self.estimate(dict(req,size='101'))
  with self.assertRaises(trade.TradeError):self.estimate(dict(self.request,report_id='sell-report',size_mode='amount'))
 def test_pending_identical_order_from_new_report_is_not_duplicated(self):
  q=self.estimate();self.send(q)
  newer=copy.deepcopy(self.report);newer.update(report_id='new-same-signal',generated_at='2027-01-01T00:00:00Z');report_ingest.save(app.connect,1,newer)
  again=trade.estimate(app.connect,1,dict(self.request,report_id='new-same-signal',size='2.00'),self.factory)
  self.assertTrue(again['duplicate']);self.assertEqual(again['proposal']['id'],q['id']);self.assertEqual(len(self.writes()),1)
 def test_concurrent_double_click_sends_one_proposal(self):
  import concurrent.futures
  q=self.estimate()
  with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.send(q),range(2)))
  self.assertEqual(len(self.writes()),1);self.assertTrue(all(r['status'] in ['sending','sent'] for r in results))
  self.assertEqual(trade.summaries(app.connect,2),[]);self.assertEqual(trade.summaries(app.connect,1)[0]['report_id'],'trade-source')
 def test_standalone_preview_needs_no_signal_and_creates_no_draft(self):
  watch=copy.deepcopy(self.report);watch.update(report_id='watch-only',generated_at='2027-01-01T00:00:00Z');watch['candidates'][0]['signal']='OVERVÅG';report_ingest.save(app.connect,1,watch)
  request={k:v for k,v in self.request.items() if k not in ['report_id','candidate_id']};request.update(side='BUY',confirm=True,method='propose_orders')
  result=trade.preview(app.connect,1,request,self.factory)
  self.assertTrue(result['read_only']);self.assertNotIn('id',result);self.assertNotIn('review_token',result);self.assertEqual(result['payload']['orders'][0]['side'],'BUY');self.assertEqual(trade.history(app.connect,1),[]);self.assertFalse(self.writes())
  with self.assertRaises(trade.TradeError):trade.send(app.connect,1,{'id':0,'confirm':True,'review_token':'none'},self.factory)
  with self.assertRaises(trade.TradeError):self.estimate(request)
  self.assertEqual(trade.history(app.connect,1),[])
 def test_preview_validates_ownership_kind_and_size(self):
  req=dict(self.request,side='SELL')
  for change in [{'portfolio_id':''},{'size_mode':'amount'},{'side':'EXECUTE'},{'kind':'collection_buy','portfolio_id':self.child},{'size':'-1'}]:
   with self.assertRaises(trade.TradeError):trade.preview(app.connect,1,dict(req,**change),self.factory)
  with self.assertRaises(trade.TradeError):trade.preview(app.connect,2,req,self.factory)
  self.assertEqual(trade.history(app.connect,1),[]);self.assertFalse(self.writes())
 def test_search_is_read_only(self):
  self.assertEqual(trade.search(app.connect,1,'TEST',self.factory)['assets'][0]['asset_id'],'asset-test');self.assertFalse(self.writes())
