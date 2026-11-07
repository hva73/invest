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
SECTORS={'technology':'Teknologi','healthcare':'Sundhed','financial services':'Finans','financials':'Finans','industrials':'Industri','energy':'Energi','consumer cyclical':'Forbrug, cyklisk','consumer defensive':'Forbrug, stabilt','basic materials':'Materialer','utilities':'Forsyning','real estate':'Ejendomme','communication services':'Kommunikation'}

def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS sector_assets(user_id INTEGER NOT NULL,asset_id TEXT NOT NULL,symbol TEXT,sector TEXT,industry TEXT,source TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL,PRIMARY KEY(user_id,asset_id))')
 c.execute('CREATE TABLE IF NOT EXISTS sector_fx(currency TEXT PRIMARY KEY, rate REAL, event_time TEXT, status TEXT NOT NULL, updated REAL NOT NULL, next_attempt REAL NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS sector_market(symbol TEXT PRIMARY KEY,region TEXT NOT NULL,sector TEXT NOT NULL,payload TEXT,status TEXT NOT NULL,updated REAL NOT NULL,next_attempt REAL NOT NULL)')
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
  existing={(r['user_id'],r['asset_id']):dict(r) for r in c.execute('SELECT * FROM sector_assets')}
  links={(r['user_id'],r['asset_id']) for r in c.execute('SELECT user_id,asset_id FROM hw_verified_feed_links WHERE verified_epoch BETWEEN ? AND ?',(now-7*86400,now))}
 for snap in snapshots:
  try:payload=json.loads(snap['payload'])
  except (ValueError,TypeError):continue
  for pos in payload.get('positions',[]):
   aid=pos.get('asset_id');key=(snap['user_id'],aid);old=existing.get(key)
   if aid and pos.get('kind')!='collection' and key not in links and (old is None or old['next_attempt']<=now):return snap['user_id'],aid,pos.get('ticker')
 return None

