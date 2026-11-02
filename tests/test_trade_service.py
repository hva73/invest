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
  self.calls=[];self.can_trade=True;self.write_result={'orderIntentId':'synthetic-intent'};self.fail_send=False;self.changed=False
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
    elif name=='get_accounts':result={'accounts':[{'currency':'DKK','balance':'1000','buyingPower':'900','reservedForOrders':'100'}]}
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
 def test_search_is_read_only(self):
  self.assertEqual(trade.search(app.connect,1,'TEST',self.factory)['assets'][0]['asset_id'],'asset-test');self.assertFalse(self.writes())
