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
    CREATE TABLE hw_sessions(id,request,status); CREATE TABLE hw_cxe_feed_evidence(user_id,asset_id,symbol,payload,verified_epoch,next_attempt,status); CREATE TABLE fx_snapshots(id INTEGER PRIMARY KEY,source_date,payload);''')
 def tearDown(self):self.tmp.cleanup()
 def connect(self):
  c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
 def test_europe_configured_funds_are_visible_while_waiting(self):
  with patch('portfolios.list_owned',return_value=[]),patch('portfolio_data.snapshots',return_value={}),patch('dashboard_projection.build',return_value={'accounts':[],'positions':[]}):
   result=sector.read(self.connect,1)
  rows=[x for x in result['markets'] if x['region']=='Europa']
  self.assertEqual(len(rows),len(sector.PROXIES['Europa']))
  self.assertTrue(all(x['status']=='PENDING' and x['series']==[] for x in rows))
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
 def test_sector_falls_back_to_eodhd_screener_when_fundamentals_denied(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','MSFT.US','US5949181045',now))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ',None,'CS','Microsoft','OK',now,now+3600))
  class Client:
   def _http(self,base,path,params):
    if path.startswith('/fundamentals/'):return {'status':'ENTITLEMENT_UNVERIFIED'}
    assert path=='/screener'
    assert json.loads(params['filters'])==[['code','=','MSFT'],['exchange','=','us']]
    return {'status':'OK','payload':{'count':1,'data':[{'code':'MSFT','exchange':'NASDAQ','sector':'Technology','industry':'Software'}]}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):
   sector.refresh_tick(self.connect);sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertEqual((row['sector'],row['industry'],row['source']),('Teknologi','Software','EODHD stock screener'))
 def test_screener_does_not_accept_ambiguous_results(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','MSFT.US','US5949181045',now))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ',None,'CS','Microsoft','OK',now,now+3600))
   c.execute("INSERT INTO sector_assets(user_id,asset_id,symbol,status,updated,next_attempt,identity_version) VALUES(1,'asset','MSFT.US','TRY_EODHD_SCREENER',0,0,1)")
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'count':2,'data':[{'code':'MSFT','exchange':'NASDAQ','sector':'Technology'},{'code':'MSFT','exchange':'NASDAQ','sector':'Finance'}]}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertIsNone(row['sector'])
 def test_reuses_existing_verified_asset_link_without_repeating_match(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','MSFT.US','US5949181045',now-30*86400))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ',None,'CS','Microsoft','OK',now,now+3600))
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'MSFT','Sector':'Technology','Industry':'Software'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertEqual((row['sector'],row['status']),('Teknologi','OK'))
 def test_reused_link_rejects_explicit_conflicting_eodhd_isin(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','MSFT.US','US5949181045',now))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ',None,'CS','Microsoft','OK',now,now+3600))
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'MSFT','ISIN':'US0000000001','Sector':'Technology'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertIsNone(row['sector']);self.assertEqual(row['status'],'IDENTITY_OR_SECTOR_UNKNOWN')
 def test_existing_hotwatch_listing_proof_works_without_a_pluto_isin(self):
  now=time.time();dt=__import__('datetime').datetime.fromtimestamp(now,__import__('datetime').timezone.utc).isoformat()
  instrument={'asset_id':'asset','ticker':'MSFT','currency':'USD','exchange':'NASDAQ','name':'Microsoft','type':'CS'}
  proof={'basis':'pluto_asset_us_listing','pluto':instrument,'symbol':'MSFT.US','isin':'US5949181045','currency':'USD','catalog_received_at':dt,'catalog_source':'https://eodhd.com/api/exchange-symbol-list/US','catalog_type':'Common Stock','catalog_exchange':'NASDAQ','catalog_ticker':'MSFT','pluto_type':'CS'}
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ','MSFT.US','US5949181045',now))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'asset','MSFT','USD','NASDAQ',None,'CS','Microsoft','OK',now,now+3600))
   c.execute('INSERT INTO hw_cxe_feed_evidence VALUES(?,?,?,?,?,?,?)',(1,'asset','MSFT.US',json.dumps(proof),now,now+3600,'MATCHED'))
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'MSFT','ISIN':'US5949181045','CurrencyCode':'USD','Exchange':'NASDAQ','Name':'Microsoft','Type':'Common Stock','Sector':'Technology'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertEqual((row['sector'],row['status']),('Teknologi','OK'))
 def test_conflicting_cached_metadata_cannot_starve_the_market_queue(self):
  now=time.time()
  with self.connect() as c:
   c.execute("INSERT INTO portfolios VALUES(1,1,1,'pluto')")
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?)',(1,1,json.dumps({'positions':[{'asset_id':'a','ticker':'AAA','currency':'USD'}]})))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'a','AAA','EUR','NASDAQ',None,'CS','Example','OK',now,now+3600))
  self.assertEqual(sector._pluto_candidate(self.connect,now),(1,'a','AAA'))
  self.assertIsNone(sector._pluto_candidate(self.connect,now+5))
  self.assertEqual(sector._pluto_candidate(self.connect,now+301),(1,'a','AAA'))
 def test_market_continues_after_one_unresolved_holding(self):
  now=time.time();date=__import__('datetime').datetime.fromtimestamp(now,__import__('datetime').timezone.utc).date().isoformat()
  with self.connect() as c:
   c.execute("INSERT INTO portfolios VALUES(1,1,1,'pluto')")
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?)',(1,1,json.dumps({'positions':[{'asset_id':'a','ticker':'AAA','currency':'USD'}]})))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'a','AAA','EUR','NASDAQ',None,'CS','Example','OK',now,now+3600))
   c.execute('INSERT INTO fx_snapshots(source_date,payload) VALUES(?,?)',(date,json.dumps({'rates':{'DKK':7.4,'USD':1.1}})))
  class Client:
   def _http(self,base,path,params):return {'status':'OK','payload':[{'date':'2026-11-05','close':10},{'date':'2026-11-06','close':11}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()),patch.object(sector,'_reuse_hotwatch_asset',return_value=True):
   sector.refresh_tick(self.connect);sector.refresh_tick(self.connect)
  with self.connect() as c:market=c.execute("SELECT status FROM sector_market WHERE symbol='XLK.US'").fetchone()
  self.assertIsNotNone(market);self.assertEqual(market['status'],'OK')
 def test_reuses_stored_watch_metadata_without_new_pluto_lookup(self):
  now=time.time();proof={'symbol':'BTC-USD.CC','pluto':{'asset_id':'btc','ticker':'BTC','currency':'USD','exchange':'WINTERMUTE','type':'CRYPTO','name':'Bitcoin'}}
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'btc','BTC','USD','WINTERMUTE','BTC-USD.CC','',now))
   c.execute('INSERT INTO hw_cxe_feed_evidence VALUES(?,?,?,?,?,?,?)',(1,'btc','BTC-USD.CC',json.dumps(proof),now,now+3600,'MATCHED'))
  self.assertTrue(sector._reuse_hotwatch_asset(self.connect,(1,'btc','BTC'),now))
  with self.connect() as c:row=c.execute("SELECT * FROM sector_assets WHERE asset_id='btc'").fetchone()
  self.assertEqual(row['sector'],'Krypto (aktivklasse)')
  self.assertFalse(sector._reuse_hotwatch_asset(self.connect,(1,'btc','OTHER'),now))
 def test_benchmark_holdings_require_verified_known_fund_and_are_cached(self):
  now=time.time()
  with self.assertRaises(ValueError):sector.request_benchmark_holdings(self.connect,1,'NOT-ALLOWED.US')
  self.assertEqual(sector.request_benchmark_holdings(self.connect,1,'XLK.US')['status'],'UNVERIFIED_BENCHMARK')
  with self.connect() as c:c.execute('INSERT INTO sector_benchmarks(symbol,region,sector,status,updated,next_attempt) VALUES(?,?,?,?,?,?)',('XLK.US','USA','Teknologi','VERIFIED',now,now+1000))
  self.assertEqual(sector.request_benchmark_holdings(self.connect,1,'XLK.US')['status'],'TRY_ISSUER')
  with self.connect() as c:c.execute("UPDATE sector_benchmark_holdings SET status='PENDING' WHERE symbol='XLK.US'")
  class Client:
   def _http(self,base,path,params):
    assert path=='/fundamentals/XLK.US' and params['filter']=='ETF_Data::Holdings'
    return {'status':'OK','payload':{'LOW.US':{'Code':'LOW','Name':'Low Co','Exchange':'US','Assets_%':1.0},'HIGH.US':{'Code':'HIGH','Name':'High Co','Exchange':'US','Assets_%':5.0}}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_benchmark_holdings').fetchone()
  self.assertEqual(row['status'],'OK');payload=json.loads(row['payload'])
  self.assertEqual([x['ticker'] for x in payload['rows']],['HIGH','LOW']);self.assertEqual(payload['total_reported'],2)
  self.assertEqual(sector.request_benchmark_holdings(self.connect,1,'XLK.US')['status'],'OK')
 def test_benchmark_holdings_fall_back_to_top_10(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO sector_benchmarks(symbol,region,sector,status,updated,next_attempt) VALUES(?,?,?,?,?,?)',('XLK.US','USA','Teknologi','VERIFIED',now,now+1000))
  sector.request_benchmark_holdings(self.connect,1,'XLK.US')
  with self.connect() as c:c.execute("UPDATE sector_benchmark_holdings SET status='PENDING' WHERE symbol='XLK.US'")
  class Client:
   def _http(self,base,path,params):
    if params['filter']=='ETF_Data::Holdings':return {'status':'RESPONSE_TOO_LARGE'}
    return {'status':'OK','payload':{'MSFT.US':{'Code':'MSFT','Name':'Microsoft','Exchange':'US','Assets_%':12}}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect);sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_benchmark_holdings').fetchone()
  self.assertTrue(json.loads(row['payload'])['top10_only']);self.assertEqual(row['status'],'OK')
 def test_us_holdings_use_issuer_and_cache(self):
  now=time.time()
  with self.connect() as c:c.execute('INSERT INTO sector_benchmarks(symbol,region,sector,status,updated,next_attempt) VALUES(?,?,?,?,?,?)',('XLU.US','USA','Forsyning','VERIFIED',now,now+1000))
  self.assertEqual(sector.request_benchmark_holdings(self.connect,1,'XLU.US')['status'],'TRY_ISSUER')
  from test_ssga_holdings import IssuerHoldingsTest
  raw=IssuerHoldingsTest().workbook()
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,size):return raw
  class Opener:
   def open(self,request,timeout):
    self.url=request.full_url;self.asserted=request.full_url.endswith('holdings-daily-us-en-xlu.xlsx')
    if not self.asserted:raise AssertionError('wrong fund URL')
    return Response()
  with patch('ssga_holdings.urllib.request.build_opener',return_value=Opener()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_benchmark_holdings').fetchone()
  self.assertEqual(row['status'],'OK');self.assertEqual(json.loads(row['payload'])['source'],'State Street / SPDR');self.assertEqual(json.loads(row['payload'])['rows'][0]['ticker'],'NEE')
  self.assertEqual(sector.request_benchmark_holdings(self.connect,1,'XLU.US')['status'],'OK')
 def test_global_benchmark_uses_provider_search_before_fundamentals(self):
  class Client:
   def _http(self,base,path,params):
    if path=='/search/IXN':return {'status':'OK','payload':[{'Code':'IXN','Exchange':'US','Name':'iShares Global Tech ETF','Currency':'USD','Type':'ETF'}]}
    if path=='/eod/IXN.US':return {'status':'OK','payload':[{'date':'2026-11-05','close':10},{'date':'2026-11-06','close':11}]}
    raise AssertionError('Unexpected request '+path)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'PROXIES',{'Globalt':[('IXN.US','Teknologi')]}),patch.object(sector,'_client',return_value=Client()):
   sector.refresh_tick(self.connect);sector.refresh_tick(self.connect)
  with self.connect() as c:
   b=c.execute('SELECT * FROM sector_benchmarks').fetchone();m=c.execute('SELECT * FROM sector_market').fetchone()
  self.assertEqual((b['status'],b['proof_source']),('VERIFIED','EODHD instrumentsøgning'));self.assertEqual(m['status'],'OK')
 def test_europe_name_search_discovers_verified_travel_fund(self):
  valid={'Code':'EXXY','Exchange':'XETRA','Name':'iShares STOXX Europe 600 Travel & Leisure UCITS ETF (DE)','Currency':'EUR','Type':'ETF'}
  wrong={**valid,'Code':'OTHER','Exchange':'US'}
  with self.connect() as c:
   c.execute('UPDATE sector_europe_queries SET next_attempt=?',(time.time()+86400,))
   c.execute("UPDATE sector_europe_queries SET next_attempt=0 WHERE query='Travel & Leisure'")
  class Client:
   def _http(self,base,path,params):
    if path=='/search/Travel%20%26%20Leisure':return {'status':'OK','payload':[valid,wrong]}
    if path=='/eod/EXXY.XETRA':return {'status':'OK','payload':[{'date':'2026-11-05','close':10},{'date':'2026-11-06','close':11}]}
    raise AssertionError(path)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'PROXIES',{'Europa':[]}),patch.object(sector,'_client',return_value=Client()):
   sector.refresh_tick(self.connect);sector.refresh_tick(self.connect)
  with self.connect() as c:
   result=c.execute("SELECT * FROM sector_benchmarks WHERE symbol='EXXY.XETRA'").fetchone()
   market=c.execute("SELECT * FROM sector_market WHERE symbol='EXXY.XETRA'").fetchone()
   none=c.execute("SELECT * FROM sector_benchmarks WHERE symbol='OTHER.XETRA'").fetchone()
  self.assertEqual((result['sector'],result['status']),('Rejser og fritid','VERIFIED'))
  self.assertEqual(market['status'],'OK');self.assertIsNone(none)
 def test_discovery_checks_listing_and_sector_before_loading(self):
  row={'Code':'EXH2','Exchange':'XETRA','Name':'iShares STOXX Europe 600 Technology UCITS ETF (DE)','Currency':'EUR','Type':'ETF'}
  self.assertEqual(sector._europe_discovery(row,'EXH2'),'Teknologi')
  self.assertIsNone(sector._europe_discovery({**row,'Exchange':'F'},'EXH2'))
  self.assertIsNone(sector._europe_discovery({**row,'Name':'Unrelated Technology Fund'},'EXH2'))
  with self.connect() as c:
   c.execute("UPDATE sector_europe_queries SET next_attempt=?",(time.time()+86400,))
   c.execute("UPDATE sector_europe_discovery SET next_attempt=?",(time.time()+86400,))
   c.execute("UPDATE sector_europe_discovery SET next_attempt=0 WHERE code='EXH2'")
  class Client:
   def _http(self,base,path,params):
    if path=='/search/EXH2':return {'status':'OK','payload':[row]}
    if path=='/eod/EXH2.XETRA':return {'status':'OK','payload':[{'date':'2026-11-05','close':10},{'date':'2026-11-06','close':11}]}
    raise AssertionError(path)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'PROXIES',{'Europa':[]}),patch.object(sector,'_client',return_value=Client()):
   sector.refresh_tick(self.connect);sector.refresh_tick(self.connect)
  with self.connect() as c:
   b=c.execute('SELECT * FROM sector_benchmarks WHERE symbol=?',('EXH2.XETRA',)).fetchone()
   m=c.execute('SELECT * FROM sector_market WHERE symbol=?',('EXH2.XETRA',)).fetchone()
  self.assertEqual((b['sector'],b['status']),('Teknologi','VERIFIED'));self.assertEqual(m['status'],'OK')
 def test_european_xetra_benchmarks_use_search_proof(self):
  cases=[('EXH4','Industri','Industrial Goods & Services'),('EXH1','Energi','Oil & Gas'),('EXV6','Råvarer','Basic Resources'),('EXH6','Medier','Media')]
  for code,sector_name,name in cases:
   row={'Code':code,'Exchange':'XETRA','Name':'iShares STOXX Europe 600 '+name+' UCITS ETF (DE)','CurrencyCode':'EUR','Type':'ETF'}
   self.assertTrue(sector._benchmark_identity('Europa',sector_name,code+'.XETRA',row))
   row['Exchange']='F'
   self.assertFalse(sector._benchmark_identity('Europa',sector_name,code+'.XETRA',row))
 def test_global_communications_abbreviation_is_recognized(self):
  row={'Code':'IXP','Exchange':'US','Name':'iShares Global Comm Services ETF','CurrencyCode':'USD','Type':'ETF'}
  self.assertTrue(sector._benchmark_identity('Globalt','Kommunikation','IXP.US',row))
  row['Name']='iShares Global Healthcare ETF'
  self.assertFalse(sector._benchmark_identity('Globalt','Kommunikation','IXP.US',row))
 def test_global_benchmark_search_rejects_wrong_sector(self):
  class Client:
   def _http(self,base,path,params):return {'status':'OK','payload':[{'Code':'IXN','Exchange':'US','Name':'iShares Global Healthcare ETF','Currency':'USD','Type':'ETF'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'PROXIES',{'Globalt':[('IXN.US','Teknologi')]}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:b=c.execute('SELECT * FROM sector_benchmarks').fetchone()
  self.assertEqual(b['status'],'TRY_FUNDAMENTALS')
 def test_published_us_benchmark_does_not_require_fundamentals_permission(self):
  class Client:
   def _http(self,base,path,params):
    self.path=path
    return {'status':'OK','payload':[{'date':'2026-11-05','close':'10'},{'date':'2026-11-06','close':'11'}]}
  client=Client()
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=client):sector.refresh_tick(self.connect)
  self.assertTrue(client.path.startswith('/eod/XLK.US'))
  with self.connect() as c:
   bench=c.execute('SELECT * FROM sector_benchmarks WHERE symbol=?',('XLK.US',)).fetchone()
   market=c.execute('SELECT * FROM sector_market WHERE symbol=?',('XLK.US',)).fetchone()
  self.assertEqual(bench['status'],'VERIFIED');self.assertIn('ssga.com',bench['proof_source']);self.assertEqual(market['status'],'OK')
 def test_upgrade_retries_only_previously_blocked_rows_once(self):
  with self.connect() as c:
   c.execute("DELETE FROM sector_migrations WHERE name='reuse_verified_feed_v2'")
   c.execute("INSERT INTO sector_assets(user_id,asset_id,status,updated,next_attempt) VALUES(1,'blocked','PLUTO_IDENTITY_INCOMPLETE',0,9999999999)")
   c.execute("INSERT INTO sector_assets(user_id,asset_id,status,updated,next_attempt) VALUES(1,'good','OK',0,9999999999)")
   c.execute("INSERT INTO sector_market(symbol,region,sector,status,updated,next_attempt) VALUES('XLK.US','USA','Teknologi','UNVERIFIED_BENCHMARK',0,9999999999)")
   sector.init(c)
   rows={r['asset_id']:r['next_attempt'] for r in c.execute('SELECT asset_id,next_attempt FROM sector_assets')}
   self.assertEqual(rows,{'blocked':0,'good':9999999999})
   self.assertEqual(c.execute('SELECT next_attempt FROM sector_market').fetchone()[0],0)
   c.execute("UPDATE sector_assets SET next_attempt=9999999999 WHERE asset_id='blocked'");sector.init(c)
   self.assertEqual(c.execute("SELECT next_attempt FROM sector_assets WHERE asset_id='blocked'").fetchone()[0],9999999999)
 def test_upgrade_retries_previously_blocked_data_once(self):
  with self.connect() as c:
   c.execute("DELETE FROM sector_migrations WHERE name='reuse_hotwatch_proof_v1'")
   c.execute("INSERT INTO sector_assets(user_id,asset_id,status,updated,next_attempt) VALUES(1,'asset','PLUTO_IDENTITY_INCOMPLETE',0,9999999999)")
   sector.init(c);self.assertEqual(c.execute('SELECT next_attempt FROM sector_assets').fetchone()[0],0)
   c.execute('UPDATE sector_assets SET next_attempt=9999999999');sector.init(c)
   self.assertEqual(c.execute('SELECT next_attempt FROM sector_assets').fetchone()[0],9999999999)
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
 def test_verified_adr_accepts_provider_common_stock_label(self):
  now=time.time()
  with self.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',(1,'adr','ABC','USD','NYSE','ABC.US','US5949181045',now))
   c.execute('INSERT INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(1,'adr','ABC','USD','NYSE','US5949181045','ADR','Microsoft','OK',now,now+3600))
  class Client:
   def _http(self,*args):return {'status':'OK','payload':{'Code':'ABC','ISIN':'US5949181045','CurrencyCode':'USD','Exchange':'NYSE','Name':'Microsoft','Type':'Common Stock','Sector':'Technology'}}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'test'}),patch.object(sector,'_client',return_value=Client()):sector.refresh_tick(self.connect)
  with self.connect() as c:row=c.execute('SELECT * FROM sector_assets').fetchone()
  self.assertEqual(row['sector'],'Teknologi');self.assertEqual(row['status'],'OK')
 def test_series_sorts_and_discards_invalid(self):
  result=sector._series([{'date':'2026-10-02','close':4},{'date':'invalid','close':7},{'date':'2026-10-01','close':2},{'date':'2026-10-03','close':-1}])
  self.assertEqual([x['date'] for x in result],['2026-10-01','2026-10-02'])

if __name__=='__main__':unittest.main()
