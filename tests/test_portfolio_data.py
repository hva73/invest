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
 def test_auto_refresh_budget_is_shared_and_user_scoped(self):
  import concurrent.futures,threading
  gate=threading.Barrier(2)
  def claim():gate.wait();return portfolio_data.claim_refresh(app.connect,1,'list',True)
  with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:claim(),range(2)))
  self.assertEqual(sorted(results),[False,True]);self.assertTrue(portfolio_data.claim_refresh(app.connect,2,'list',True));self.assertTrue(portfolio_data.claim_refresh(app.connect,1,'data:'+str(self.root),True))
  self.assertTrue(portfolio_data.claim_refresh(app.connect,1,'list',False));self.assertFalse(portfolio_data.claim_refresh(app.connect,1,'list',True))
  with app.connect() as c:c.execute('UPDATE pluto_refresh_checks SET attempted=0 WHERE user_id=1')
  self.assertTrue(portfolio_data.claim_refresh(app.connect,1,'list',True))
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
 def test_strict_scope_evidence_requires_explicit_direct_and_collection_identity(self):
  class Client:
   def __init__(self,token):pass
   def tools(self):return TOOLS
   def request(self,method,params):
    name=params['name']
    if name=='get_positions':return {'structuredContent':{'positions':[],'collections':[{'collectionId':'test-child'}],'totalCount':1}}
    if name=='get_collection':return {'structuredContent':{'collection':{'id':'test-child','localCurrency':'DKK'},'holdings':{'portfolioView':{'collectionId':'test-child','positions':[]}},'accounts':[],'value':{'equity':'0','currency':'DKK'}}}
    return {'isError':True}
  parent=portfolio_data.read(app.connect,1,self.root,Client,strict_positions=True)
  child=portfolio_data.read(app.connect,1,self.child,Client,strict_positions=True)
  self.assertEqual((parent['positions_scope'],parent['positions_collection_ids']),('DIRECT',['test-child']))
  self.assertEqual(child['positions_scope'],'COLLECTION')
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
 def test_strict_positions_proof_survives_unrelated_section_failure_but_not_missing_rows(self):
  class Client:
   total=1
   def __init__(self,token):pass
   def tools(self):return TOOLS
   def request(self,method,params):
    if params['name']=='get_positions':return {'structuredContent':{'positions':[{'assetId':'asset-one','ticker':'ONE','name':'One','quantity':'2','currency':'USD'}],'collections':[],'totalCount':self.total}}
    return {'isError':True}
  result=portfolio_data.read(app.connect,1,self.root,Client,strict_positions=True)
  self.assertFalse(result['complete']);self.assertTrue(result['positions_complete']);self.assertTrue(result['positions_strict_verified'])
  Client.total=2
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.read(app.connect,1,self.root,Client,strict_positions=True)
  Client.total=None
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.read(app.connect,1,self.root,Client,strict_positions=True)
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

 def test_observed_pluto_equity_value_contract(self):
  # Field names observed on Nordicway; amounts are synthetic test values.
  result=portfolio_data.normalize_value({'timestamp':'2026-01-01T12:00:00Z','equity':'1234.50','profitLoss':'99.00','currency':'DKK'})
  self.assertEqual(result['value'],{'amount':'1234.50','currency':'DKK'})
  self.assertEqual(result['source_time'],'2026-01-01T12:00:00+00:00')
  self.assertNotIn('realized',result);self.assertNotIn('profitLoss',result)
 def test_conflicting_equity_and_value_fail_safely(self):
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.normalize_value({'equity':'100','value':'200','currency':'DKK'})

 def test_unknown_cash_fields_report_shape_not_values(self):
  accounts=portfolio_data.normalize_accounts([{'currency':'DKK','reservedForOrders':'0','unknownCash':'123456.789','unknownPower':'99999.111'}])
  self.assertIsNone(accounts[0]['balance']['amount']);self.assertIsNone(accounts[0]['buying_power']['amount'])
  self.assertEqual(accounts[0]['reserved']['amount'],'0');self.assertIn('unknownCash',accounts[0]['diagnostic']);self.assertNotIn('123456',accounts[0]['diagnostic'])

 def test_observed_cash_and_withdrawal_are_separate(self):
  # Field names from the user's live diagnostic; all amounts are synthetic.
  rows=portfolio_data.normalize_accounts([{'currency':'DKK','cash':'200','withdrawalPower':'125','reservedForOrders':'75'}])
  self.assertEqual(rows[0]['balance']['amount'],'200');self.assertEqual(rows[0]['withdrawal_power']['amount'],'125');self.assertEqual(rows[0]['reserved']['amount'],'75')
  self.assertIsNone(rows[0]['buying_power']['amount']);self.assertNotIn('diagnostic',rows[0])
 def test_nested_collection_preserves_metadata_and_currency(self):
  class Client:
   def __init__(self,token):pass
   def tools(self):return TOOLS
   def request(self,method,params):
    return {'structuredContent':{'collection':{'localCurrency':'EUR','accountCurrency':'DKK'},'holdings':{'positions':[{'name':'Test stock','currency':'USD','quantity':'1','price':'10','value':'10'}],'totalCount':1},'accounts':[{'currency':'EUR','cash':'20','withdrawalPower':'15','reservedForOrders':'5'}],'value':{'equity':'30','currency':'EUR','timestamp':'2026-01-01T00:00:00Z'}}}
  result=portfolio_data.read(app.connect,1,self.child,Client)
  self.assertTrue(result['complete']);self.assertEqual(result['value']['value'],{'amount':'30','currency':'EUR'});self.assertEqual(len(result['positions']),1);self.assertEqual(result['accounts'][0]['balance']['amount'],'20')
 def test_collection_sections_survive_unknown_holdings(self):
  class Client:
   def __init__(self,token):pass
   def tools(self):return TOOLS
   def request(self,method,params):return {'structuredContent':{'collection':{'localCurrency':'EUR'},'holdings':{'unknown':'private-value'},'accounts':[{'currency':'EUR','cash':'20','withdrawalPower':'15','reservedForOrders':'5'}],'value':{'equity':'30','currency':'EUR'}}}
  result=portfolio_data.read(app.connect,1,self.child,Client)
  self.assertFalse(result['complete']);self.assertEqual(result['value']['value']['amount'],'30');self.assertEqual(result['accounts'][0]['balance']['amount'],'20');self.assertEqual(result['positions'],[])
  self.assertNotIn('private-value',' '.join(result['errors']))
 def test_nested_collection_rejects_partial_and_ambiguous_lists(self):
  for data in [{'holdings':{'items':[],'nextToken':'more'}},{'holdings':{'items':[],'totalCount':1}},{'holdings':{'items':[],'positions':[]}}]:
   with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.complete_list(data,['holdings','items','positions'])
 def test_collection_map_keeps_source_records_without_exposing_keys(self):
  data={'holdings':{'private-key-a':{'name':'Test one','quantity':'2','currency':'USD','value':'10'},'private-key-b':{'name':'Test two','quantity':'3','currency':'EUR','value':'20'}}}
  rows=portfolio_data.complete_list(data,['holdings','positions','items','assets'])
  self.assertEqual(len(rows),2);self.assertEqual(rows[0]['quantity'],'2');self.assertNotIn('private-key-a',str(rows))
 def test_single_custom_wrapper_requires_quantity(self):
  rows=portfolio_data.complete_list({'holdings':{'customWrapper':[{'name':'Test','quantity':'2'}]}},['holdings','positions','items'])
  self.assertEqual(rows[0]['name'],'Test')
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.complete_list({'holdings':{'weights':[{'name':'Test','weight':'0.5'}]}},['holdings','positions','items'])
 def test_nested_diagnostic_shows_structure_without_private_keys(self):
  text=portfolio_data.nested_shape({'private-key':{'assets':[{'name':'Private instrument','quantity':'123'}]}})
  self.assertIn('assets:list',text);self.assertNotIn('private-key',text);self.assertNotIn('Private instrument',text);self.assertNotIn('123',text)
 def test_observed_extra_collection_object_wrapper(self):
  # Structure from the diagnostic; values and wrapper name are synthetic.
  data={'collection':{'localCurrency':'EUR'},'holdings':{'wrapper':{'accountCurrency':'DKK','localCurrency':'EUR','positions':[{'name':'Test stock','quantity':'1','currency':'USD','value':'25'}],'metadataA':'test','metadataB':'test'}},'accounts':[],'value':{'equity':'25','currency':'EUR'}}
  rows=portfolio_data.complete_list(data,['positions','holdings','rows','items','data','assets'])
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['name'],'Test stock')
 def test_extra_wrapper_still_rejects_partial_positions(self):
  data={'holdings':{'wrapper':{'positions':[],'nextToken':'test-more'}}}
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.complete_list(data,['positions','holdings','items'])
