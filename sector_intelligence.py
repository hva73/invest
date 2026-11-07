"""Read-only sector data; background collection never places or changes orders."""
import json, math, os, re, time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from eodhd_feeds import EODHDFeeds, HTTP_BASE
from hotwatch_adapters import reserve

# ETFs are comparison instruments, not a measure of fund flows or an entire region.
PROXIES = {
 'USA': [('XLK.US','Teknologi'),('XLV.US','Sundhed'),('XLF.US','Finans'),('XLI.US','Industri'),('XLE.US','Energi'),('XLY.US','Forbrug, cyklisk'),('XLP.US','Forbrug, stabilt'),('XLB.US','Materialer'),('XLU.US','Forsyning'),('XLRE.US','Ejendomme'),('XLC.US','Kommunikation')],
 'Globalt': [('IXN.US','Teknologi'),('IXJ.US','Sundhed'),('IXG.US','Finans'),('EXI.US','Industri'),('IXC.US','Energi'),('RXI.US','Forbrug, cyklisk'),('KXI.US','Forbrug, stabilt'),('MXI.US','Materialer'),('JXI.US','Forsyning'),('IXP.US','Kommunikation')],
 'Europa': [('EUFN.US','Finans')], 'Asien': []}
SECTORS={'information technology':'Teknologi','technology':'Teknologi','health care':'Sundhed','healthcare':'Sundhed','financial services':'Finans','financials':'Finans','industrials':'Industri','energy':'Energi','consumer discretionary':'Forbrug, cyklisk','consumer cyclicals':'Forbrug, cyklisk','consumer cyclical':'Forbrug, cyklisk','consumer staples':'Forbrug, stabilt','consumer defensive':'Forbrug, stabilt','materials':'Materialer','basic materials':'Materialer','utilities':'Forsyning','real estate':'Ejendomme','communication services':'Kommunikation'}

