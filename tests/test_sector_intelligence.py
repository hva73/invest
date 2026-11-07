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
    CREATE TABLE hw_sessions(id,request,status);''')
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
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'OTHER','Sector':'Technology','CurrencyCode':'USD'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertIsNone(row['sector']);self.assertEqual(row['status'],'IDENTITY_OR_SECTOR_UNKNOWN')
 def test_classification_accepts_exact_verified_symbol_and_isin(self):
  now=time.time()
  with self.connect() as c:c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','MSFT.US','US5949181045',now))
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'MSFT','ISIN':'US5949181045','CurrencyCode':'USD','Sector':'Technology','Industry':'Software'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertEqual((row['sector'],row['industry']),('Teknologi','Software'))
 def test_series_sorts_and_discards_invalid(self):
  result=sector._series([{'date':'2026-10-02','close':4},{'date':'invalid','close':7},{'date':'2026-10-01','close':2},{'date':'2026-10-03','close':-1}])
  self.assertEqual([x['date'] for x in result],['2026-10-01','2026-10-02'])

if __name__=='__main__':unittest.main()
