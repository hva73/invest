"""Read-only sector data; background collection never places or changes orders."""
from eodhd_capacity import Capacity
import json, math, os, re, sqlite3, time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from eodhd_feeds import EODHDFeeds, HTTP_BASE
from hotwatch_adapters import reserve

# ETFs are comparison instruments, not a measure of fund flows or an entire region.
PROXIES = {
 'USA': [('XLK.US','Teknologi'),('XLV.US','Sundhed'),('XLF.US','Finans'),('XLI.US','Industri'),('XLE.US','Energi'),('XLY.US','Forbrug, cyklisk'),('XLP.US','Forbrug, stabilt'),('XLB.US','Materialer'),('XLU.US','Forsyning'),('XLRE.US','Ejendomme'),('XLC.US','Kommunikation')],
 'Globalt': [('IXN.US','Teknologi'),('IXJ.US','Sundhed'),('IXG.US','Finans'),('EXI.US','Industri'),('IXC.US','Energi'),('RXI.US','Forbrug, cyklisk'),('KXI.US','Forbrug, stabilt'),('MXI.US','Materialer'),('JXI.US','Forsyning'),('IXP.US','Kommunikation')],
 'Europa': [('EUFN.US','Finans'),('EXH4.XETRA','Industri'),('EXH1.XETRA','Energi'),('EXV6.XETRA','Råvarer'),('EXH6.XETRA','Medier')], 'Asien': []}
SECTORS={'information technology':'Teknologi','technology':'Teknologi','health care':'Sundhed','healthcare':'Sundhed','financial services':'Finans','financials':'Finans','industrials':'Industri','energy':'Energi','consumer discretionary':'Forbrug, cyklisk','consumer cyclicals':'Forbrug, cyklisk','consumer cyclical':'Forbrug, cyklisk','consumer staples':'Forbrug, stabilt','consumer defensive':'Forbrug, stabilt','materials':'Materialer','basic materials':'Materialer','utilities':'Forsyning','real estate':'Ejendomme','communication services':'Kommunikation'}

