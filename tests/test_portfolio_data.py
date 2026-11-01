"""Synthetic financial fixtures only; never loaded into application databases."""
import tempfile,time,unittest
from unittest.mock import patch
import app,oauth,portfolios,portfolio_data,jobs

TOOLS=[{'name':name,'inputSchema':{'type':'object','properties':{key:{'type':'string'}}},'annotations':{'readOnlyHint':True}} for name,key in portfolio_data.READ_TOOLS.items()]
class Data(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.previous=app.DB;app.DB=self.tmp.name+'/data.db';app.init();app.create_user('test-password-long')
  self.env=patch.dict('os.environ',{'ESCAPE_TOKEN_KEY_FILE':self.tmp.name+'/token.key'});self.env.start();oauth.setup_key()
  with app.connect() as c:
   c.execute("INSERT INTO users(username,salt,hash) VALUES('other','test','test')")
   portfolios.replace_pluto(c,1,[{'id':'portfolios:test','name':'Root','kind':'portfolio'},{'id':'collections:test-child','name':'Child','kind':'collection','parent_external_id':'portfolios:test'}])
   self.root=c.execute("SELECT id FROM portfolios WHERE external_id='portfolios:test'").fetchone()[0];self.child=c.execute("SELECT id FROM portfolios WHERE external_id='collections:test-child'").fetchone()[0]
   c.execute('INSERT INTO oauth_tokens VALUES(?,?,?,?)',(1,oauth.seal(1,{'token':{'access_token':'test-token'}}),time.time()+1000,time.time()))
 def tearDown(self):self.env.stop();app.DB=self.previous;self.tmp.cleanup()
 def test_pagination_and_cash_fields(self):
  calls=[]
  class Client:
   def __init__(self,token):pass
   def tools(self):return TOOLS
   def request(self,method,params):
    calls.append(params);name=params['name']
    if name=='get_portfolio_value':data={'value':'1000','currency':'DKK','recordedAt':'2026-01-01T12:00:00Z'}
    elif name=='get_accounts':data={'accounts':[{'currency':'DKK','balance':'500','reservedForOrders':'100','buyingPower':'400'}]}
    elif params['arguments'].get('nextToken')=='page-two':data={'positions':[{'name':'Second','quantity':1,'currency':'USD','price':None,'value':None}],'totalCount':2}
    else:data={'positions':[{'name':'First','quantity':'2','currency':'USD','latestPrice':'10','value':'20','valueInPortfolioCurrency':'140','unrealisedPnL':'5'}],'totalCount':2,'nextToken':'page-two'}
    return {'structuredContent':data}
  payload=portfolio_data.read(app.connect,1,self.root,Client)
  self.assertTrue(payload['complete']);self.assertEqual(len(payload['positions']),2);self.assertEqual(payload['accounts'][0]['reserved']['amount'],'100');self.assertIsNone(payload['positions'][1]['price']['amount']);self.assertIsNone(payload['positions'][0]['price_time'])
  self.assertEqual(calls[-1]['arguments']['nextToken'],'page-two')
 def test_collection_currency_never_account_currency(self):
  class Client:
   def __init__(self,token):pass
   def tools(self):return TOOLS
   def request(self,method,params):return {'structuredContent':{'localCurrency':'EUR','accountCurrency':'DKK','value':'120','holdings':[{'name':'Stock','currency':'USD','quantity':1,'value':'100'}],'cashAccounts':[{'currency':'EUR','balance':'20'}]}}
  payload=portfolio_data.read(app.connect,1,self.child,Client)
  self.assertEqual(payload['value']['value']['currency'],'EUR');self.assertEqual(payload['positions'][0]['currency'],'USD');self.assertEqual(payload['accounts'][0]['currency'],'EUR')
 def test_user_isolation_before_network(self):
  def forbidden(*args):raise AssertionError('must not open a connection')
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.read(app.connect,2,self.root,forbidden)
  with app.connect() as c:self.assertEqual(portfolio_data.snapshots(c,2),{})
 def test_summary_excludes_collections_and_keeps_currencies(self):
  with app.connect() as c:
   for pid,value,code in [(self.root,'1000','DKK'),(self.child,'300','DKK')]:
    portfolio_data.save(c,1,pid,{'observed':'2026-01-01T12:00:00+00:00','value':{'value':{'amount':value,'currency':code}},'errors':[]})
   summary=portfolio_data.summaries(portfolios.list_owned(c,1),portfolio_data.snapshots(c,1))
   self.assertEqual(summary['by_currency'],{'DKK':'1000'})
   portfolio_data.mark_failed(c,1,self.root,'Test failure')
   summary=portfolio_data.summaries(portfolios.list_owned(c,1),portfolio_data.snapshots(c,1));self.assertEqual(summary['by_currency'],{});self.assertEqual(summary['missing_portfolios'],1)
   self.assertEqual(portfolio_data.snapshots(c,1)[str(self.root)]['data']['value']['value']['amount'],'1000')
 def test_bad_numbers_and_missing_fields(self):
  for value in ['NaN','Infinity',True,'1,25']:
   with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.number(value)
  self.assertIsNone(portfolio_data.number(None));self.assertEqual(portfolio_data.number(0),'0')
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.normalize_accounts([{'unknownBalance':10}])
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.normalize_value({'unknownValue':10})
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.normalize_accounts([{'currency':'DKK','balance':{'amount':'10','currency':'USD'}}])
 def test_partial_errors_are_explicit(self):
  class Client:
   def __init__(self,token):pass
   def tools(self):return TOOLS
   def request(self,method,params):
    if params['name']=='get_portfolio_value':return {'structuredContent':{'value':'100','currency':'EUR'}}
    return {'isError':True}
  payload=portfolio_data.read(app.connect,1,self.root,Client);self.assertFalse(payload['complete']);self.assertEqual(len(payload['errors']),2);self.assertEqual(payload['value']['value']['amount'],'100')
 def test_all_sections_fail_without_overwriting(self):
  class Client:
   def __init__(self,token):pass
   def tools(self):return TOOLS
   def request(self,method,params):return {'isError':True}
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.read(app.connect,1,self.root,Client)
 def test_background_schedule_is_per_user_and_portfolio(self):
  jobs.schedule(app.connect)
  with app.connect() as c:
   rows=c.execute("SELECT user_id,portfolio_id FROM jobs WHERE kind='pluto_data'").fetchall()
   self.assertEqual({row['portfolio_id'] for row in rows},{self.root,self.child});self.assertTrue(all(row['user_id']==1 for row in rows))
 def test_unsupported_write_tool_never_allowed(self):
  self.assertFalse(portfolio_data.supported([{'name':'propose_orders','annotations':{'readOnlyHint':True}}],'propose_orders'))

 def test_summary_does_not_convert_or_add_currencies(self):
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:test','name':'Root','kind':'portfolio'},{'id':'portfolios:usd','name':'USD root','kind':'portfolio'}])
   rows=portfolios.list_owned(c,1)
   for row in rows:
    if row['kind']=='portfolio' and row['active']:
     code='USD' if row['external_id']=='portfolios:usd' else 'DKK'
     portfolio_data.save(c,1,row['id'],{'observed':'2026-01-01T12:00:00+00:00','value':{'value':{'amount':'100','currency':code}},'errors':[]})
   self.assertEqual(portfolio_data.summaries(rows,portfolio_data.snapshots(c,1))['by_currency'],{'DKK':'100','USD':'100'})