def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS sector_assets(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,symbol TEXT,sector TEXT,industry TEXT,source TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 if 'identity_version' not in {r[1] for r in c.execute('PRAGMA table_info(sector_assets)')}:c.execute('ALTER TABLE sector_assets ADD COLUMN identity_version INTEGER NOT NULL DEFAULT 0')
 if 'original_sector' not in {r[1] for r in c.execute('PRAGMA table_info(sector_assets)')}:c.execute('ALTER TABLE sector_assets ADD COLUMN original_sector TEXT')
 c.execute('CREATE TABLE IF NOT EXISTS sector_instruments(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,ticker TEXT,currency TEXT,exchange TEXT,isin TEXT,instrument_type TEXT,name TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 c.execute('CREATE TABLE IF NOT EXISTS sector_fx(currency TEXT PRIMARY KEY, rate REAL, event_time TEXT, status TEXT NOT NULL, updated REAL NOT NULL, next_attempt REAL NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS sector_fund_exposure(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,symbol TEXT NOT NULL,payload TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 c.execute('CREATE TABLE IF NOT EXISTS sector_benchmarks(symbol TEXT PRIMARY KEY,region TEXT NOT NULL,sector TEXT NOT NULL,name TEXT,currency TEXT,exchange TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS sector_market(symbol TEXT PRIMARY KEY,region TEXT NOT NULL,sector TEXT NOT NULL,payload TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL)')
 if 'price_basis' not in {r[1] for r in c.execute('PRAGMA table_info(sector_market)')}:c.execute('ALTER TABLE sector_market ADD COLUMN price_basis TEXT')
 c.execute('CREATE TABLE IF NOT EXISTS sector_history(user_id INTEGER NOT NULL,portfolio_id INTEGER NOT NULL,bucket INTEGER NOT NULL,observed TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(user_id,portfolio_id,bucket))')

def capture(c,uid,pid,payload):
 if not payload.get('positions_complete') or not payload.get('observed'):return
 try:bucket=int(datetime.fromisoformat(payload['observed'].replace('Z','+00:00')).timestamp())//14400
 except (ValueError,TypeError,AttributeError):return
 rows=[r for r in payload.get('positions',[]) if r.get('kind')!='collection' and r.get('asset_id')]
 c.execute('INSERT OR REPLACE INTO sector_history VALUES(?,?,?,?,?)',(uid,pid,bucket,payload['observed'],json.dumps(rows,separators=(',',':'))))

def _client(connect,uid):
 return EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),reserve=lambda:reserve(connect,uid,'eodhd',purpose='sector'))

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
   changed=old and any(pos.get(key) and old.get(key) and str(pos[key]).casefold()!=str(old[key]).casefold() for key in ('ticker','currency'))
   if aid and pos.get('kind')!='collection' and (old is None or old['next_attempt']<=now or changed):return snap['user_id'],aid,pos.get('ticker')
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
  c.execute('INSERT OR REPLACE INTO sector_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,aid,instrument.get('ticker'),instrument.get('currency'),instrument.get('exchange'),instrument.get('isin'),instrument.get('instrument_type'),instrument.get('name'),status,now,now+(7*86400 if status=='OK' else 86400)))
  if sector:c.execute('INSERT OR REPLACE INTO sector_assets(user_id,asset_id,symbol,sector,industry,source,status,updated,next_attempt,identity_version,original_sector) VALUES(?,?,?,?,?,?,?,?,?,1,?)',(uid,aid,None,sector,industry,'Pluto get_asset','OK',now,now+7*86400,raw_sector))

def _benchmark_identity(region,sector,symbol,general):
 if not isinstance(general,dict):return False
 code=str(general.get('Code') or '').upper();name=str(general.get('Name') or '');upper=name.upper()
 exchange=str(general.get('Exchange') or '').upper().strip();currency=str(general.get('CurrencyCode') or '').upper()
 typ=re.sub(r'[^A-Z0-9]','',str(general.get('Type') or '').upper())
 if code!=symbol.rsplit('.',1)[0] or currency!='USD' or typ not in ('ETF','ETP','FUND') or exchange not in ('NYSE ARCA','NYSEARCA','NASDAQ','NYSE','BATS','CBOE','ARCA'):return False
 if region=='USA' and ('SELECT SECTOR' not in upper or 'SPDR' not in upper):return False
 if region=='Globalt' and ('GLOBAL' not in upper or 'ISHARES' not in upper):return False
 if region=='Europa' and ('EUROPE' not in upper or 'FINANCIAL' not in upper):return False
 terms={'Teknologi':('TECH',),'Sundhed':('HEALTH',),'Finans':('FINANCIAL',),'Industri':('INDUSTRIAL',),'Energi':('ENERGY',),'Forbrug, cyklisk':('CONSUMER DISCRETIONARY','CONSUMER CYCLICAL'),'Forbrug, stabilt':('CONSUMER STAPLES','CONSUMER DEFENSIVE'),'Materialer':('MATERIAL',),'Forsyning':('UTILIT',),'Ejendomme':('REAL ESTATE',),'Kommunikation':('COMMUNICATION','TELECOM')}
 return any(word in upper for word in terms.get(sector,()))

def refresh_tick(connect):
 """Do at most one low-priority EODHD request per invocation."""
 now=time.time()
 if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1' or not os.environ.get('ESCAPE_EODHD_API_KEY','').strip():
  candidate=_pluto_candidate(connect,now)
  if candidate:_fetch_pluto(connect,candidate,now)
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
  _fetch_pluto(connect,candidate,now);return
 with connect() as c:
  # Only reuse identities already checked by the existing HOT WATCH engine.
  candidates=c.execute('''SELECT l.*,i.isin AS pluto_isin,i.ticker AS pluto_ticker,i.currency AS pluto_currency,i.exchange AS pluto_exchange,i.instrument_type AS pluto_type,i.name AS pluto_name FROM hw_verified_feed_links l JOIN users u ON u.id=l.user_id AND u.active=1 JOIN sector_instruments i ON i.user_id=l.user_id AND i.asset_id=l.asset_id
    LEFT JOIN sector_assets a ON a.user_id=l.user_id AND a.asset_id=l.asset_id
    WHERE l.verified_epoch BETWEEN ? AND ? AND UPPER(COALESCE(i.instrument_type,'')) IN ('CS','ADRC','ADR','COMMON_STOCK','COMMON STOCK','ORDINARY SHARES','STOCK','EQUITY') AND (a.asset_id IS NULL OR a.next_attempt<=? OR a.identity_version!=1 OR (a.source!='Pluto get_asset' AND COALESCE(a.symbol,'')!=l.symbol))
    ORDER BY COALESCE(a.next_attempt,0) LIMIT 1''',(now-7*86400,now,now)).fetchone()
 if candidates:
  item=dict(candidates);symbol=item['symbol']
  if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',symbol):return
  def same(a,b):return isinstance(a,str) and isinstance(b,str) and bool(a.strip()) and a.strip().casefold()==b.strip().casefold()
  pluto_verified=all(same(item['pluto_'+key],item[key]) for key in ('ticker','currency','exchange','isin'))
  if not pluto_verified:
   with connect() as c:c.execute('INSERT OR REPLACE INTO sector_assets(user_id,asset_id,symbol,sector,industry,source,status,updated,next_attempt,identity_version) VALUES(?,?,?,?,?,?,?,?,?,1)',(item['user_id'],item['asset_id'],symbol,None,None,None,'PLUTO_IDENTITY_INCOMPLETE',now,now+86400))
   return
  res=_client(connect,item['user_id'])._http(HTTP_BASE,'/fundamentals/'+quote(symbol,safe=''),{'fmt':'json','filter':'General'})
  general=res.get('payload');general=general.get('General',general) if isinstance(general,dict) else {}
  code=str(general.get('Code') or '').upper(); expected=symbol.rsplit('.',1)[0].upper()
  isin=str(general.get('ISIN') or '').upper(); currency=str(general.get('CurrencyCode') or '').upper()
  from instrument_resolver import _us_issuer
  names_match=bool(_us_issuer(item.get('pluto_name'))[0] and _us_issuer(item.get('pluto_name'))==_us_issuer(general.get('Name')))
  source_exchange=str(general.get('Exchange') or '').upper().strip()
  source_type=re.sub(r'[^A-Z0-9]','',str(general.get('Type') or '').upper())
  pluto_type=re.sub(r'[^A-Z0-9]','',str(item.get('pluto_type') or '').upper())
  type_match=(source_type in ('COMMONSTOCK','ORDINARYSHARES','STOCK','EQUITY') and pluto_type in ('CS','COMMONSTOCK','ORDINARYSHARES','STOCK','EQUITY')) or (source_type in ('ADR','ADRC') and pluto_type in ('ADR','ADRC'))
  identity=(code==expected and isin==item['isin'].upper() and currency==item['currency'].upper() and source_exchange==item['exchange'].upper() and names_match and type_match)
  raw=general.get('Sector');sector=SECTORS.get(raw.casefold().strip(),raw.strip()) if identity and isinstance(raw,str) and raw.strip() and raw.strip().lower() not in ('none','n/a') else None
  industry=general.get('Industry') if sector and isinstance(general.get('Industry'),str) else None
  status='OK' if sector else res['status'] if res['status']!='OK' else 'IDENTITY_OR_SECTOR_UNKNOWN'
  with connect() as c:c.execute('INSERT OR REPLACE INTO sector_assets(user_id,asset_id,symbol,sector,industry,source,status,updated,next_attempt,identity_version,original_sector) VALUES(?,?,?,?,?,?,?,?,?,1,?)',(item['user_id'],item['asset_id'],symbol,sector,industry,'EODHD fundamentals' if sector else None,status,now,now+(7*86400 if sector else 86400),raw if sector else None))
  return
 with connect() as c:
  fund=c.execute('''SELECT i.*,l.symbol,l.isin AS linked_isin,l.ticker AS linked_ticker,l.currency AS linked_currency,l.exchange AS linked_exchange,f.status AS phase,f.symbol AS phase_symbol,f.next_attempt AS due
   FROM sector_instruments i JOIN hw_verified_feed_links l ON l.user_id=i.user_id AND l.asset_id=i.asset_id
   LEFT JOIN sector_fund_exposure f ON f.user_id=i.user_id AND f.asset_id=i.asset_id
   WHERE UPPER(COALESCE(i.instrument_type,'')) IN ('ETF','ETP','FUND','MUTUALFUND','INVESTMENTFUND') AND l.verified_epoch BETWEEN ? AND ? AND (f.asset_id IS NULL OR f.next_attempt<=? OR f.symbol!=l.symbol) LIMIT 1''',(now-7*86400,now,now)).fetchone()
 if fund:
  item=dict(fund);symbol=item['symbol'];uid=item['user_id'];aid=item['asset_id']
  def same(a,b):return isinstance(a,str) and isinstance(b,str) and bool(a.strip()) and a.strip().casefold()==b.strip().casefold()
  matched=all(same(item[k],item['linked_'+k]) for k in ('isin','ticker','currency','exchange'))
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
   from instrument_resolver import _us_issuer
   names=_us_issuer(item.get('name'))
   valid=(str(g.get('Code') or '').upper()==symbol.rsplit('.',1)[0].upper() and same(g.get('ISIN'),item['isin']) and same(g.get('CurrencyCode'),item['currency']) and same(g.get('Exchange'),item['exchange']) and names[0] and names==_us_issuer(g.get('Name')) and str(g.get('Type') or '').upper() in ('ETF','ETP','FUND'))
   status='IDENTITY_VERIFIED' if valid else response['status'] if response['status']!='OK' else 'IDENTITY_OR_SECTOR_UNKNOWN'
   if valid:retry=now
  with connect() as c:c.execute('INSERT OR REPLACE INTO sector_fund_exposure VALUES(?,?,?,?,?,?,?)',(uid,aid,symbol,payload,status,now,retry))
  return
 with connect() as c:
  for region,items in PROXIES.items():
   for symbol,sector in items:
    row=c.execute('SELECT next_attempt FROM sector_market WHERE symbol=?',(symbol,)).fetchone()
    if not row or row['next_attempt']<=now:target=(region,symbol,sector);break
   else:continue
   break
  else:return
 region,symbol,sector=target
 with connect() as c:benchmark=c.execute('SELECT * FROM sector_benchmarks WHERE symbol=?',(symbol,)).fetchone()
 if not benchmark or benchmark['status']!='VERIFIED' or benchmark['next_attempt']<=now:
  if benchmark and benchmark['next_attempt']>now:
   with connect() as c:c.execute('INSERT OR REPLACE INTO sector_market(symbol,region,sector,payload,status,updated,next_attempt) VALUES(?,?,?,?,?,?,?)',(symbol,region,sector,None,'UNVERIFIED_BENCHMARK',now,benchmark['next_attempt']))
   return
  result=_client(connect,0)._http(HTTP_BASE,'/fundamentals/'+quote(symbol,safe=''),{'fmt':'json','filter':'General'})
  general=result.get('payload');general=general.get('General',general) if isinstance(general,dict) else {}
  verified=result['status']=='OK' and _benchmark_identity(region,sector,symbol,general)
  status='VERIFIED' if verified else result['status'] if result['status']!='OK' else 'IDENTITY_UNVERIFIED'
  retry=now+(7*86400 if verified else 86400)
  with connect() as c:
   c.execute('INSERT OR REPLACE INTO sector_benchmarks VALUES(?,?,?,?,?,?,?,?,?)',(symbol,region,sector,general.get('Name'),general.get('CurrencyCode'),general.get('Exchange'),status,now,retry))
   if not verified:c.execute('INSERT OR REPLACE INTO sector_market(symbol,region,sector,payload,status,updated,next_attempt) VALUES(?,?,?,?,?,?,?)',(symbol,region,sector,None,'UNVERIFIED_BENCHMARK',now,retry))
  return
 start=(datetime.now(timezone.utc).date()-timedelta(days=410)).isoformat()
 res=_client(connect,0)._http(HTTP_BASE,'/eod/'+quote(symbol,safe=''),{'fmt':'json','period':'d','from':start})
 series=_series(res.get('payload'));status='OK' if series else res['status'] if res['status']!='OK' else 'NO_DATA'
 with connect() as c:
  old=c.execute('SELECT payload FROM sector_market WHERE symbol=?',(symbol,)).fetchone()
  payload=json.dumps(series) if series else old['payload'] if old else None
  c.execute('INSERT OR REPLACE INTO sector_market(symbol,region,sector,payload,status,updated,next_attempt) VALUES(?,?,?,?,?,?,?)',(symbol,region,sector,payload,status,now,now+(3600 if series else 86400)))
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
  links={r['asset_id']:dict(r) for r in c.execute('SELECT * FROM hw_verified_feed_links WHERE user_id=? AND verified_epoch BETWEEN ? AND ?',(uid,time.time()-7*86400,time.time()))}
  markets=[dict(r) for r in c.execute('SELECT m.*,b.status AS benchmark_status,b.updated AS benchmark_updated,b.name AS benchmark_name,b.currency AS benchmark_currency,b.exchange AS benchmark_exchange FROM sector_market m LEFT JOIN sector_benchmarks b ON b.symbol=m.symbol')]
  fx_quotes=[dict(r) for r in c.execute('SELECT currency,rate,event_time,status FROM sector_fx')]
  history=[dict(r) for r in c.execute('SELECT portfolio_id,observed,payload FROM sector_history WHERE user_id=? AND bucket>=? ORDER BY bucket',(uid,int((time.time()-366*86400)//14400)))]
  fx=c.execute('SELECT payload FROM fx_snapshots ORDER BY source_date DESC,id DESC LIMIT 1').fetchone()
 dashboard=dashboard_projection.build(connect,uid,owned,snapshots)
 for account in dashboard['accounts']:
  portfolio=next((p for p in owned if p['id']==account['id']),{})
  account['external_id']=portfolio.get('external_id')
  snapshot=snapshots.get(str(account['id'])) or {}
  value=(snapshot.get('data') or {}).get('value') or {}
  account['reported_result']=value.get('reported_result')
 for row in dashboard['positions']:
  aid=row.get('asset_id');instrument=instruments.get(aid,{});mismatch=any(row.get(k) and instrument.get(k) and str(row[k]).casefold()!=str(instrument[k]).casefold() for k in ('ticker','currency'));a=assets.get(aid,{}) if instrument.get('status')=='OK' and not mismatch else {};fund=funds.get(aid);link=links.get(aid,{})
  if mismatch:a={'status':'IDENTITY_EXPIRED'}
  identity_current=bool(link and all(instrument.get(k) and str(instrument[k]).casefold()==str(link.get(k,'')).casefold() for k in ('isin','ticker','currency','exchange')))
  if a.get('source')=='EODHD fundamentals' and (not identity_current or a.get('symbol')!=link.get('symbol')):a={'status':'IDENTITY_EXPIRED'}
  valid_fund=bool(fund and not mismatch and fund.get('payload') and 0<=time.time()-fund['updated']<=7*86400 and instrument.get('status')=='OK' and _kind(instrument.get('instrument_type'))=='fund' and fund['symbol']==link.get('symbol') and all(instrument.get(k) and str(instrument[k]).casefold()==str(link.get(k,'')).casefold() for k in ('isin','ticker','currency','exchange')))
  row['sector_intelligence']={'sector':a.get('sector'),'industry':a.get('industry'),'original_sector':a.get('original_sector'),'source':a.get('source'),'status':a.get('status') or instrument.get('status','AFVENTER'),'updated':a.get('updated'),'instrument_type':instrument.get('instrument_type'),'isin':instrument.get('isin'),'exchange':instrument.get('exchange'),'fund_exposure':{**json.loads(fund['payload']),'observed':fund['updated'],'symbol':fund['symbol']} if valid_fund else None}
 for r in markets:
  saved=r.pop('payload')
  verified=r.get('benchmark_status')=='VERIFIED' and r.get('benchmark_updated') is not None and 0<=time.time()-r['benchmark_updated']<=7*86400
  r['series']=json.loads(saved or '[]') if verified else []
  if not verified:r['status']='UNVERIFIED_BENCHMARK'
 for r in history:r['positions']=json.loads(r.pop('payload'))
 return {'dashboard':dashboard,'markets':markets,'history':history,'fx_quotes':fx_quotes,'fx':json.loads(fx['payload']) if fx else None,'regions':list(PROXIES)}
