"""Synthetic quotes only; no real market values or external service calls."""
import tempfile,time,unittest
from unittest.mock import patch
from decimal import Decimal
import app,oauth,portfolios,portfolio_data,asset_quotes

class Quotes(unittest.TestCase):
 def row(self):return portfolio_data.normalize_positions([{'assetId':'test-id','quantity':'0.1','averageEntryPrice':'400','costBasis':'40','asset':{'id':'test-id','name':'Test asset','ticker':'TEST','currency':'USD'}}])[0]
 def test_quote_identity_currency_and_time(self):
  result=asset_quotes.parse({'asset':{'id':'test-id','currency':'USD'},'price':{'amount':'500','currency':'USD','timestamp':'2026-01-01T00:00:00Z'}},'test-id')
  self.assertEqual(result['price'],{'amount':'500','currency':'USD'});self.assertEqual(result['price_time'],'2026-01-01T00:00:00+00:00')
  with self.assertRaises(portfolio_data.PortfolioFormatError):asset_quotes.parse({'id':'wrong','currency':'USD','price':'500'},'test-id')
  with self.assertRaises(portfolio_data.PortfolioFormatError):asset_quotes.parse({'id':'test-id','currency':'EUR','price':{'amount':'500','currency':'USD'}},'test-id')
 def test_nested_current_price_observed_contract(self):
  data={'asset':{'id':'test-id','currency':'USD'},'price':{'assetId':'test-id','currentPrice':502.5,'dailyChange':-1.2,'dailyChangePercent':-0.24}}
  result=asset_quotes.parse(data,'test-id')
  self.assertEqual(result['price'],{'amount':'502.5','currency':'USD'})
  self.assertEqual(result['daily']['percent'],'-0.24');self.assertEqual(result['daily']['basis'],'pluto_reported_daily_change')
  self.assertIsNone(result['price_time'])
  contradicting={'asset':{'id':'test-id','currency':'USD'},'price':{'currentPrice':'500','dailyChange':'2','dailyChangePercent':'-1'}}
  self.assertIsNone(asset_quotes.parse(contradicting,'test-id')['daily'])
  data['price']['assetId']='foreign'
  with self.assertRaises(portfolio_data.PortfolioFormatError):asset_quotes.parse(data,'test-id')
 def test_calculated_value_is_labeled_and_same_currency(self):
  row=self.row();row['price']={'amount':'500','currency':'USD'};asset_quotes.calculate(row)
  self.assertEqual(Decimal(row['value']['amount']),Decimal('50'));self.assertEqual(Decimal(row['unrealized']['amount']),Decimal('10'))
  self.assertEqual(row['value_basis'],'calculated_quantity_price');self.assertEqual(row['unrealized_basis'],'calculated_value_cost')
  row=self.row();row['price']={'amount':'500','currency':'EUR'};asset_quotes.calculate(row);self.assertIsNone(row['value']['amount'])
 def test_source_values_are_never_overwritten(self):
  row=self.row();row['price']={'amount':'500','currency':'USD'};row['value']={'amount':'49','currency':'USD'};row['unrealized']={'amount':'9','currency':'USD'}
  asset_quotes.calculate(row);self.assertEqual(row['value']['amount'],'49');self.assertEqual(row['unrealized']['amount'],'9');self.assertNotIn('value_basis',row)
 def test_lookup_uses_exact_id_and_reuses_quote(self):
  tools=[{'name':'get_asset','annotations':{'readOnlyHint':True},'inputSchema':{'type':'object','required':['assetId'],'properties':{'assetId':{'type':'string'}}}}];calls=[]
  class Client:
   def request(self,method,params):calls.append(params);return {'structuredContent':{'id':'test-id','currency':'USD','price':'500'}}
  payload={'positions':[self.row(),self.row()],'errors':[],'complete':True}
  asset_quotes.enrich(Client(),tools,payload,lambda response,name:response['structuredContent'])
  self.assertEqual(len(calls),1);self.assertEqual(calls[0],{'name':'get_asset','arguments':{'assetId':'test-id'}})
  self.assertIsNone(payload['positions'][0]['price_time']);self.assertTrue(payload['complete'])
  self.assertEqual(payload['positions'][0]['price_type'],'get_asset_latest')
 def test_missing_id_and_unknown_quote_stay_unknown(self):
  row=self.row();row['asset_id']=None;payload={'positions':[row],'errors':[],'complete':True}
  class Client:
   def request(self,*args):raise AssertionError('must not search by ticker')
  asset_quotes.enrich(Client(),[],payload,lambda *args:None);self.assertFalse(payload['complete']);self.assertIsNone(row['value']['amount'])
  with self.assertRaises(portfolio_data.PortfolioFormatError):asset_quotes.parse({'id':'test-id','currency':'USD','averageEntryPrice':'500'},'test-id')
 def test_conflicting_holding_asset_id_rejected(self):
  with self.assertRaises(portfolio_data.PortfolioFormatError):portfolio_data.normalize_positions([{'assetId':'one','quantity':'1','asset':{'id':'two','name':'Test','currency':'USD'}}])
 def test_collection_enrichment_keeps_broker_total_separate(self):
  previous=app.DB
  with tempfile.TemporaryDirectory() as directory:
   try:
    app.DB=directory+'/db';app.init();app.create_user('test-password-long')
    with patch.dict('os.environ',{'ESCAPE_TOKEN_KEY_FILE':directory+'/key'}):
     oauth.setup_key()
     with app.connect() as c:
      portfolios.replace_pluto(c,1,[{'id':'collections:child','kind':'collection','name':'Test collection'}]);pid=c.execute('SELECT id FROM portfolios').fetchone()[0]
      c.execute('INSERT INTO oauth_tokens VALUES(?,?,?,?)',(1,oauth.seal(1,{'token':{'access_token':'test'}}),time.time()+100,time.time()))
     class Client:
      def __init__(self,token):pass
      def tools(self):return [{'name':name,'annotations':{'readOnlyHint':True},'inputSchema':{'type':'object','properties':{key:{'type':'string'}}}} for name,key in [('get_collection','collectionId'),('get_asset','assetId')]]
      def request(self,method,params):
       if params['name']=='get_collection':data={'collection':{'localCurrency':'DKK'},'holdings':{'portfolioView':{'positions':[{'assetId':'test-id','quantity':'0.1','costBasis':'40','asset':{'id':'test-id','name':'Test','currency':'USD'}}]}},'accounts':[],'value':{'equity':'1000','profitLoss':'2','currency':'DKK'}}
       elif params['name']=='get_asset':data={'id':'test-id','currency':'USD','price':'500'}
       else:raise AssertionError('unexpected method')
       return {'structuredContent':data}
     result=portfolio_data.read(app.connect,1,pid,Client)
     self.assertEqual(result['value']['value'],{'amount':'1000','currency':'DKK'});self.assertEqual(result['value']['reported_result'],{'amount':'2','currency':'DKK'})
     self.assertEqual(Decimal(result['positions'][0]['value']['amount']),Decimal('50'));self.assertEqual(result['positions'][0]['value']['currency'],'USD')
   finally:app.DB=previous
