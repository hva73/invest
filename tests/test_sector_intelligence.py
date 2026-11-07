import json, os, sqlite3, tempfile, time, unittest
from unittest.mock import patch
import sector_intelligence as sector

class SectorIntelligenceTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=os.path.join(self.tmp.name,'test.db')
  with self.connect() as c:
   sector.init(c)
   c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,active INTEGER); INSERT INTO users VALUES(1,1);
    CREATE TABLE hw_verified_feed_links(user_id,asset_id,ticker,currency,exchange,symbol,isin,verified_epoch);
    CREATE TABLE portfolios(id,user_id,active,source);
    CREATE TABLE portfolio_snapshots(portfolio_id,user_id,payload);
    CREATE TABLE hw_sessions(id,request,status); CREATE TABLE fx_snapshots(id INTEGER PRIMARY KEY,source_date,payload);''')
 def tearDown(self):self.tmp.cleanup()
 def connect(self):
  c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
 def test_history_stays_owner_and_depot_scoped_and_skips_incomplete(self):
  data={'observed':'2026-11-07T10:00:00+00:00','positions_complete':True,'positions':[{'asset_id':'btc','kind':'holding'},{'asset_id':'collection','kind':'collection'}]}
  with self.connect() as c:
   sector.capture(c,1,21,data);sector.capture(c,1,61,data);sector.capture(c,2,21,data)
   sector.capture(c,1,21,{**data,'positions_complete':False})
   rows=c.execute('SELECT * FROM sector_history ORDER BY user_id,portfolio_id').fetchall()
  self.assertEqual([(r['user_id'],r['portfolio_id']) for r in rows],[(1,21),(1,61),(2,21)])
  self.assertEqual(json.loads(rows[0]['payload']),[{'asset_id':'btc','kind':'holding'}])
 def test_classification_rejects_conflicting_identity(self):
  now=time.time()
  with self.connect() as c:c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','MSFT.US','US5949181045',now))
  with self.connect() as c:c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','US5949181045','CS','Microsoft','OK',now,now+3600))
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'OTHER','Sector':'Technology','CurrencyCode':'USD','Exchange':'NASDAQ','Name':'Microsoft','Type':'Common Stock'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertIsNone(row['sector']);self.assertEqual(row['status'],'IDENTITY_OR_SECTOR_UNKNOWN')
 def test_classification_accepts_exact_verified_symbol_and_isin(self):
  now=time.time()
  with self.connect() as c:c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','MSFT.US','US5949181045',now))
  with self.connect() as c:c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','US5949181045','CS','Microsoft','OK',now,now+3600))
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'MSFT','ISIN':'US5949181045','CurrencyCode':'USD','Exchange':'NASDAQ','Name':'Microsoft','Type':'Common Stock','Sector':'Technology','Industry':'Software'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertEqual((row['sector'],row['industry']),('Teknologi','Software'))
 def test_fx_fallback_fetches_timestamped_currency_for_holding(self):
  with self.connect() as c:
   c.execute("INSERT INTO portfolios VALUES(1,1,1,'pluto')")
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?)',(1,1,json.dumps({'positions':[{'asset_id':'one','currency':'USD'}]})))
  class Client:
   def snapshot(self,symbol):
    self.symbol=symbol
    return {'status':'OK','price':'6.75','event_time':'2026-11-07T10:00:00+00:00'}
  client=Client()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=client):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_fx').fetchone()
  self.assertEqual(client.symbol,'USDDKK.FOREX')
  self.assertEqual((row['currency'],row['rate'],row['event_time']),('USD',6.75,'2026-11-07T10:00:00+00:00'))
 def test_read_reuses_broker_reported_result_and_keeps_user_history_private(self):
  with self.connect() as c:
   sector.capture(c,1,1,{'observed':'2026-11-07T10:00:00+00:00','positions_complete':True,'positions':[{'asset_id':'mine'}]})
   sector.capture(c,2,2,{'observed':'2026-11-07T10:00:00+00:00','positions_complete':True,'positions':[{'asset_id':'other'}]})
  dashboard={'accounts':[{'id':1}],'positions':[], 'portfolio_value_history':{'reported_result':{'amount':'-166.41','currency':'DKK'}}}
  snapshots={'1':{'data':{'value':{'reported_result':{'amount':'-166.41','currency':'DKK'}}}}}
  with patch('portfolios.list_owned',return_value=[{'id':1,'external_id':'portfolios:main'}]),patch('portfolio_data.snapshots',return_value=snapshots),patch('dashboard_projection.build',return_value=dashboard):result=sector.read(self.connect,1)
  self.assertEqual(result['dashboard']['accounts'][0]['reported_result']['amount'],'-166.41')
  self.assertEqual(result['dashboard']['accounts'][0]['external_id'],'portfolios:main')
  self.assertTrue(all(row['portfolio_id']==1 for row in result['history']))
 def test_pluto_fund_and_crypto_are_separate_asset_classes(self):
  for aid,kind,expected in [('fund','ETF','Fonde og ETF (aktivklasse)'),('coin','CRYPTO','Krypto (aktivklasse)')]:
   with self.subTest(kind=kind),patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value={'id':aid,'ticker':'TEST','currency':'USD','type':kind,'sector':'Technology'}):
    sector._fetch_pluto(self.connect,(1,aid,'TEST'),time.time())
   with self.connect() as c:row=c.execute('SELECT * FROM sector_assets WHERE asset_id=?',(aid,)).fetchone()
   self.assertEqual(row['sector'],expected)
   self.assertNotEqual(row['sector'],'Teknologi')
 def test_unmatched_isin_and_listing_are_never_accepted(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','ABC','USD','NYSE','ABC.US','US5949181045',now))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'asset','ABC','USD','NYSE','US0000000001','CS','Microsoft','OK',now,now+3600))
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client') as client:sector.refresh_tick(self.connect)
  client.assert_not_called()
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertIsNone(row['sector']);self.assertEqual(row['status'],'PLUTO_IDENTITY_INCOMPLETE')
 def test_fund_exposure_uses_documented_equity_percentage(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'fund','ABC','USD','NASDAQ','ABC.US','US5949181045',now))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'fund','ABC','USD','NASDAQ','US5949181045','ETF','Microsoft','OK',now,now+3600))
  class Client:
   def _http(self,base,path,params):
    if params.get('filter')=='General':return {'status':'OK','payload':{'Code':'ABC','ISIN':'US5949181045','CurrencyCode':'USD','Exchange':'NASDAQ','Name':'Microsoft','Type':'ETF'}}
    return {'status':'OK','payload':{'Sector_Weights':{'Technology':{'Equity_%':'60'},'Healthcare':{'Equity_%':'40'}},'Asset_Allocation':{'Stock US':{'Net_Assets_%':'70'},'Stock non-US':{'Net_Assets_%':'20'}}}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):
   sector.refresh_tick(self.connect);sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_fund_exposure').fetchone()
  self.assertEqual(row['status'],'OK');payload=json.loads(row['payload'])
  self.assertEqual(payload['equity_percent'],90);self.assertEqual(payload['weights'][0]['sector'],'Teknologi')
 def test_benchmark_requires_matching_region_sector_and_etf_type(self):
  fund={'Code':'XLK','Name':'Technology Select Sector SPDR Fund','Exchange':'NYSE ARCA','CurrencyCode':'USD','Type':'ETF'}
  self.assertTrue(sector._benchmark_identity('USA','Teknologi','XLK.US',fund))
  self.assertFalse(sector._benchmark_identity('Globalt','Teknologi','XLK.US',fund))
  self.assertFalse(sector._benchmark_identity('USA','Sundhed','XLK.US',fund))
  self.assertFalse(sector._benchmark_identity('USA','Teknologi','XLK.US',{**fund,'Type':'Common Stock'}))
 def test_adr_is_not_accepted_as_local_common_share(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'adr','ABC','USD','NYSE','ABC.US','US5949181045',now))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'adr','ABC','USD','NYSE','US5949181045','ADR','Microsoft','OK',now,now+3600))
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'ABC','ISIN':'US5949181045','CurrencyCode':'USD','Exchange':'NYSE','Name':'Microsoft','Type':'Common Stock','Sector':'Technology'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertIsNone(row['sector']);self.assertEqual(row['status'],'IDENTITY_OR_SECTOR_UNKNOWN')
 def test_series_sorts_and_discards_invalid(self):
  result=sector._series([{'date':'2026-10-02','close':4},{'date':'invalid','close':7},{'date':'2026-10-01','close':2},{'date':'2026-10-03','close':-1}])
  self.assertEqual([x['date'] for x in result],['2026-10-01','2026-10-02'])

if __name__=='__main__':unittest.main()
