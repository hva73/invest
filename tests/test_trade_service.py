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
    elif name=='get_order_intent':result={'orderIntentId':'synthetic-intent','status':'accepted'}
    elif name=='search_assets':result={'assets':[{'id':'asset-test','name':'Synthetic asset','ticker':'TEST','isin':'SYNTHETIC','currency':'USD'}]}
    else:raise AssertionError(name)
    return {'structuredContent':result}
  self.factory=Client
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
  class PositionClient(original):
   def tools(client):
    return super().tools()+[{'name':'get_positions','inputSchema':{'type':'object','properties':{'portfolioId':{'type':'string'}},'required':['portfolioId']},'annotations':{'readOnlyHint':True}}]
   def request(client,method,args):
    if args['name']=='get_positions':return {'structuredContent':{'positions':[{'assetId':'asset-test','ticker':'TEST','quantity':'8','currency':'USD'}]}}
    if args['name']=='get_portfolio_value':return {'structuredContent':{'value':'1000','currency':'DKK'}}
    return super().request(method,args)
  request=dict(self.request,size_mode='percent',size='25',order_type='MARKET')
  with patch('trade_service.candidate',return_value={'signal':'SÆLG'}),patch('pending_orders.enrich'):
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
  session={'status':'ACTIVE','signal':'BUY','display_status':'KØBSSIGNAL','request':{'asset_id':'asset-test','ticker':'TEST'}}
  request=dict(self.request,report_id='@hotwatch',candidate_id='watch-1',size_mode='amount',size='100',order_type='MARKET')
  with patch('hotwatch_engine.item',return_value={'session':session}):
   with self.assertRaisesRegex(trade.TradeError,'Aktivet svarer ikke'):self.estimate(dict(request,asset_id='wrong'))
   proposal=self.estimate(request);self.assertFalse(self.writes())
   session['signal']='SELL';session['display_status']='SÆLGSSIGNAL'
   with self.assertRaisesRegex(trade.TradeError,'retning'):self.send(proposal)
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
