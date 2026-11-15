import json,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
from realized_statistics import display_currency,documented_order_origins,project
from test_statistics_missing_cost import order

class DkkDisplay(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'test.db')
  with self.connect() as c:
   c.execute('CREATE TABLE fx_snapshots(id INTEGER,source_date TEXT,payload TEXT)')
   c.execute('CREATE TABLE sector_fx(currency TEXT,rate REAL,event_time TEXT,status TEXT)')
 def tearDown(self):self.tmp.cleanup()
 def connect(self):return sqlite3.connect(self.path)
 def test_cached_reference_converts_without_changing_original_execution(self):
  with self.connect() as c:c.execute('INSERT INTO fx_snapshots VALUES(1,?,?)',('2026-11-13',json.dumps({'rates':{'DKK':'7.46','USD':'1.10'}})))
  data={'portfolios':[{'items':[{'currency':'USD','gross':'2.2','cost_basis':'10','sale_proceeds':'12.2'},{'currency':'EUR','gross':'1'},{'currency':'DKK','gross':'3'}]}]}
  result=display_currency(self.connect,data,datetime(2026,11,15,tzinfo=timezone.utc));items=result['portfolios'][0]['items']
  self.assertEqual(items[0]['gross'],'2.2');self.assertAlmostEqual(float(items[0]['display_gross_dkk']),14.92)
  self.assertEqual(items[1]['display_gross_dkk'],'7.46');self.assertEqual(items[2]['display_gross_dkk'],'3')
  self.assertEqual(items[0]['display_fx']['source'],'ECB');self.assertIsNone(items[1]['display_proceeds_dkk'])
 def test_stale_future_and_missing_fx_do_not_invent_zero(self):
  for date in ('2026-11-01','2026-11-16'):
   with self.connect() as c:c.execute('DELETE FROM fx_snapshots');c.execute('INSERT INTO fx_snapshots VALUES(1,?,?)',(date,json.dumps({'rates':{'DKK':7.46,'USD':1.1}})))
   item={'currency':'USD','gross':'10'}
   display_currency(self.connect,{'portfolios':[{'items':[item]}]},datetime(2026,11,15,tzinfo=timezone.utc))
   self.assertIsNone(item['display_gross_dkk']);self.assertIsNone(item['display_fx'])
 def test_fresh_fx_quote_fallback(self):
  with self.connect() as c:c.execute("INSERT INTO sector_fx VALUES('USD',6.8,'2026-11-14T12:00:00Z','OK')")
  item={'currency':'USD','gross':'2'};display_currency(self.connect,{'portfolios':[{'items':[item]}]},datetime(2026,11,15,tzinfo=timezone.utc))
  self.assertEqual(item['display_gross_dkk'],'13.6');self.assertEqual(item['display_fx']['source'],'EODHD')

class OrderEvidence(unittest.TestCase):
 def test_exact_manual_order_reference_without_provider_asset_id(self):
  with tempfile.TemporaryDirectory() as directory:
   path=str(Path(directory)/'db');connect=lambda:sqlite3.connect(path)
   with connect() as c:
    c.execute('CREATE TABLE broker_proposals(user_id INTEGER,portfolio_id INTEGER,kind TEXT,status TEXT,report_id TEXT,payload TEXT,response TEXT,intent_id TEXT,asset TEXT)')
    args=(1,1,'direct','sent','@manual-sell',json.dumps({'orders':[{'side':'SELL','assetId':'asset-1'}]}),json.dumps({'orderId':'ASELL','orderIntentId':'intent','status':'ACCEPTED'}),'intent',json.dumps({'assetId':'asset-1','ticker':'A','name':'A','currency':'USD'}))
    c.execute('INSERT INTO broker_proposals VALUES(?,?,?,?,?,?,?,?,?)',args)
   evidence=documented_order_origins(connect,1,1)
   result=project([order('A','BUY','10'),order('A','SELL','12')],order_origins=evidence)['items'][0]
   self.assertEqual(result['sell_origin'],'own');self.assertEqual(result['buy_origin'],'unknown')
   self.assertIn('ordre-ID',result['sell_origin_evidence'])
   self.assertEqual(documented_order_origins(connect,2,1),{})
   bad=order('A','SELL','12');bad['asset']['name']='Different company'
   self.assertEqual(project([bad],order_origins=evidence)['unresolved_sales'][0]['sell_origin'],'unknown')
   with connect() as c:c.execute('INSERT INTO broker_proposals VALUES(?,?,?,?,?,?,?,?,?)',args)
   self.assertEqual(documented_order_origins(connect,1,1),{})