def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS sector_assets(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,symbol TEXT,sector TEXT,industry TEXT,source TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 if 'identity_version' not in {r[1] for r in c.execute('PRAGMA table_info(sector_assets)')}:c.execute('ALTER TABLE sector_assets ADD COLUMN identity_version INTEGER NOT NULL DEFAULT 0')
 if 'original_sector' not in {r[1] for r in c.execute('PRAGMA table_info(sector_assets)')}:c.execute('ALTER TABLE sector_assets ADD COLUMN original_sector TEXT')
 c.execute('CREATE TABLE IF NOT EXISTS sector_instruments(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,ticker TEXT,currency TEXT,exchange TEXT,isin TEXT,instrument_type TEXT,name TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 c.execute('CREATE TABLE IF NOT EXISTS sector_identity_attempts(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,fingerprint TEXT NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 c.execute('CREATE TABLE IF NOT EXISTS sector_fx(currency TEXT PRIMARY KEY, rate REAL, event_time TEXT, status TEXT NOT NULL, updated REAL NOT NULL, next_attempt REAL NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS sector_fund_exposure(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,symbol TEXT NOT NULL,payload TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 c.execute('CREATE TABLE IF NOT EXISTS sector_benchmarks(symbol TEXT PRIMARY KEY,region TEXT NOT NULL,sector TEXT NOT NULL,name TEXT,currency TEXT,exchange TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL)')
 if 'proof_source' not in {r[1] for r in c.execute('PRAGMA table_info(sector_benchmarks)')}:c.execute('ALTER TABLE sector_benchmarks ADD COLUMN proof_source TEXT')
 c.execute('CREATE TABLE IF NOT EXISTS sector_benchmark_holdings(symbol TEXT PRIMARY KEY,payload TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS sector_holding_prices(ticker TEXT NOT NULL,identifier TEXT NOT NULL,status TEXT NOT NULL,payload TEXT,updated REAL NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(ticker,identifier))')
 c.execute('CREATE TABLE IF NOT EXISTS sector_europe_discovery(code TEXT PRIMARY KEY,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS sector_europe_queries(query TEXT PRIMARY KEY,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL)')
 for query in ('STOXX Europe 600','Travel & Leisure','EXH','EXV'):
  c.execute("INSERT OR IGNORE INTO sector_europe_queries VALUES(?,'PENDING',0,0)",(query,))
 for prefix in ('EXV','EXH'):
  for number in range(1,10):
   code=prefix+str(number)
   if (code+'.XETRA') not in {symbol for symbol,_ in PROXIES['Europa']}:c.execute("INSERT OR IGNORE INTO sector_europe_discovery VALUES(?,'PENDING',0,0)",(code,))
 c.execute('CREATE TABLE IF NOT EXISTS sector_market(symbol TEXT PRIMARY KEY,region TEXT NOT NULL,sector TEXT NOT NULL,payload TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL)')
 if 'price_basis' not in {r[1] for r in c.execute('PRAGMA table_info(sector_market)')}:c.execute('ALTER TABLE sector_market ADD COLUMN price_basis TEXT')
 c.execute('CREATE TABLE IF NOT EXISTS sector_history(user_id INTEGER NOT NULL,portfolio_id INTEGER NOT NULL,bucket INTEGER NOT NULL,observed TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(user_id,portfolio_id,bucket))')
 c.execute('CREATE TABLE IF NOT EXISTS sector_migrations(name TEXT PRIMARY KEY,applied REAL NOT NULL)')
 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='reuse_hotwatch_proof_v1'").fetchone():
  c.execute("UPDATE sector_assets SET next_attempt=0 WHERE status IN ('PLUTO_IDENTITY_INCOMPLETE','IDENTITY_OR_SECTOR_UNKNOWN','ENTITLEMENT_UNVERIFIED')")
  c.execute("UPDATE sector_market SET next_attempt=0 WHERE status='UNVERIFIED_BENCHMARK'")
  c.execute("INSERT INTO sector_migrations VALUES('reuse_hotwatch_proof_v1',?)",(time.time(),))
 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='reuse_verified_feed_v2'").fetchone():
  c.execute("UPDATE sector_assets SET next_attempt=0 WHERE status IN ('PLUTO_IDENTITY_INCOMPLETE','IDENTITY_OR_SECTOR_UNKNOWN','ENTITLEMENT_UNVERIFIED','PLUTO_UNAVAILABLE')")
  c.execute("UPDATE sector_instruments SET next_attempt=0 WHERE status IN ('PLUTO_UNAVAILABLE','PLUTO_TYPE_MISSING')")
  c.execute("UPDATE sector_market SET next_attempt=0 WHERE status='UNVERIFIED_BENCHMARK'")
  c.execute("INSERT INTO sector_migrations VALUES('reuse_verified_feed_v2',?)",(time.time(),))
 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='benchmark_search_v1'").fetchone():
  c.execute("UPDATE sector_benchmarks SET status='TRY_SEARCH',next_attempt=0 WHERE region IN ('Globalt','Europa') AND status!='VERIFIED'")
  c.execute("UPDATE sector_market SET next_attempt=0 WHERE status='UNVERIFIED_BENCHMARK' OR NOT EXISTS (SELECT 1 FROM sector_benchmarks b WHERE b.symbol=sector_market.symbol AND b.status='VERIFIED' AND b.updated>=?)",(time.time()-7*86400,))
  c.execute("INSERT INTO sector_migrations VALUES('benchmark_search_v1',?)",(time.time(),))

 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='ixp_comm_name_v1'").fetchone():
  c.execute("UPDATE sector_benchmarks SET status='TRY_SEARCH',next_attempt=0 WHERE symbol='IXP.US' AND status!='VERIFIED'")
  c.execute("UPDATE sector_market SET next_attempt=0 WHERE symbol='IXP.US' AND status='UNVERIFIED_BENCHMARK'")
  c.execute("INSERT INTO sector_migrations VALUES('ixp_comm_name_v1',?)",(time.time(),))

 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='ssga_holdings_v1'").fetchone():
  symbols=[symbol for symbol,_ in PROXIES['USA']]
  for symbol in symbols:
   c.execute("UPDATE sector_benchmark_holdings SET status='TRY_ISSUER',next_attempt=0 WHERE symbol=? AND status IN ('ENTITLEMENT_UNVERIFIED','NO_DATA','RESPONSE_TOO_LARGE','PROVIDER_REJECTED')",(symbol,))
  c.execute("INSERT INTO sector_migrations VALUES('ssga_holdings_v1',?)",(time.time(),))

 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='ssga_canonical_url_v1'").fetchone():
  for symbol,_ in PROXIES['USA']:
   c.execute("UPDATE sector_benchmark_holdings SET status='TRY_ISSUER',next_attempt=0 WHERE symbol=? AND status IN ('ISSUER_HTTP_301','ISSUER_HTTP_302','ISSUER_HTTP_303','ISSUER_HTTP_307','ISSUER_HTTP_308')",(symbol,))
  c.execute("INSERT INTO sector_migrations VALUES('ssga_canonical_url_v1',?)",(time.time(),))

 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='ssga_cusip_v1'").fetchone():
  for symbol,_ in PROXIES['USA']:
   c.execute("UPDATE sector_benchmark_holdings SET status='TRY_ISSUER',next_attempt=0 WHERE symbol=? AND status='OK' AND payload NOT LIKE '%\"identifier\"%'",(symbol,))
  c.execute("INSERT INTO sector_migrations VALUES('ssga_cusip_v1',?)",(time.time(),))

 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='ishares_us_holdings_v1'").fetchone():
  for symbol in [s for s,_ in PROXIES['Globalt']]+['EUFN.US']:
   c.execute("UPDATE sector_benchmark_holdings SET status='TRY_ISHARES',next_attempt=0 WHERE symbol=? AND status IN ('ENTITLEMENT_UNVERIFIED','NO_DATA','RESPONSE_TOO_LARGE','PROVIDER_REJECTED','PENDING','TRY_TOP10')",(symbol,))
  c.execute("INSERT INTO sector_migrations VALUES('ishares_us_holdings_v1',?)",(time.time(),))

 if not c.execute("SELECT 1 FROM sector_migrations WHERE name='ishares_europe_holdings_v1'").fetchone():
  c.execute("UPDATE sector_benchmark_holdings SET status='TRY_ISHARES_EU',next_attempt=0 WHERE symbol IN (SELECT symbol FROM sector_benchmarks WHERE region='Europa' AND status='VERIFIED' AND exchange='XETRA') AND status IN ('ENTITLEMENT_UNVERIFIED','NO_DATA','RESPONSE_TOO_LARGE','PROVIDER_REJECTED','PENDING','TRY_TOP10')")
  c.execute("INSERT INTO sector_migrations VALUES('ishares_europe_holdings_v1',?)",(time.time(),))

def capture(c,uid,pid,payload):
 if not payload.get('positions_complete') or not payload.get('observed'):return
 try:bucket=int(datetime.fromisoformat(payload['observed'].replace('Z','+00:00')).timestamp())//14400
 except (ValueError,TypeError,AttributeError):return
 rows=[r for r in payload.get('positions',[]) if r.get('kind')!='collection' and r.get('asset_id')]
 c.execute('INSERT OR REPLACE INTO sector_history VALUES(?,?,?,?,?)',(uid,pid,bucket,payload['observed'],json.dumps(rows,separators=(',',':'))))

def _client(connect,uid):
 return EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),capacity=Capacity(connect))

def _num(v):
 if isinstance(v,bool):return None
 try:
  x=float(v)
  return x if math.isfinite(x) else None
 except (TypeError,ValueError,OverflowError):return None

def _series(payload):
 out={}
 rows=payload if isinstance(payload,list) else []
 # Never mix adjusted and unadjusted prices within the same return series.
 use_adjusted=bool(rows) and all(_num(row.get('adjusted_close')) is not None and _num(row.get('adjusted_close'))>0 for row in rows if isinstance(row,dict))
 for row in rows:
  if not isinstance(row,dict):continue
  try:d=datetime.strptime(row.get('date',''),'%Y-%m-%d').date()
  except (TypeError,ValueError):continue
  v=_num(row.get('adjusted_close' if use_adjusted else 'close'))
  if v and v>0 and d<=datetime.now(timezone.utc).date():out[d.isoformat()]=v
 return [{'date':d,'close':out[d]} for d in sorted(out)]

def _pluto_candidate(connect,now):
 with connect() as c:
  snapshots=c.execute("SELECT s.user_id,s.payload FROM portfolio_snapshots s JOIN portfolios p ON p.id=s.portfolio_id AND p.user_id=s.user_id WHERE p.active=1 AND p.source='pluto'").fetchall()
  existing={(r['user_id'],r['asset_id']):dict(r) for r in c.execute('SELECT * FROM sector_instruments')}
 for snap in snapshots:
  try:payload=json.loads(snap['payload'])
  except (ValueError,TypeError):continue
  for pos in payload.get('positions',[]):
   aid=pos.get('asset_id');old=existing.get((snap['user_id'],aid))
   if not aid or pos.get('kind')=='collection':continue
   if old is None or old['next_attempt']<=now:return snap['user_id'],aid,pos.get('ticker')
   changed=any(pos.get(key) and old.get(key) and str(pos[key]).casefold()!=str(old[key]).casefold() for key in ('ticker','currency'))
   if changed:
    fingerprint=json.dumps([pos.get('ticker'),pos.get('currency')],separators=(',',':'))
    with connect() as c:
     previous=c.execute('SELECT fingerprint,next_attempt FROM sector_identity_attempts WHERE user_id=? AND asset_id=?',(snap['user_id'],aid)).fetchone()
     if previous and previous['fingerprint']==fingerprint and previous['next_attempt']>now:continue
     c.execute('INSERT OR REPLACE INTO sector_identity_attempts VALUES(?,?,?,?)',(snap['user_id'],aid,fingerprint,now+300))
    return snap['user_id'],aid,pos.get('ticker')
 return None

def _kind(kind):
 value=re.sub(r'[^A-Z0-9]','',str(kind or '').upper())
 if value in ('CRYPTO','CRYPTOCURRENCY','TOKEN'):return 'crypto'
 if value in ('ETF','ETP','FUND','MUTUALFUND','INVESTMENTFUND'):return 'fund'
 if value in ('CS','ADRC','ADR','COMMONSTOCK','ORDINARYSHARES','STOCK','EQUITY'):return 'stock'
 if value in ('CASH','CURRENCY','FOREX'):return 'cash'
 if value in ('COMMODITY','PRECIOUSMETAL'):return 'commodity'
 return 'unknown'

def _fetch_pluto(connect,candidate,now):
 import trade_service
 from hotwatch_adapters import PlutoAdapter
 uid,aid,ticker=candidate;adapter=PlutoAdapter(connect,uid,purpose='sector')
 sector=industry=raw_sector=None;instrument={};status='PLUTO_UNAVAILABLE'
 try:
  client,tools=trade_service.client(connect,uid,adapter.factory)
  raw=trade_service.call(client,tools,'get_asset',{'assetId':aid})
  asset=raw.get('asset',raw) if isinstance(raw,dict) else {}
  ids=[x for x in (asset.get('id'),asset.get('assetId'),raw.get('assetId')) if x is not None]
  if not ids or any(x!=aid for x in ids) or ticker and asset.get('ticker') and ticker.casefold()!=str(asset['ticker']).casefold():raise ValueError('identity')
  kind=str(asset.get('type') or asset.get('assetType') or '').upper()
  instrument={'ticker':asset.get('ticker') or ticker,'currency':asset.get('currency'),'exchange':asset.get('exchange'),'isin':asset.get('isin') or asset.get('ISIN'),'instrument_type':kind,'name':asset.get('name')}
  asset_kind=_kind(kind)
  if asset_kind=='crypto':sector='Krypto (aktivklasse)'
  elif asset_kind=='fund':sector='Fonde og ETF (aktivklasse)'
  elif asset_kind=='cash':sector='Kontanter (aktivklasse)'
  elif asset_kind=='commodity':sector='Råvarer (aktivklasse)'
  elif asset_kind=='stock' and isinstance(asset.get('sector'),str) and asset['sector'].strip():
   raw_sector=asset['sector'].strip();sector=SECTORS.get(raw_sector.casefold(),raw_sector)
   industry=asset.get('industry') if isinstance(asset.get('industry'),str) else None
  status='OK' if asset_kind!='unknown' else 'PLUTO_TYPE_MISSING'
 except Exception:pass
 with connect() as c:
  c.execute('INSERT OR REPLACE INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,aid,instrument.get('ticker'),instrument.get('currency'),instrument.get('exchange'),instrument.get('isin'),instrument.get('instrument_type'),instrument.get('name'),status,now,now+(7*86400 if status=='OK' else _retry_delay(status))))
  if sector:c.execute('INSERT OR REPLACE INTO sector_assets(user_id,asset_id,symbol,sector,industry,source,status,updated,next_attempt,identity_version,original_sector) VALUES(?,?,?,?,?,?,?,?,?,1,?)',(uid,aid,None,sector,industry,'Pluto get_asset','OK',now,now+7*86400,raw_sector))

def _verified_stock_basis(connect,uid,instrument,link,now):
 """Reuse the asset-specific listing already verified by HOT WATCH.

 Sector display does not place orders. Missing fields are not treated as a
 contradiction; explicit ticker, currency, exchange or ISIN conflicts are.
 """
 if not link or instrument.get('asset_id')!=link.get('asset_id'):return None
 isin=link.get('isin')
 if not isinstance(isin,str) or not re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',isin):return None
 for key in ('ticker','currency','exchange','isin'):
  left=instrument.get(key);right=link.get(key)
  if left and right and str(left).casefold()!=str(right).casefold():return None
 return 'previously_verified_hotwatch_link'

def _retry_delay(status):
 if status in ('LOCAL_BUDGET_EXHAUSTED','PROVIDER_RATE_BUDGET','RATE_LIMIT'):return 120
 if status in ('NETWORK_OR_RESPONSE_ERROR','HTTP_ERROR','PLUTO_UNAVAILABLE'):return 300
 if status in ('ENTITLEMENT_UNVERIFIED','KEY_MISSING'):return 3600
 return 21600

def _reuse_hotwatch_asset(connect,candidate,now):
 """Copy broker metadata from an already verified watch; no provider call."""
 uid,aid,ticker=candidate
 try:
  with connect() as c:
   row=c.execute('SELECT e.payload,e.symbol,e.status,l.symbol AS linked_symbol,l.currency AS linked_currency FROM hw_cxe_feed_evidence e JOIN hw_verified_feed_links l ON l.user_id=e.user_id AND l.asset_id=e.asset_id WHERE e.user_id=? AND e.asset_id=?',(uid,aid)).fetchone()
   if not row or row['status']!='MATCHED' or row['symbol']!=row['linked_symbol']:return False
   proof=json.loads(row['payload']);asset=proof.get('pluto') or {}
   if proof.get('symbol')!=row['symbol'] or asset.get('asset_id')!=aid or not asset.get('ticker') or ticker and str(asset['ticker']).casefold()!=str(ticker).casefold() or asset.get('currency')!=row['linked_currency']:return False
   kind=_kind(asset.get('type'))
   if kind=='unknown':return False
   c.execute('INSERT OR REPLACE INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,aid,asset.get('ticker'),asset.get('currency'),asset.get('exchange'),asset.get('isin'),asset.get('type'),asset.get('name'),'OK',now,now+7*86400))
   category={'crypto':'Krypto (aktivklasse)','fund':'Fonde og ETF (aktivklasse)','cash':'Kontanter (aktivklasse)','commodity':'Råvarer (aktivklasse)'}.get(kind)
   if category:c.execute('INSERT OR REPLACE INTO sector_assets(user_id,asset_id,symbol,sector,industry,source,status,updated,next_attempt,identity_version,original_sector) VALUES(?,?,?,?,?,?,?,?,?,1,?)',(uid,aid,None,category,None,'Pluto / HOT WATCH','OK',now,now+7*86400,None))
  return True
 except (ValueError,TypeError,sqlite3.Error):return False

def _benchmark_identity(region,sector,symbol,general):
 if not isinstance(general,dict):return False
 code=str(general.get('Code') or '').upper();name=str(general.get('Name') or '');upper=name.upper()
 exchange=str(general.get('Exchange') or '').upper().strip();currency=str(general.get('CurrencyCode') or '').upper()
 european_xetra={'EXH4.XETRA':('Industri','INDUSTRIAL GOODS'), 'EXH1.XETRA':('Energi','OIL & GAS'), 'EXV6.XETRA':('Råvarer','BASIC RESOURCES'), 'EXH6.XETRA':('Medier','MEDIA')}
 if region=='Europa' and symbol in european_xetra:
  label,term=european_xetra[symbol]
  typ=re.sub(r'[^A-Z0-9]','',str(general.get('Type') or '').upper())
  return sector==label and code==symbol.split('.')[0] and exchange=='XETRA' and currency=='EUR' and typ in ('ETF','ETP','FUND') and 'ISHARES' in upper and 'STOXX EUROPE 600' in upper and term in upper
 typ=re.sub(r'[^A-Z0-9]','',str(general.get('Type') or '').upper())
 if code!=symbol.rsplit('.',1)[0] or currency!='USD' or typ not in ('ETF','ETP','FUND') or exchange not in ('NYSE ARCA','NYSEARCA','NASDAQ','NYSE','BATS','CBOE','ARCA','US'):return False
 if region=='USA' and ('SELECT SECTOR' not in upper or 'SPDR' not in upper):return False
 if region=='Globalt' and ('GLOBAL' not in upper or 'ISHARES' not in upper):return False
 if region=='Europa' and ('EUROPE' not in upper or 'FINANCIAL' not in upper):return False
 terms={'Teknologi':('TECH',),'Sundhed':('HEALTH',),'Finans':('FINANCIAL',),'Industri':('INDUSTRIAL',),'Energi':('ENERGY',),'Forbrug, cyklisk':('CONSUMER DISCRETIONARY','CONSUMER CYCLICAL'),'Forbrug, stabilt':('CONSUMER STAPLES','CONSUMER DEFENSIVE'),'Materialer':('MATERIAL',),'Forsyning':('UTILIT',),'Ejendomme':('REAL ESTATE',),'Kommunikation':('COMMUNICATION','COMM SERVICES','TELECOM')}
 return any(word in upper for word in terms.get(sector,()))

def _europe_discovery(row,code):
 """Accept only the exact XETRA listing of a named STOXX Europe 600 ETF."""
 if not isinstance(row,dict) or str(row.get('Code','')).upper()!=code or str(row.get('Exchange','')).upper()!='XETRA' or str(row.get('Currency','')).upper()!='EUR' or str(row.get('Type','')).upper() not in ('ETF','ETP','FUND'):return None
 name=str(row.get('Name') or '').upper()
 if 'ISHARES' not in name or 'STOXX EUROPE 600' not in name:return None
 terms=(('INDUSTRIAL GOODS','Industri'),('OIL & GAS','Energi'),('BASIC RESOURCES','Råvarer'),('MEDIA','Medier'),('TECHNOLOGY','Teknologi'),('HEALTH CARE','Sundhed'),('HEALTHCARE','Sundhed'),('UTILITIES','Forsyning'),('CHEMICALS','Kemikalier'),('CONSTRUCTION & MATERIALS','Byggeri og materialer'),('AUTOMOBILES','Biler'),('BANKS','Banker'),('FINANCIAL SERVICES','Finansielle tjenester'),('INSURANCE','Forsikring'),('FOOD & BEVERAGE','Fødevarer'),('PERSONAL & HOUSEHOLD','Personlige og husholdningsvarer'),('REAL ESTATE','Ejendomme'),('RETAIL','Detailhandel'),('TELECOMMUNICATIONS','Telekommunikation'),('TRAVEL & LEISURE','Rejser og fritid'),('TRAVEL AND LEISURE','Rejser og fritid'))
 matches=[label for term,label in terms if term in name]
 return matches[0] if len(set(matches))==1 else None

def _queue_holding_prices(c,rows,limit,now):
 for row in rows[:limit]:
  ticker=str(row.get('ticker') or '').upper();identifier=str(row.get('identifier') or '').upper()
  if not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,14}',ticker) or not re.fullmatch(r'[A-Z0-9]{9}',identifier):continue
  existing=c.execute('SELECT status,next_attempt FROM sector_holding_prices WHERE ticker=? AND identifier=?',(ticker,identifier)).fetchone()
  if not existing:c.execute("INSERT INTO sector_holding_prices VALUES(?,?,'TRY_IDENTITY',NULL,?,?)",(ticker,identifier,now,now))
  elif existing['status']=='OK' and existing['next_attempt']<=now:c.execute("UPDATE sector_holding_prices SET status='TRY_HISTORY',next_attempt=? WHERE ticker=? AND identifier=?",(now,ticker,identifier))
  elif existing['status'] not in ('OK','TRY_IDENTITY','TRY_HISTORY') and existing['next_attempt']<=now:c.execute("UPDATE sector_holding_prices SET status='TRY_IDENTITY',next_attempt=? WHERE ticker=? AND identifier=?",(now,ticker,identifier))

def request_benchmark_holdings(connect,uid,symbol,limit=20):
 """Queue only configured, verified public benchmarks. No broker operations."""
 allowed={s for items in PROXIES.values() for s,_ in items}
 with connect() as c:allowed.update(r['symbol'] for r in c.execute("SELECT symbol FROM sector_benchmarks WHERE region='Europa' AND status='VERIFIED' AND proof_source='EODHD instrumentsøgning · europæisk fond'"))
 if not isinstance(symbol,str) or symbol not in allowed:raise ValueError('Ukendt sektorfond')
 if type(limit) is not int or limit not in (20,30,50):raise ValueError('Ugyldigt antal')
 now=time.time()
 with connect() as c:
  benchmark=c.execute('SELECT status,updated,region,exchange FROM sector_benchmarks WHERE symbol=?',(symbol,)).fetchone()
  if not benchmark or benchmark['status']!='VERIFIED' or not 0<=now-benchmark['updated']<=7*86400:return {'status':'UNVERIFIED_BENCHMARK'}
  row=c.execute('SELECT status,updated,next_attempt,payload FROM sector_benchmark_holdings WHERE symbol=?',(symbol,)).fetchone()
  if row and row['status']=='OK' and row['payload'] and symbol in {s for s,_ in PROXIES['USA']}:
   try:_queue_holding_prices(c,json.loads(row['payload']).get('rows',[]),limit,now)
   except (TypeError,ValueError,AttributeError):pass
  if row and (row['status'] in ('PENDING','TRY_TOP10','TRY_ISSUER','TRY_ISHARES','TRY_ISHARES_EU') or row['status']=='OK' and now-row['updated']<86400 or row['status'] not in ('OK','PENDING','TRY_TOP10','TRY_ISSUER','TRY_ISHARES','TRY_ISHARES_EU') and row['next_attempt']>now):return {'status':row['status'],'updated':row['updated']}
  status='TRY_ISSUER' if symbol in {s for s,_ in PROXIES['USA']} else 'TRY_ISHARES' if symbol in {s for s,_ in PROXIES['Globalt']}|{'EUFN.US'} else 'TRY_ISHARES_EU' if benchmark['region']=='Europa' and benchmark['exchange']=='XETRA' else 'PENDING'
  c.execute('INSERT OR REPLACE INTO sector_benchmark_holdings VALUES(?,?,?,?,?)',(symbol,None,status,now,now))
 return {'status':status,'updated':now}

def _holding_rows(payload):
 if not isinstance(payload,(dict,list)):return []
 if isinstance(payload,dict):
  if isinstance(payload.get('ETF_Data'),dict):payload=payload['ETF_Data']
  for key in ('Holdings','Top_10_Holdings'):
   if isinstance(payload.get(key),(dict,list)):payload=payload[key];break
 rows=list(payload.values()) if isinstance(payload,dict) else payload
 result=[];seen=set()
 for row in rows:
  if not isinstance(row,dict):continue
  code=row.get('Code');name=row.get('Name');exchange=row.get('Exchange');weight=_num(row.get('Assets_%'))
  if not isinstance(code,str) or not code.strip() or not isinstance(name,str) or not name.strip() or weight is None or not 0<=weight<=100:continue
  identity=(code.casefold(),str(exchange or '').casefold())
  if identity in seen:continue
  seen.add(identity);result.append({'ticker':code[:40],'name':name[:200],'exchange':exchange[:40] if isinstance(exchange,str) else None,'weight':weight})
 return sorted(result,key=lambda r:(-r['weight'],r['ticker']))

def _holding_changes(series):
 if len(series)<2:return {}
 end=series[-1];end_date=datetime.strptime(end['date'],'%Y-%m-%d').date();result={}
 for key,days in [('1',1),('7',7),('30',30),('90',90),('365',365)]:
  start=series[-2] if key=='1' else next((p for p in reversed(series[:-1]) if datetime.strptime(p['date'],'%Y-%m-%d').date()<=end_date-timedelta(days=days)),None)
  if start:result[key]={'value':(end['close']/start['close']-1)*100,'from':start['date'],'to':end['date']}
 return result

def _refresh_holding_price(connect,item,now):
 ticker=item['ticker'];identifier=item['identifier'];phase=item['status'];client=_client(connect,0)
 if phase=='TRY_IDENTITY':
  response=client._http(HTTP_BASE,'/search/'+quote(ticker,safe=''),{'fmt':'json','limit':'50'})
  rows=response.get('payload') if response['status']=='OK' else []
  valid=[]
  for row in rows if isinstance(rows,list) else []:
   if not isinstance(row,dict):continue
   code=str(row.get('Code') or '').upper();code=ticker if code==ticker+'.US' else code;exchange=str(row.get('Exchange') or '').upper();isin=str(row.get('ISIN') or row.get('Isin') or row.get('isin') or '').upper();kind=str(row.get('Type') or '').upper()
   if code==ticker and exchange in ('US','NYSE','NASDAQ','NYSE ARCA','NYSEARCA','ARCA','CBOE','BATS') and kind in ('COMMON STOCK','STOCK') and re.fullmatch(r'US[A-Z0-9]{9}[0-9]',isin) and isin[2:11]==identifier:valid.append(row)
  if len(valid)==1:status='TRY_HISTORY';retry=now
  elif response['status'] in ('LOCAL_BUDGET_EXHAUSTED','RATE_LIMIT','NETWORK_OR_RESPONSE_ERROR'):status='TRY_IDENTITY';retry=now+_retry_delay(response['status'])
  else:status=response['status'] if response['status']!='OK' else 'IDENTITY_UNVERIFIED';retry=now+_retry_delay(status)
  payload=None
 else:
  start=(datetime.now(timezone.utc).date()-timedelta(days=410)).isoformat()
  response=client._http(HTTP_BASE,'/eod/'+quote(ticker+'.US',safe=''),{'fmt':'json','period':'d','from':start})
  series=_series(response.get('payload'));status='OK' if len(series)>1 else 'TRY_HISTORY' if response['status'] in ('LOCAL_BUDGET_EXHAUSTED','RATE_LIMIT','NETWORK_OR_RESPONSE_ERROR') else response['status'] if response['status']!='OK' else 'NO_DATA'
  source=response.get('payload');adjusted=isinstance(source,list) and bool(source) and all(_num(r.get('adjusted_close')) is not None and _num(r.get('adjusted_close'))>0 for r in source if isinstance(r,dict))
  payload=json.dumps({'periods':_holding_changes(series),'basis':'justeret' if adjusted else 'ujusteret'}) if status=='OK' else None
  retry=now+(86400 if status=='OK' else _retry_delay(response['status'] if status=='TRY_HISTORY' else status))
 with connect() as c:c.execute('UPDATE sector_holding_prices SET status=?,payload=?,updated=?,next_attempt=? WHERE ticker=? AND identifier=?',(status,payload,now,retry,ticker,identifier))

def refresh_tick(connect):
 """Do at most one low-priority EODHD request per invocation."""
 now=time.time()
 # US sector ETFs publish their actual holdings directly. Fetch only on request.
 with connect() as c:
  issuer=c.execute("SELECT h.*,b.name AS benchmark_name FROM sector_benchmark_holdings h LEFT JOIN sector_benchmarks b ON b.symbol=h.symbol WHERE h.status IN ('TRY_ISSUER','TRY_ISHARES','TRY_ISHARES_EU') AND h.next_attempt<=? ORDER BY h.updated LIMIT 1",(now,)).fetchone()
 if issuer:
  is_ishares=issuer['status'] in ('TRY_ISHARES','TRY_ISHARES_EU')
  try:
   if is_ishares:
    import ishares_holdings
    result=ishares_holdings.fetch_europe(issuer['symbol'],issuer['benchmark_name']) if issuer['status']=='TRY_ISHARES_EU' else ishares_holdings.fetch(issuer['symbol'])
   else:
    import ssga_holdings
    result=ssga_holdings.fetch(issuer['symbol'])
   rows=result['rows']
   payload=json.dumps({'rows':rows[:50],'total_reported':len(rows),'source':'iShares / BlackRock' if is_ishares else 'State Street / SPDR','as_of':result['as_of']})
   status='OK';retry=now+86400
  except (ImportError,AttributeError):
   payload=None;status='ISHARES_MODULE_MISSING' if is_ishares else 'ISSUER_MODULE_MISSING';retry=now+3600
  except ValueError as error:
   value=str(error);payload=None;status=value if re.fullmatch(r'(?:ISHARES|ISSUER)_[A-Z0-9_]+',value) else 'ISSUER_INVALID_RESPONSE';retry=now+3600
  with connect() as c:
   c.execute('INSERT OR REPLACE INTO sector_benchmark_holdings VALUES(?,?,?,?,?)',(issuer['symbol'],payload,status,now,retry))
   if status=='OK':_queue_holding_prices(c,rows,20,now)
  return
 if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1'  or not os.environ.get('ESCAPE_EODHD_API_KEY','').strip():
  candidate=_pluto_candidate(connect,now)
  if candidate and not _reuse_hotwatch_asset(connect,candidate,now):_fetch_pluto(connect,candidate,now)
  return
 # Only the user's selected verified ETF is queried; results are cached.
 with connect() as c:
  pending=c.execute("SELECT * FROM sector_benchmark_holdings WHERE status IN ('PENDING','TRY_TOP10') AND next_attempt<=? ORDER BY updated LIMIT 1",(now,)).fetchone()
 if pending:
  symbol=pending['symbol'];fallback=pending['status']=='TRY_TOP10'
  endpoint='ETF_Data::Top_10_Holdings' if fallback else 'ETF_Data::Holdings'
  response=_client(connect,0)._http(HTTP_BASE,'/fundamentals/'+quote(symbol,safe=''),{'fmt':'json','filter':endpoint})
  rows=_holding_rows(response.get('payload')) if response['status']=='OK' else []
  if rows:status='OK';retry=now+86400;payload=json.dumps({'rows':rows[:50],'total_reported':len(rows),'top10_only':fallback})
  elif response['status'] in ('LOCAL_BUDGET_EXHAUSTED','RATE_LIMIT','NETWORK_OR_RESPONSE_ERROR'):
   status=pending['status'];retry=now+_retry_delay(response['status']);payload=None
  elif not fallback:status='TRY_TOP10';retry=now;payload=None
  else:status=response['status'] if response['status']!='OK' else 'NO_DATA';retry=now+_retry_delay(status);payload=None
  with connect() as c:c.execute('INSERT OR REPLACE INTO sector_benchmark_holdings VALUES(?,?,?,?,?)',(symbol,payload,status,now,retry))
  return
 # If ECB reference rates are absent, collect a timestamped EODHD FX quote
 # for each currency actually held. This is separate from trading prices.
 with connect() as c:
  fxrow=c.execute('SELECT source_date,payload FROM fx_snapshots ORDER BY source_date DESC,id DESC LIMIT 1').fetchone()
  try:
   ecb_fresh=bool(fxrow and 0<=(datetime.now(timezone.utc).date()-datetime.fromisoformat(fxrow['source_date']).date()).days<=7)
   ecb_rates=json.loads(fxrow['payload']).get('rates',{}) if ecb_fresh else {}
  except (ValueError,TypeError,AttributeError):ecb_rates={}
  wanted=set()
  for snap in c.execute("SELECT s.payload FROM portfolio_snapshots s JOIN portfolios p ON p.id=s.portfolio_id AND p.user_id=s.user_id WHERE p.active=1 AND p.source='pluto'"):
   try:
    for pos in json.loads(snap['payload']).get('positions',[]):
     code=pos.get('currency')
     if isinstance(code,str) and re.fullmatch(r'[A-Z]{3}',code) and code!='DKK' and not (ecb_rates.get('DKK') and (code=='EUR' or ecb_rates.get(code))):wanted.add(code)
   except (TypeError,ValueError):continue
  for code in sorted(wanted):
   existing=c.execute('SELECT next_attempt FROM sector_fx WHERE currency=?',(code,)).fetchone()
   if not existing or existing['next_attempt']<=now:fx_currency=code;break
  else:fx_currency=None
 if fx_currency:
  result=_client(connect,0).snapshot(fx_currency+'DKK.FOREX')
  rate=_num(result.get('price'));event=result.get('event_time');status=result.get('status','NO_DATA')
  if status!='OK' or not rate or rate<=0 or not event:rate=event=None
  with connect() as c:
   old=c.execute('SELECT rate,event_time FROM sector_fx WHERE currency=?',(fx_currency,)).fetchone()
   if rate is None and old:rate,event=old['rate'],old['event_time']
   c.execute('INSERT OR REPLACE INTO sector_fx VALUES(?,?,?,?,?,?)',(fx_currency,rate,event,status,now,now+(3600 if status=='OK' else 21600)))
  return
 candidate=_pluto_candidate(connect,now)
 if candidate:
  if not _reuse_hotwatch_asset(connect,candidate,now):_fetch_pluto(connect,candidate,now)
  return
 with connect() as c:
  # Only reuse identities already checked by the existing HOT WATCH engine.
  candidates=c.execute('''SELECT l.*,i.isin AS pluto_isin,i.ticker AS pluto_ticker,i.currency AS pluto_currency,i.exchange AS pluto_exchange,i.instrument_type AS pluto_type,i.name AS pluto_name,a.status AS sector_phase,a.symbol AS previous_symbol FROM hw_verified_feed_links l JOIN users u ON u.id=l.user_id AND u.active=1 JOIN sector_instruments i ON i.user_id=l.user_id AND i.asset_id=l.asset_id
    LEFT JOIN sector_assets a ON a.user_id=l.user_id AND a.asset_id=l.asset_id
    WHERE UPPER(COALESCE(i.instrument_type,'')) IN ('CS','ADRC','ADR','COMMON_STOCK','COMMON STOCK','ORDINARY SHARES','STOCK','EQUITY') AND (a.asset_id IS NULL OR a.next_attempt<=? OR a.identity_version!=1 OR (a.source!='Pluto get_asset' AND COALESCE(a.symbol,'')!=l.symbol))
    ORDER BY COALESCE(a.next_attempt,0) LIMIT 1''',(now,)).fetchone()
 if candidates:
  item=dict(candidates);symbol=item['symbol']
  if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',symbol):return
  def same(a,b):return isinstance(a,str) and isinstance(b,str) and bool(a.strip()) and a.strip().casefold()==b.strip().casefold()
  instrument={'asset_id':item['asset_id'],'ticker':item['pluto_ticker'],'currency':item['pluto_currency'],'exchange':item['pluto_exchange'],'isin':item['pluto_isin'],'instrument_type':item['pluto_type'],'name':item['pluto_name']}
  basis=_verified_stock_basis(connect,item['user_id'],instrument,item,now)
  if not basis:
   with connect() as c:c.execute('INSERT OR REPLACE INTO sector_assets(user_id,asset_id,symbol,sector,industry,source,status,updated,next_attempt,identity_version) VALUES(?,?,?,?,?,?,?,?,?,1)',(item['user_id'],item['asset_id'],symbol,None,None,None,'PLUTO_IDENTITY_INCOMPLETE',now,now+86400))
   return
  # Reuse the same verified symbol for EODHD's documented stock screener
  # if the account cannot return Fundamentals or the sector is absent.
  if item.get('sector_phase')=='TRY_EODHD_SCREENER' and item.get('previous_symbol')==symbol:
   code,exchange=symbol.rsplit('.',1)
   filters=json.dumps([['code','=',code],['exchange','=',exchange.lower()]],separators=(',',':'))
   res=_client(connect,item['user_id'])._http(HTTP_BASE,'/screener',{'filters':filters,'limit':'100','fmt':'json'})
   payload=res.get('payload');rows=payload.get('data',[]) if isinstance(payload,dict) else payload if isinstance(payload,list) else []
   allowed={exchange.upper(),str(item['exchange']).upper()}
   if exchange.upper()=='US':allowed.update(('US','USA','NYSE','NASDAQ'))
   complete=not isinstance(payload,dict) or not isinstance(payload.get('count'),int) or payload['count']<=len(rows)
   matches=[r for r in rows if isinstance(r,dict) and str(r.get('code') or '').upper()==code.upper() and str(r.get('exchange') or '').upper() in allowed]
   raw=matches[0].get('sector') if complete and len(matches)==1 else None
   sector=SECTORS.get(raw.casefold().strip(),raw.strip()) if isinstance(raw,str) and raw.strip() and raw.strip().lower() not in ('none','n/a') else None
   industry=matches[0].get('industry') if sector and isinstance(matches[0].get('industry'),str) else None
   status='OK' if sector else res['status'] if res['status']!='OK' else 'SECTOR_NOT_RETURNED'
   with connect() as c:c.execute('INSERT OR REPLACE INTO sector_assets(user_id,asset_id,symbol,sector,industry,source,status,updated,next_attempt,identity_version,original_sector) VALUES(?,?,?,?,?,?,?,?,?,1,?)',(item['user_id'],item['asset_id'],symbol,sector,industry,'EODHD stock screener' if sector else None,status,now,now+(7*86400 if sector else _retry_delay(status)),raw if sector else None))
   return
  res=_client(connect,item['user_id'])._http(HTTP_BASE,'/fundamentals/'+quote(symbol,safe=''),{'fmt':'json','filter':'General'})
  general=res.get('payload');general=general.get('General',general) if isinstance(general,dict) else {}
  code=str(general.get('Code') or '').upper(); expected=symbol.rsplit('.',1)[0].upper()
  isin=str(general.get('ISIN') or '').upper(); currency=str(general.get('CurrencyCode') or '').upper()
  source_exchange=str(general.get('Exchange') or '').upper().strip()
  source_type=re.sub(r'[^A-Z0-9]','',str(general.get('Type') or '').upper())
  conflicting_type=source_type in ('ETF','ETP','FUND','MUTUALFUND','CRYPTO','CURRENCY')
  exchange_conflict=bool(source_exchange and source_exchange not in (item['exchange'].upper(),'US','USA'))
  identity=(code==expected and (not isin or isin==item['isin'].upper()) and (not currency or currency==item['currency'].upper()) and not exchange_conflict and not conflicting_type)
  raw=general.get('Sector');sector=SECTORS.get(raw.casefold().strip(),raw.strip()) if identity and isinstance(raw,str) and raw.strip() and raw.strip().lower() not in ('none','n/a') else None
  industry=general.get('Industry') if sector and isinstance(general.get('Industry'),str) else None
  explicit_conflict=res['status']=='OK' and bool(general) and not identity
  status='OK' if sector else 'IDENTITY_OR_SECTOR_UNKNOWN' if explicit_conflict else 'TRY_EODHD_SCREENER' if res['status'] not in ('LOCAL_BUDGET_EXHAUSTED','RATE_LIMIT','NETWORK_OR_RESPONSE_ERROR') else res['status']
  next_attempt=now if status=='TRY_EODHD_SCREENER' else now+(7*86400 if sector else _retry_delay(status))
  with connect() as c:c.execute('INSERT OR REPLACE INTO sector_assets(user_id,asset_id,symbol,sector,industry,source,status,updated,next_attempt,identity_version,original_sector) VALUES(?,?,?,?,?,?,?,?,?,1,?)',(item['user_id'],item['asset_id'],symbol,sector,industry,'EODHD fundamentals' if sector else None,status,now,next_attempt,raw if sector else None))
  return
 with connect() as c:
  fund=c.execute('''SELECT i.*,l.symbol,l.isin AS linked_isin,l.ticker AS linked_ticker,l.currency AS linked_currency,l.exchange AS linked_exchange,f.status AS phase,f.symbol AS phase_symbol,f.next_attempt AS due
   FROM sector_instruments i JOIN hw_verified_feed_links l ON l.user_id=i.user_id AND l.asset_id=i.asset_id
   LEFT JOIN sector_fund_exposure f ON f.user_id=i.user_id AND f.asset_id=i.asset_id
   WHERE UPPER(COALESCE(i.instrument_type,'')) IN ('ETF','ETP','FUND','MUTUALFUND','INVESTMENTFUND') AND (f.asset_id IS NULL OR f.next_attempt<=? OR f.symbol!=l.symbol) LIMIT 1''',(now,)).fetchone()
 if fund:
  item=dict(fund);symbol=item['symbol'];uid=item['user_id'];aid=item['asset_id']
  def same(a,b):return isinstance(a,str) and isinstance(b,str) and bool(a.strip()) and a.strip().casefold()==b.strip().casefold()
  link={'asset_id':aid,'isin':item['linked_isin'],'ticker':item['linked_ticker'],'currency':item['linked_currency'],'exchange':item['linked_exchange'],'symbol':symbol}
  matched=bool(_verified_stock_basis(connect,uid,item,link,now))
  payload=None;status='PLUTO_IDENTITY_INCOMPLETE';retry=now+86400
  if matched and item.get('phase')=='IDENTITY_VERIFIED' and item.get('phase_symbol')==symbol:
   response=_client(connect,uid)._http(HTTP_BASE,'/fundamentals/'+quote(symbol,safe=''),{'fmt':'json','filter':'ETF_Data'})
   part=response.get('payload');part=part.get('ETF_Data',part) if isinstance(part,dict) else {}
   weights=part.get('Sector_Weights');allocation=part.get('Asset_Allocation');entries=[];equity=None
   if isinstance(weights,dict):
    for name,raw in weights.items():
     pct=_num(raw.get('Equity_%')) if isinstance(raw,dict) else None
     if isinstance(name,str) and pct is not None and 0<=pct<=100:entries.append({'sector':SECTORS.get(name.casefold(),name),'original':name,'percent':pct})
   if isinstance(allocation,dict):
    stock=[_num(v.get('Net_Assets_%')) for k,v in allocation.items() if isinstance(v,dict) and str(k).casefold() in ('stock us','stock non-us')]
    if len(stock)==2 and all(x is not None and x>=0 for x in stock) and 0<=sum(stock)<=100:equity=sum(stock)
   total=sum(x['percent'] for x in entries)
   if entries and 0<total<=100.5:
    payload=json.dumps({'weights':entries,'equity_percent':equity});status='OK';retry=now+7*86400
   else:status=response['status'] if response['status']!='OK' else 'FUND_WEIGHTS_MISSING'
  elif matched:
   response=_client(connect,uid)._http(HTTP_BASE,'/fundamentals/'+quote(symbol,safe=''),{'fmt':'json','filter':'General'})
   g=response.get('payload');g=g.get('General',g) if isinstance(g,dict) else {}
   kind=str(g.get('Type') or '').upper();gisin=g.get('ISIN');gc=g.get('CurrencyCode');gx=g.get('Exchange')
   valid=(str(g.get('Code') or '').upper()==symbol.rsplit('.',1)[0].upper() and (not gisin or same(gisin,link['isin'])) and (not gc or same(gc,link['currency'])) and (not gx or same(gx,link['exchange']) or str(gx).upper() in ('US','USA')) and (not kind or kind in ('ETF','ETP','FUND')))
   status='IDENTITY_VERIFIED' if valid else response['status'] if response['status']!='OK' else 'IDENTITY_OR_SECTOR_UNKNOWN'
   if valid:retry=now
  with connect() as c:c.execute('INSERT OR REPLACE INTO sector_fund_exposure VALUES(?,?,?,?,?,?,?)',(uid,aid,symbol,payload,status,now,retry))
  return
 with connect() as c:
  dynamic=[(r['symbol'],r['sector']) for r in c.execute("SELECT symbol,sector FROM sector_benchmarks WHERE region='Europa' AND status='VERIFIED' AND proof_source='EODHD instrumentsøgning · europæisk fond' AND updated>=?",(now-7*86400,))]
  configured={s for s,_ in PROXIES.get('Europa',[])}
  target=None
  for region,items in PROXIES.items():
   for symbol,sector in list(items)+([(s,n) for s,n in dynamic if s not in configured] if region=='Europa' else []):
    row=c.execute('SELECT next_attempt FROM sector_market WHERE symbol=?',(symbol,)).fetchone()
    if not row or row['next_attempt']<=now:target=(region,symbol,sector);break
   if target:break
  query=c.execute('SELECT * FROM sector_europe_queries WHERE next_attempt<=? ORDER BY next_attempt,query LIMIT 1',(now,)).fetchone() if target is None else None
  discovery=c.execute('SELECT * FROM sector_europe_discovery WHERE next_attempt<=? ORDER BY next_attempt,code LIMIT 1',(now,)).fetchone() if target is None and not query else None
 if target is None:
  with connect() as c:price=c.execute("SELECT * FROM sector_holding_prices WHERE status IN ('TRY_IDENTITY','TRY_HISTORY') AND next_attempt<=? ORDER BY updated,ticker LIMIT 1",(now,)).fetchone()
  if price:_refresh_holding_price(connect,price,now);return
 if target is None and query:
  term=query['query'];result=_client(connect,0)._http(HTTP_BASE,'/search/'+quote(term,safe=''),{'fmt':'json','limit':'100'})
  rows=result.get('payload') if result['status']=='OK' else []
  candidates={}
  for row in rows if isinstance(rows,list) else []:
   if not isinstance(row,dict):continue
   code=str(row.get('Code') or '').upper()
   if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{0,15}',code):continue
   label=_europe_discovery(row,code)
   if label:candidates.setdefault(code,[]).append((row,label))
  configured={s for items in PROXIES.values() for s,_ in items}
  with connect() as c:
   for code,matches in candidates.items():
    symbol=code+'.XETRA'
    if symbol in configured or len(matches)!=1:continue
    row,label=matches[0]
    existing=c.execute('SELECT status,proof_source,updated FROM sector_benchmarks WHERE symbol=?',(symbol,)).fetchone()
    if existing and existing['status']=='VERIFIED' and existing['proof_source']!='EODHD instrumentsøgning · europæisk fond':continue
    c.execute('INSERT OR REPLACE INTO sector_benchmarks(symbol,region,sector,name,currency,exchange,status,updated,next_attempt,proof_source) VALUES(?,?,?,?,?,?,?,?,?,?)',(symbol,'Europa',label,row.get('Name'),'EUR','XETRA','VERIFIED',now,now+7*86400,'EODHD instrumentsøgning · europæisk fond'))
   status='OK' if result['status']=='OK' else result['status']
   c.execute('INSERT OR REPLACE INTO sector_europe_queries VALUES(?,?,?,?)',(term,status,now,now+(7*86400 if status=='OK' else _retry_delay(status))))
  return
 if target is None:
  if not discovery:return
  code=discovery['code'];result=_client(connect,0)._http(HTTP_BASE,'/search/'+quote(code,safe=''),{'fmt':'json','limit':'50'})
  rows=result.get('payload') if result['status']=='OK' else []
  candidates=[(r,_europe_discovery(r,code)) for r in rows if isinstance(r,dict)] if isinstance(rows,list) else []
  candidates=[(r,label) for r,label in candidates if label]
  with connect() as c:
   if len(candidates)==1:
    row,label=candidates[0];symbol=code+'.XETRA'
    c.execute('INSERT OR REPLACE INTO sector_benchmarks(symbol,region,sector,name,currency,exchange,status,updated,next_attempt,proof_source) VALUES(?,?,?,?,?,?,?,?,?,?)',(symbol,'Europa',label,row.get('Name'),'EUR','XETRA','VERIFIED',now,now+7*86400,'EODHD instrumentsøgning · europæisk fond'))
   status='OK' if len(candidates)==1 else result['status'] if result['status']!='OK' else 'NOT_FOUND'
   c.execute('INSERT OR REPLACE INTO sector_europe_discovery VALUES(?,?,?,?)',(code,status,now,now+(7*86400 if result['status']=='OK' else _retry_delay(status))))
  return
 region,symbol,sector=target
 with connect() as c:benchmark=c.execute('SELECT * FROM sector_benchmarks WHERE symbol=?',(symbol,)).fetchone()
 # The eleven US tickers are the issuer's published S&P 500 sector funds.
 # The EODHD history still has to be fetched and validated independently.
 issuer_source='https://www.ssga.com/us/en/individual/capabilities/equities/sector-investing/gics-sector-and-industry-map'
 issuer_verified=region=='USA' and (symbol,sector) in PROXIES['USA']
 if issuer_verified and (not benchmark or benchmark['proof_source']!=issuer_source or benchmark['next_attempt']<=now):
  with connect() as c:
   c.execute('INSERT OR REPLACE INTO sector_benchmarks(symbol,region,sector,name,currency,exchange,status,updated,next_attempt,proof_source) VALUES(?,?,?,?,?,?,?,?,?,?)',(symbol,region,sector,'Select Sector SPDR · S&P 500',None,None,'VERIFIED',now,now+7*86400,issuer_source))
   benchmark=c.execute('SELECT * FROM sector_benchmarks WHERE symbol=?',(symbol,)).fetchone()
 if not benchmark or benchmark['status']!='VERIFIED' or benchmark['next_attempt']<=now:
  if benchmark and benchmark['next_attempt']>now:
   with connect() as c:c.execute('INSERT OR REPLACE INTO sector_market(symbol,region,sector,payload,status,updated,next_attempt) VALUES(?,?,?,?,?,?,?)',(symbol,region,sector,None,'UNVERIFIED_BENCHMARK',now,benchmark['next_attempt']))
   return
  # Search returns the ticker, name, type and currency even on plans that
  # do not include ETF Fundamentals. Verify once and reuse the result.
  use_fundamentals=bool(benchmark and benchmark['status']=='TRY_FUNDAMENTALS')
  if use_fundamentals:
   result=_client(connect,0)._http(HTTP_BASE,'/fundamentals/'+quote(symbol,safe=''),{'fmt':'json','filter':'General'})
   general=result.get('payload');general=general.get('General',general) if isinstance(general,dict) else {}
   verified=result['status']=='OK' and _benchmark_identity(region,sector,symbol,general)
   status='VERIFIED' if verified else result['status'] if result['status']!='OK' else 'IDENTITY_UNVERIFIED'
   retry=now+(7*86400 if verified else _retry_delay(status))
   source='EODHD fundamentals' if verified else None
  else:
   code,market_code=symbol.rsplit('.',1)
   result=_client(connect,0)._http(HTTP_BASE,'/search/'+quote(code,safe=''),{'fmt':'json','limit':'50'})
   rows=result.get('payload');rows=rows if isinstance(rows,list) else []
   candidates=[]
   for row in rows:
    if not isinstance(row,dict):continue
    raw_code=str(row.get('Code') or '').upper();exchange=str(row.get('Exchange') or '').upper()
    if raw_code==symbol.upper():raw_code=code.upper()
    if raw_code!=code.upper() or exchange!=market_code.upper():continue
    candidate={'Code':raw_code,'Name':row.get('Name'),'Exchange':exchange,'CurrencyCode':row.get('Currency'),'Type':row.get('Type')}
    if _benchmark_identity(region,sector,symbol,candidate):candidates.append(candidate)
   verified=len(candidates)==1
   general=candidates[0] if verified else {}
   status='VERIFIED' if verified else 'TRY_FUNDAMENTALS' if result['status'] not in ('LOCAL_BUDGET_EXHAUSTED','RATE_LIMIT','NETWORK_OR_RESPONSE_ERROR') else result['status']
   retry=now+7*86400 if verified else now if status=='TRY_FUNDAMENTALS' else now+_retry_delay(status)
   source='EODHD instrumentsøgning' if verified else None
  with connect() as c:
   c.execute('INSERT OR REPLACE INTO sector_benchmarks(symbol,region,sector,name,currency,exchange,status,updated,next_attempt,proof_source) VALUES(?,?,?,?,?,?,?,?,?,?)',(symbol,region,sector,general.get('Name'),general.get('CurrencyCode'),general.get('Exchange'),status,now,retry,source))
   if not verified:c.execute('INSERT OR REPLACE INTO sector_market(symbol,region,sector,payload,status,updated,next_attempt) VALUES(?,?,?,?,?,?,?)',(symbol,region,sector,None,'UNVERIFIED_BENCHMARK',now,retry))
  return
 start=(datetime.now(timezone.utc).date()-timedelta(days=410)).isoformat()
 res=_client(connect,0)._http(HTTP_BASE,'/eod/'+quote(symbol,safe=''),{'fmt':'json','period':'d','from':start})
 series=_series(res.get('payload'));status='OK' if series else res['status'] if res['status']!='OK' else 'NO_DATA'
 with connect() as c:
  old=c.execute('SELECT payload FROM sector_market WHERE symbol=?',(symbol,)).fetchone()
  payload=json.dumps(series) if series else old['payload'] if old else None
  c.execute('INSERT OR REPLACE INTO sector_market(symbol,region,sector,payload,status,updated,next_attempt) VALUES(?,?,?,?,?,?,?)',(symbol,region,sector,payload,status,now,now+(3600 if series else _retry_delay(status))))
  if series:
   rows=res.get('payload') if isinstance(res.get('payload'),list) else []
   adjusted=bool(rows) and all(_num(row.get('adjusted_close')) is not None and _num(row.get('adjusted_close'))>0 for row in rows if isinstance(row,dict))
   c.execute('UPDATE sector_market SET price_basis=? WHERE symbol=?',('adjusted_close' if adjusted else 'close',symbol))

def read(connect,uid):
 import portfolios,portfolio_data,dashboard_projection
 with connect() as c:
  owned=portfolios.list_owned(c,uid);snapshots=portfolio_data.snapshots(c,uid)
  assets={r['asset_id']:dict(r) for r in c.execute('SELECT * FROM sector_assets WHERE user_id=? AND identity_version=1',(uid,))}
  instruments={r['asset_id']:dict(r) for r in c.execute('SELECT * FROM sector_instruments WHERE user_id=?',(uid,))}
  funds={r['asset_id']:dict(r) for r in c.execute('SELECT * FROM sector_fund_exposure WHERE user_id=? AND status=\'OK\'',(uid,))}
  links={r['asset_id']:dict(r) for r in c.execute('SELECT * FROM hw_verified_feed_links WHERE user_id=?',(uid,))}
  markets=[dict(r) for r in c.execute('SELECT m.*,b.status AS benchmark_status,b.updated AS benchmark_updated,b.proof_source AS benchmark_source,b.name AS benchmark_name,b.currency AS benchmark_currency,b.exchange AS benchmark_exchange FROM sector_market m LEFT JOIN sector_benchmarks b ON b.symbol=m.symbol')]
  fx_quotes=[dict(r) for r in c.execute('SELECT currency,rate,event_time,status FROM sector_fx')]
  benchmark_holdings=[dict(r) for r in c.execute('SELECT * FROM sector_benchmark_holdings')]
  holding_prices=[dict(r) for r in c.execute('SELECT ticker,identifier,status,payload FROM sector_holding_prices')]
  history=[dict(r) for r in c.execute('SELECT portfolio_id,observed,payload FROM sector_history WHERE user_id=? AND bucket>=? ORDER BY bucket',(uid,int((time.time()-366*86400)//14400)))]
  fx=c.execute('SELECT payload FROM fx_snapshots ORDER BY source_date DESC,id DESC LIMIT 1').fetchone()
 # Show every configured fund while it is waiting for its first lookup.
 # Do not invent prices: the worker fills these entries only from EODHD.
 known={r['symbol'] for r in markets}
 for region,items in PROXIES.items():
  for symbol,sector in items:
   if symbol not in known:
    markets.append({'symbol':symbol,'region':region,'sector':sector,'payload':None,'status':'PENDING','benchmark_status':None,'benchmark_updated':None,'benchmark_source':None,'benchmark_name':None,'benchmark_currency':None,'benchmark_exchange':None})
 dashboard=dashboard_projection.build(connect,uid,owned,snapshots)
 # Preserve active Pluto scopes without a snapshot so allocation cannot appear complete.
 present={a['id'] for a in dashboard['accounts']}
 for p in owned:
  if p.get('source')=='pluto' and p.get('active') and p['id'] not in present:
   dashboard['accounts'].append({'id':p['id'],'name':p.get('name') or 'Depot','kind':p.get('kind'),
    'parent_external_id':p.get('parent_external_id'),'value':None,'as_of':None,'snapshot_at':None,
    'failed':True,'snapshot_missing':True})
 for account in dashboard['accounts']:
  portfolio=next((p for p in owned if p['id']==account['id']),{})
  account['external_id']=portfolio.get('external_id')
  snapshot=snapshots.get(str(account['id'])) or {}
  value=(snapshot.get('data') or {}).get('value') or {}
  account['reported_result']=value.get('reported_result')
  data=snapshot.get('data') or {}
  errors=data.get('errors')
  cash=data.get('accounts')
  cash_ok=(bool(snapshot) and not snapshot.get('last_error') and isinstance(cash,list)
           and isinstance(errors,list) and not any(isinstance(e,str) and (e.startswith('accounts:') or e.startswith('Collection-kontanter:')) for e in errors))
  account['cash_accounts']=[row.get('balance') for row in cash if isinstance(row,dict)] if cash_ok else []
  account['cash_status']='available' if cash_ok and len(account['cash_accounts'])==len(cash) else 'unavailable'
 for row in dashboard['positions']:
  aid=row.get('asset_id');instrument=instruments.get(aid,{});mismatch=any(row.get(k) and instrument.get(k) and str(row[k]).casefold()!=str(instrument[k]).casefold() for k in ('ticker','currency'));a=assets.get(aid,{}) if instrument.get('status')=='OK' and not mismatch else {};fund=funds.get(aid);link=links.get(aid,{})
  if mismatch:a={'status':'IDENTITY_EXPIRED'}
  identity_current=bool(link and _verified_stock_basis(connect,uid,instrument,link,time.time())) if _kind(instrument.get('instrument_type'))=='stock' else bool(link and _verified_stock_basis(connect,uid,instrument,link,time.time()))
  if a.get('source') in ('EODHD fundamentals','EODHD stock screener') and (not identity_current or a.get('symbol')!=link.get('symbol')):a={'status':'IDENTITY_EXPIRED'}
  valid_fund=bool(fund and not mismatch and fund.get('payload') and 0<=time.time()-fund['updated']<=7*86400 and instrument.get('status')=='OK' and _kind(instrument.get('instrument_type'))=='fund' and fund['symbol']==link.get('symbol') and _verified_stock_basis(connect,uid,instrument,link,time.time()))
  row['sector_intelligence']={'sector':a.get('sector'),'industry':a.get('industry'),'original_sector':a.get('original_sector'),'source':a.get('source'),'status':a.get('status') or instrument.get('status','AFVENTER'),'updated':a.get('updated'),'instrument_type':instrument.get('instrument_type'),'isin':instrument.get('isin'),'exchange':instrument.get('exchange'),'fund_exposure':{**json.loads(fund['payload']),'observed':fund['updated'],'symbol':fund['symbol']} if valid_fund else None}
 for r in markets:
  saved=r.pop('payload')
  verified=r.get('benchmark_status')=='VERIFIED' and r.get('benchmark_updated') is not None and 0<=time.time()-r['benchmark_updated']<=7*86400
  r['series']=json.loads(saved or '[]') if verified else []
  if not verified and r.get('status')!='PENDING':r['status']='UNVERIFIED_BENCHMARK'
 for r in benchmark_holdings:r['holdings']=json.loads(r.pop('payload') or '{}')
 for r in holding_prices:r['price']=json.loads(r.pop('payload') or '{}')
 for r in history:r['positions']=json.loads(r.pop('payload'))
 return {'dashboard':dashboard,'markets':markets,'history':history,'benchmark_holdings':benchmark_holdings,'holding_prices':holding_prices,'fx_quotes':fx_quotes,'fx':json.loads(fx['payload']) if fx else None,'regions':list(PROXIES)}