def _fetch_pluto(connect,candidate,now):
 import trade_service
 from hotwatch_adapters import PlutoAdapter
 uid,aid,ticker=candidate;adapter=PlutoAdapter(connect,uid,purpose='sector')
 try:
  client,tools=trade_service.client(connect,uid,adapter.factory)
  raw=trade_service.call(client,tools,'get_asset',{'assetId':aid})
  asset=raw.get('asset',raw) if isinstance(raw,dict) else {}
  ids=[x for x in (asset.get('id'),asset.get('assetId'),raw.get('assetId')) if x is not None]
  if not ids or any(x!=aid for x in ids) or ticker and asset.get('ticker') and ticker.casefold()!=str(asset['ticker']).casefold():raise ValueError('identity')
  raw_sector=asset.get('sector');kind=str(asset.get('type') or asset.get('assetType') or '').upper()
  if isinstance(raw_sector,str) and raw_sector.strip():sector=SECTORS.get(raw_sector.casefold().strip(),raw_sector.strip())
  elif kind in ('CRYPTO','CRYPTOCURRENCY'):sector='Krypto (aktivklasse)'
  else:sector=None
  industry=asset.get('industry') if isinstance(asset.get('industry'),str) else None
  status='OK' if sector else 'SECTOR_NOT_RETURNED'
 except Exception:
  sector=industry=None;status='PLUTO_UNAVAILABLE'
 with connect() as c:c.execute('INSERT OR REPLACE INTO sector_assets VALUES(?,?,?,?,?,?,?,?,?)',(uid,aid,None,sector,industry,'Pluto get_asset' if sector else None,status,now,now+(7*86400 if sector else 86400)))

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
 with connect() as c:
  # Only reuse identities already checked by the existing HOT WATCH engine.
  candidates=c.execute('''SELECT l.* FROM hw_verified_feed_links l JOIN users u ON u.id=l.user_id AND u.active=1
    LEFT JOIN sector_assets a ON a.user_id=l.user_id AND a.asset_id=l.asset_id
    WHERE l.verified_epoch BETWEEN ? AND ? AND (a.asset_id IS NULL OR a.next_attempt<=? OR COALESCE(a.symbol,'')!=l.symbol)
    ORDER BY COALESCE(a.next_attempt,0) LIMIT 1''',(now-7*86400,now,now)).fetchone()
 if candidates:
  item=dict(candidates);symbol=item['symbol']
  if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',symbol):return
  res=_client(connect,item['user_id'])._http(HTTP_BASE,'/fundamentals/'+quote(symbol,safe=''),{'fmt':'json','filter':'General'})
  general=res.get('payload');general=general.get('General',general) if isinstance(general,dict) else {}
  code=str(general.get('Code') or '').upper(); expected=symbol.rsplit('.',1)[0].upper()
  isin=str(general.get('ISIN') or '').upper(); currency=str(general.get('CurrencyCode') or '').upper()
  identity=(code==expected and (not isin or isin==item['isin'].upper()) and (not currency or currency==item['currency'].upper()))
  raw=general.get('Sector');sector=SECTORS.get(raw.casefold().strip(),raw.strip()) if identity and isinstance(raw,str) and raw.strip() and raw.strip().lower() not in ('none','n/a') else None
  industry=general.get('Industry') if sector and isinstance(general.get('Industry'),str) else None
  status='OK' if sector else res['status'] if res['status']!='OK' else 'IDENTITY_OR_SECTOR_UNKNOWN'
  with connect() as c:c.execute('INSERT OR REPLACE INTO sector_assets VALUES(?,?,?,?,?,?,?,?,?)',(item['user_id'],item['asset_id'],symbol,sector,industry,'EODHD fundamentals' if sector else None,status,now,now+(7*86400 if sector else 86400)))
  return
 candidate=_pluto_candidate(connect,now)
 if candidate and int(now//60)%2==0:
  _fetch_pluto(connect,candidate,now);return
 with connect() as c:
  for region,items in PROXIES.items():
   for symbol,sector in items:
    row=c.execute('SELECT next_attempt FROM sector_market WHERE symbol=?',(symbol,)).fetchone()
    if not row or row['next_attempt']<=now:target=(region,symbol,sector);break
   else:continue
   break
  else:return
 region,symbol,sector=target
 start=(datetime.now(timezone.utc).date()-timedelta(days=410)).isoformat()
 res=_client(connect,0)._http(HTTP_BASE,'/eod/'+quote(symbol,safe=''),{'fmt':'json','period':'d','from':start})
 series=_series(res.get('payload'));status='OK' if series else res['status'] if res['status']!='OK' else 'NO_DATA'
 with connect() as c:
  old=c.execute('SELECT payload FROM sector_market WHERE symbol=?',(symbol,)).fetchone()
  payload=json.dumps(series) if series else old['payload'] if old else None
  c.execute('INSERT OR REPLACE INTO sector_market VALUES(?,?,?,?,?,?,?)',(symbol,region,sector,payload,status,now,now+(3600 if series else 86400)))

def read(connect,uid):
 import portfolios,portfolio_data,dashboard_projection
 with connect() as c:
  owned=portfolios.list_owned(c,uid);snapshots=portfolio_data.snapshots(c,uid)
  assets={r['asset_id']:dict(r) for r in c.execute('SELECT * FROM sector_assets WHERE user_id=?',(uid,))}
  markets=[dict(r) for r in c.execute('SELECT * FROM sector_market')]
  fx_quotes=[dict(r) for r in c.execute('SELECT currency,rate,event_time,status FROM sector_fx')]
  history=[dict(r) for r in c.execute('SELECT portfolio_id,observed,payload FROM sector_history WHERE user_id=? AND bucket>=? ORDER BY bucket',(uid,int((time.time()-366*86400)//14400)))]
  fx=c.execute('SELECT payload FROM fx_snapshots ORDER BY source_date DESC,id DESC LIMIT 1').fetchone()
 dashboard=dashboard_projection.build(connect,uid,owned,snapshots)
 for account in dashboard['accounts']:
  snapshot=snapshots.get(str(account['id'])) or {}
  value=(snapshot.get('data') or {}).get('value') or {}
  account['reported_result']=value.get('reported_result')
 for row in dashboard['positions']:
  a=assets.get(row.get('asset_id'),{});row['sector_intelligence']={'sector':a.get('sector'),'industry':a.get('industry'),'source':a.get('source'),'status':a.get('status','AFVENTER'),'updated':a.get('updated')}
 for r in markets:
  r['series']=json.loads(r.pop('payload') or '[]')
 for r in history:r['positions']=json.loads(r.pop('payload'))
 return {'dashboard':dashboard,'markets':markets,'history':history,'fx_quotes':fx_quotes,'fx':json.loads(fx['payload']) if fx else None,'regions':list(PROXIES)}
