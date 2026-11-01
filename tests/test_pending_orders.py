"""Synthetic pending-order fixtures; no real orders or brokerage data."""
import tempfile,time,unittest
from unittest.mock import patch
import app,oauth,portfolios,portfolio_data,pending_orders

class Pending(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=app.DB;app.DB=self.tmp.name+'/orders.db';app.init();app.create_user('a-test-password-long')
  self.env=patch.dict('os.environ',{'ESCAPE_TOKEN_KEY_FILE':self.tmp.name+'/token.key'});self.env.start();oauth.setup_key()
  with app.connect() as c:
   c.execute("INSERT INTO users(username,salt,hash) VALUES('other','test','test')")
   portfolios.replace_pluto(c,1,[{'id':'portfolios:root','name':'Root','kind':'portfolio'},{'id':'collections:child','name':'Child','kind':'collection','parent_external_id':'portfolios:root'}])
   self.root=c.execute("SELECT * FROM portfolios WHERE external_id='portfolios:root'").fetchone();self.child=c.execute("SELECT * FROM portfolios WHERE external_id='collections:child'").fetchone()
   c.execute('INSERT INTO oauth_tokens VALUES(?,?,?,?)',(1,oauth.seal(1,{'token':{'access_token':'test'}}),time.time()+100,time.time()))
 def tearDown(self):self.env.stop();app.DB=self.old;self.tmp.cleanup()
 def tools(self):
  mapping={**portfolio_data.READ_TOOLS,'list_orders':'portfolioId','get_collection_activity':'collectionId'}
  return [{'name':name,'annotations':{'readOnlyHint':True},'inputSchema':{'type':'object','properties':{key:{'type':'string'}}}} for name,key in mapping.items()]
 def test_active_buy_is_never_a_completed_position(self):
  rows=[{'name':'Held','quantity':'2','currency':'USD','value':'20'},{'name':'Planned one','quantity':'3','type':'ACTIVE_BUY'},{'name':'Planned two','quantity':'4','status':'ACTIVE_BUY'}]
  self.assertEqual(len(portfolio_data.normalize_positions(rows)),1)
  pending=pending_orders.from_positions(rows,'get_collection');self.assertEqual(len(pending),2)
  self.assertTrue(all(row['pending_buy'] for row in pending));self.assertTrue(all(row['filled_quantity'] is None for row in pending))
 def test_allocation_is_not_inferred_from_cost_or_order_value(self):
  row=pending_orders.normalize({'name':'Planned','status':'ACTIVE_BUY','quantity':'10','amount':'100','costBasis':'90','value':'110','currency':'DKK'},'test')
  self.assertIsNone(row['allocated']['amount']);self.assertEqual(row['order_amount']['amount'],'100');self.assertIsNone(row['filled_quantity'])
 def test_explicit_id_dedup_and_unknown_identity(self):
  original={'name':'Planned','status':'ACTIVE_BUY','orderId':'test-order','allocatedAmount':{'amount':'100','currency':'DKK'}}
  merged=pending_orders.merge([pending_orders.normalize(original,'source-a'),pending_orders.normalize(original,'source-b')])
  self.assertEqual(len(merged),1);self.assertEqual(merged[0]['sources'],['source-a','source-b'])
  unknown={k:v for k,v in original.items() if k!='orderId'}
  self.assertEqual(len(pending_orders.merge([pending_orders.normalize(unknown,'source-a'),pending_orders.normalize(unknown,'source-b')])),2)
 def test_final_status_does_not_remain_active_buy(self):
  self.assertFalse(pending_orders.active_buy({'type':'ACTIVE_BUY','status':'FILLED'}))
  self.assertIsNone(pending_orders.normalize({'status':'CANCELLED','side':'BUY'},'test',True))
 def test_two_pending_buys_and_cash_are_not_double_counted(self):
  tools=self.tools();calls=[]
  pending=[{'name':'Planned '+str(i),'quantity':'1','status':'ACTIVE_BUY','orderId':'test-order-'+str(i),'allocatedAmount':{'amount':'50','currency':'DKK'},'collectionId':'child'} for i in range(2)]
  class Client:
   def __init__(self,token):pass
   def tools(self):return tools
   def request(self,method,params):
    calls.append(params['name'])
    if params['name']=='get_collection':data={'localCurrency':'DKK','value':'1000','holdings':{'positions':[{'name':'Held','quantity':'1','currency':'USD','value':'10'},*pending]},'accounts':[{'currency':'DKK','cash':'500','withdrawalPower':'400','reservedForOrders':'100'}]}
    elif params['name']=='list_orders':data={'orders':pending}
    elif params['name']=='get_collection_activity':data={'activities':pending}
    else:raise AssertionError('Unexpected tool')
    return {'structuredContent':data}
  result=portfolio_data.read(app.connect,1,self.child['id'],Client)
  self.assertEqual(len(result['positions']),1);self.assertEqual(len(result['pending_orders']),2);self.assertTrue(result['orders_complete'])
  self.assertEqual(result['accounts'][0]['balance']['amount'],'500');self.assertEqual(result['accounts'][0]['reserved']['amount'],'100');self.assertEqual(result['value']['value']['amount'],'1000')
  self.assertTrue(set(calls).issubset({'get_collection','list_orders','get_collection_activity'}))
 def test_collection_order_filter_and_unlinked_warning(self):
  tools=self.tools()
  class Client:
   def request(self,method,params):
    rows=[{'name':'Mine','status':'ACTIVE_BUY','collectionId':'child'},{'name':'Different collection','status':'ACTIVE_BUY','collectionId':'different'},{'name':'Unknown affiliation','status':'ACTIVE_BUY'}]
    return {'structuredContent':{'orders':rows}} if params['name']=='list_orders' else {'structuredContent':{'activities':[]}}
  payload={'pending_orders':[]};pending_orders.enrich(Client(),tools,dict(self.child),payload,app.connect,1,lambda response,name:response['structuredContent'])
  self.assertEqual([row['name'] for row in payload['pending_orders']],['Mine']);self.assertFalse(payload['orders_complete'])
 def test_activity_pagination_and_missing_parent_never_guesses(self):
  tools=self.tools();calls=[]
  class Client:
   def request(self,method,params):
    calls.append(params)
    data={'activities':[],'nextToken':'second'} if not params['arguments'].get('nextToken') else {'activities':[{'name':'Pending','status':'ACTIVE_BUY'}]}
    return {'structuredContent':data}
  portfolio=dict(self.child);portfolio['parent_external_id']=None;payload={'pending_orders':[]}
  pending_orders.enrich(Client(),tools,portfolio,payload,app.connect,1,lambda response,name:response['structuredContent'])
  self.assertTrue(all(call['name']=='get_collection_activity' for call in calls));self.assertEqual(calls[1]['arguments']['nextToken'],'second');self.assertEqual(len(payload['pending_orders']),1);self.assertFalse(payload['orders_complete'])
 def test_mutating_tool_is_not_allowed(self):
  self.assertFalse(pending_orders.allowed(self.tools(),'propose_orders','portfolioId'))
