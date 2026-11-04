"""Read-only provider adapters. Missing entitlements/fields are explicit faults."""
import hashlib,json,os,re,urllib.request,urllib.error
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from urllib.parse import quote,urlencode
from hotwatch_contract import EngineError,checksum,stamp
from hotwatch_engine import utc

class DataUnavailable(EngineError):pass

def reserve(connect,uid,source,now=None):
 uid=0 if source=='eodhd' else uid
 now=now or utc();window=int(now.timestamp()//60);limit=max(1,min(120,int(os.environ.get('ESCAPE_HW_REQUESTS_PER_MINUTE','12'))))
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM hw_request_budget WHERE window<?',(window-2,))
  row=c.execute('SELECT used FROM hw_request_budget WHERE user_id=? AND source=? AND window=?',(uid,source,window)).fetchone()
  if row and row['used']>=limit:raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
  c.execute('INSERT INTO hw_request_budget VALUES(?,?,?,1) ON CONFLICT(user_id,source,window) DO UPDATE SET used=used+1',(uid,source,window))

def unknown_context():return {'tradability':'unknown','status':'unknown','as_of':None,'position':'unknown','quantity':None,'cost_price':None,'portfolio_equity_dkk':None,'exposure_dkk':None,'fx_to_dkk':None,'fees_dkk':None,'orders':[]}

def providers(connect=None,uid=None,mode=False):
 result={'pluto':{'adapter':'existing read-only contracts','minimum_poll_s':300,'known_limits':['Quote timestamp may be absent','Bid/ask, volume and market session are not guaranteed','Fees/FX remain unknown unless actually supplied']},'eodhd':{'plan_reported_by_owner':'Active Trader','key_configured':bool(os.environ.get('ESCAPE_EODHD_API_KEY')),'enabled':os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')=='1','endpoint':'/api/real-time/{symbol}','minimum_poll_s':300,'entitlements_verified':False,'websocket_enabled':False,'known_limits':['Account/feed rights must be verified on the installation','REST quote is not assumed tick-level, regular-session or a complete OHLC bar']},'report_inbox':{'adapter':'existing observation inbox','trusted_for_new_buy':False},'synthetic':{'test_only':True}}

 if connect is not None and uid is not None:
  with connect() as c:
   for row in c.execute('SELECT * FROM hw_provider_health WHERE user_id=? AND is_test=?',(uid,int(mode))):
    result[row['source']].update(last_attempt=row['attempted'],last_success=row['succeeded'],last_error=row['code'],observed_capabilities=json.loads(row['payload']))
 return result

def search_eodhd_symbols(connect,uid,data,opener=None):
 """Search only a candidate owned by the current user; never expose API credentials."""
 import market_data
 if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1':raise DataUnavailable('EODHD_FEED_NOT_ENABLED')
 key=os.environ.get('ESCAPE_EODHD_API_KEY')
 if not key:raise DataUnavailable('EODHD_KEY_NOT_CONFIGURED')
 candidate=market_data.candidate(connect,uid,data);ticker=candidate.get('ticker')
 if not isinstance(ticker,str) or not re.fullmatch(r'[A-Za-z0-9.\-]{1,32}',ticker):raise DataUnavailable('EODHD_SYMBOL_MAPPING_REQUIRED')
 reserve(connect,uid,'eodhd')
 url='https://eodhd.com/api/search/'+quote(ticker,safe='')+'?'+urlencode({'api_token':key,'fmt':'json','limit':50})
 try:
  with (opener or urllib.request.build_opener(NoRedirect())).open(urllib.request.Request(url,headers={'Accept':'application/json'}),timeout=8) as response:
   raw=response.read(131073)
  if len(raw)>131072:raise ValueError()
  rows=json.loads(raw)
  if not isinstance(rows,list):raise ValueError()
 except urllib.error.HTTPError as error:
  raise DataUnavailable('EODHD_ENTITLEMENT_REJECTED' if error.code in [401,403] else 'EODHD_RATE_LIMIT' if error.code==429 else 'EODHD_READ_ERROR') from None
 except Exception:raise DataUnavailable('EODHD_READ_OR_CONTRACT_ERROR') from None
 choices=[];seen=set()
 for row in rows[:50]:
  if not isinstance(row,dict):continue
  code=row.get('Code');exchange=row.get('Exchange');name=row.get('Name');currency=row.get('Currency');isin=row.get('ISIN')
  if not isinstance(code,str) or not isinstance(exchange,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',code) or not re.fullmatch(r'[A-Za-z0-9_-]{1,16}',exchange):continue
  base=code.rsplit('.',1)[0] if code.upper().endswith('.'+exchange.upper()) else code
  if base.casefold()!=ticker.casefold():continue
  symbol=code if code.upper().endswith('.'+exchange.upper()) else code+'.'+exchange
  if symbol.casefold() in seen:continue
  seen.add(symbol.casefold());choices.append({'symbol':symbol,'name':name[:200] if isinstance(name,str) else None,'exchange':exchange,'currency':currency if isinstance(currency,str) and re.fullmatch('[A-Z]{3}',currency) else None,'isin':isin[:32] if isinstance(isin,str) else None})
 return {'ticker':ticker,'choices':choices}

class PlutoAdapter:
 def __init__(self,connect,uid):self.connect=connect;self.uid=uid;self.gateway=None;self.order_cache={}
 def factory(self,token):
  if self.gateway and self.gateway.token==token:return self.gateway
  from mcp_client import MCP
  connect=self.connect;uid=self.uid
  class ReadOnlyGateway(MCP):
   allowed={'search_assets','get_asset','get_portfolio_value','get_accounts','get_positions','get_collection','list_orders','get_collection_activity'}
   def __init__(self,token):super().__init__(token);self.catalog=None
   def tools(self):
    if self.catalog is None:self.catalog=super().tools()
    return self.catalog
   def request(self,method,params=None,notification=False):
    if method=='tools/call':
     name=(params or {}).get('name');metadata=next((t for t in self.catalog or [] if t['name']==name),None)
     if name not in self.allowed or not metadata or metadata.get('annotations',{}).get('readOnlyHint') is not True:raise DataUnavailable('PLUTO_WRITE_OR_UNKNOWN_TOOL_BLOCKED')
    elif method not in ['initialize','notifications/initialized','tools/list']:raise DataUnavailable('PLUTO_METHOD_BLOCKED')
    reserve(connect,uid,'pluto');return super().request(method,params,notification)
  self.gateway=ReadOnlyGateway(token);return self.gateway
 def context(self,request,currency):
  import portfolio_data
  result=unknown_context();rows=[];portfolios=[]
  with self.connect() as c:
   for pid in request['portfolio_ids']:
    p=c.execute("SELECT * FROM portfolios WHERE id=? AND user_id=? AND source='pluto' AND active=1",(pid,self.uid)).fetchone()
    if not p:return result
    portfolios.append(dict(p))
   if any(a['external_id']==b.get('parent_external_id') for a in portfolios for b in portfolios):return result
  for p in portfolios:
   with self.connect() as c:row=c.execute('SELECT * FROM portfolio_snapshots WHERE portfolio_id=? AND user_id=?',(p['id'],self.uid)).fetchone()
   if not row or row['last_error'] or (utc()-stamp(row['observed'])).total_seconds()>300:
    payload=portfolio_data.read(self.connect,self.uid,p['id'],client_factory=self.factory)
    with self.connect() as c:portfolio_data.save(c,self.uid,p['id'],payload)
   else:payload=json.loads(row['payload'])
   if not payload.get('positions_complete') or not payload.get('complete'):return result
   rows.append(payload)
  if not rows:return result
  found=[position for payload in rows for position in payload['positions'] if position.get('asset_id')==request['asset_id']]
  if any(p['quantity'] is None for p in found):return result
  if any(p.get('ticker') and p['ticker'].casefold()!=request['ticker'].casefold() for p in found):raise DataUnavailable('PLUTO_ASSET_NOT_CONFIRMED')
  if any(Decimal(p['quantity'])<0 for p in found):raise DataUnavailable('PLUTO_SHORT_POSITION_NOT_SUPPORTED')
  quantity=sum((Decimal(p['quantity']) for p in found),Decimal(0))
  result.update(status='verified',as_of=min((p['observed'] for p in rows),key=stamp),position='held' if quantity>0 else 'none',quantity=format(quantity,'f'),fx_to_dkk='1' if currency=='DKK' else None)
  if len(found)==1 and found[0].get('average_entry',{}).get('currency')==currency:result['cost_price']=found[0]['average_entry']['amount']
  values=[p.get('value',{}).get('value') for p in rows]
  if all(v and v['amount'] is not None and v['currency']=='DKK' for v in values):result['portfolio_equity_dkk']=format(sum(Decimal(v['amount']) for v in values),'f')
  exposures=[p.get('value_in_portfolio_currency') for p in found]
  if not found:result['exposure_dkk']='0'
  elif all(v and v['amount'] is not None and v['currency']=='DKK' for v in exposures):result['exposure_dkk']=format(sum(Decimal(v['amount']) for v in exposures),'f')
  # Existing broker snapshots only prove the order rows actually received.
  for payload in rows:
   for o in payload.get('pending_orders',[])+payload.get('unconfirmed_orders',[]):
    if o.get('ticker','').casefold()==request['ticker'].casefold() and o.get('key') and o.get('verified_id'):
     result['orders'].append({'order_id':o['key'].replace('order:','').replace('trade:',''),'status':o['status'],'requested_quantity':o.get('requested_quantity'),'filled_quantity':o.get('filled_quantity'),'side':o.get('side') if o.get('side') in ['BUY','SELL'] else None})
  result['orders_complete']=False
  try:
   inactive=self.inactive_orders(portfolios,request)
   known={o['order_id']:o for o in result['orders']}
   for order in inactive:known[order['order_id']]=order
   result['orders']=list(known.values())[:100]
  except Exception:pass
  return result
 def inactive_orders(self,portfolios,request):
  import oauth,trade_service,portfolio_data
  result=[];now=utc().timestamp()
  for p in portfolios:
   cached=self.order_cache.get(p['id'])
   if not cached or now-cached['at']>=300:
    parent=p['external_id'] if p['kind']=='portfolio' else p['parent_external_id']
    if not parent:continue
    cl=self.factory(oauth.access_token(self.connect,self.uid));tools={t['name']:t for t in cl.tools()}
    raw=trade_service.call(cl,tools,'list_orders',{'portfolioId':parent.split(':',1)[1],'statusGroup':'INACTIVE','scope':'DIRECT' if p['kind']=='portfolio' else 'COLLECTION','limit':50})
    rows=portfolio_data.list_data(raw,['orders','items','data']);cached={'at':now,'rows':rows[:50]};self.order_cache[p['id']]=cached
   for row in cached['rows']:
    if not isinstance(row,dict):continue
    if p['kind']=='collection' and row.get('collectionId')!=p['external_id'].split(':',1)[1]:continue
    body=row.get('holding') if isinstance(row.get('holding'),dict) else row;asset=body.get('asset') if isinstance(body.get('asset'),dict) else {}
    aid=row.get('assetId') or body.get('assetId') or asset.get('id')
    if aid!=request['asset_id']:continue
    ticker=body.get('ticker') or asset.get('ticker') or row.get('ticker')
    if ticker and ticker.casefold()!=request['ticker'].casefold():raise DataUnavailable('PLUTO_ASSET_NOT_CONFIRMED')
    identity=row.get('orderId') or row.get('id');status=row.get('status')
    if not isinstance(identity,str) or not isinstance(status,str):continue
    changed=portfolio_data.date_field(row,['statusChangedAt','updatedAt'])
    result.append({'order_id':identity,'status':status,'requested_quantity':portfolio_data.number(row.get('requestedQuantity',body.get('quantity'))),'filled_quantity':portfolio_data.number(row.get('filledQuantity')),'side':row.get('side') if row.get('side') in ['BUY','SELL'] else None,'status_time':changed})
  return result
 def poll(self,session):
  import market_data
  r=session['request_data'];q=market_data.quote(self.connect,self.uid,{'report_id':r['report_id'],'candidate_id':r['candidate_id'],'is_test':r['is_test'],'asset_id':r['asset_id']},factory=self.factory)
  if q.get('pending'):raise DataUnavailable('PLUTO_REQUEST_PENDING')
  if q.get('selection_required') or q.get('asset_id')!=r['asset_id'] or str(q.get('ticker','')).casefold()!=r['ticker'].casefold():raise DataUnavailable('PLUTO_ASSET_NOT_CONFIRMED')
  if q.get('last_error'):raise DataUnavailable('PLUTO_PROVIDER_ERROR')
  context=self.context(r,q['currency'])
  if not q.get('price_time'):
   error=DataUnavailable('PLUTO_QUOTE_TIME_UNKNOWN');error.position_context=context;raise error
  at=stamp(q['price_time'])
  return {'sample_id':'pluto-'+hashlib.sha256((r['asset_id']+q['price_time']).encode()).hexdigest()[:32],'source':'pluto','ticker':r['ticker'],'asset_id':r['asset_id'],'venue':q.get('exchange'),'currency':q['currency'],'event_time':q['price_time'],'session_key':at.date().isoformat()+':UNKNOWN','market_status':'UNKNOWN','feed_type':'Pluto get_asset price; cadence/session unconfirmed','documented_delay_s':None,'verification':'verified','error_code':None,'interval_s':300,'price':q['price'],'bid':None,'ask':None,'volume':None,'volume_type':'unknown','open':None,'high':None,'low':None,'close':None,'context':context}

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
class EODHDAdapter:
 def __init__(self,connect,uid,opener=None):self.connect=connect;self.uid=uid;self.opener=opener or urllib.request.build_opener(NoRedirect());self.pluto=PlutoAdapter(connect,uid)
 def poll(self,session):
  if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1':raise DataUnavailable('EODHD_FEED_NOT_ENABLED')
  key=os.environ.get('ESCAPE_EODHD_API_KEY')
  if not key:raise DataUnavailable('EODHD_KEY_NOT_CONFIGURED')
  r=session['request_data'];symbol=r.get('provider_symbol')
  if not symbol:raise DataUnavailable('EODHD_SYMBOL_MAPPING_REQUIRED')
  if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',symbol):raise DataUnavailable('EODHD_SYMBOL_MAPPING_REQUIRED')
  # Exchange is an explicit EODHD code, not inferred from a display name.
  reserve(self.connect,self.uid,'eodhd');url='https://eodhd.com/api/real-time/'+quote(symbol,safe='')+'?'+urlencode({'api_token':key,'fmt':'json'})
  try:
   with self.opener.open(urllib.request.Request(url,headers={'Accept':'application/json'}),timeout=8) as response:
    raw=response.read(131073)
    if len(raw)>131072:raise ValueError()
    d=json.loads(raw,parse_float=str)
   if not isinstance(d,dict) or d.get('code') not in [symbol,r['ticker']] or not isinstance(d.get('timestamp'),(int,str)) or type(d.get('timestamp')) is bool:raise ValueError()
   at=datetime.fromtimestamp(int(d['timestamp']),timezone.utc);price=Decimal(str(d['close']))
   if not price.is_finite() or price<=0:raise ValueError()
  except urllib.error.HTTPError as error:
   if error.code==429:
    failure=DataUnavailable('EODHD_RATE_LIMIT',429)
    retry=error.headers.get('Retry-After','600') if error.headers else '600'
    try:
     seconds=int(retry);failure.retry_after_s=max(600,min(604800,seconds))
     if seconds>604800:failure.code='EODHD_RATE_LIMIT_MANUAL_REVIEW'
    except (ValueError,TypeError):failure.retry_after_s=3600
    raise failure from None
   raise DataUnavailable('EODHD_ENTITLEMENT_REJECTED' if error.code in [401,403] else 'EODHD_READ_ERROR') from None
  except Exception:raise DataUnavailable('EODHD_READ_OR_CONTRACT_ERROR') from None
  # This documented price endpoint does not prove bid/ask, interval volume,
  # market status or account entitlement. Never invent these capabilities.
  currency=d.get('currency') or r.get('quote_currency')
  if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):raise DataUnavailable('EODHD_CURRENCY_UNCONFIRMED')
  if d.get('currency') and d['currency']!=r.get('quote_currency'):raise DataUnavailable('quote_currency_mismatch')
  return {'sample_id':'eodhd-'+hashlib.sha256((symbol+at.isoformat()).encode()).hexdigest()[:32],'source':'eodhd','ticker':r['ticker'],'asset_id':r['asset_id'],'venue':r['exchange'],'currency':currency,'event_time':at.isoformat(),'session_key':at.date().isoformat()+':UNKNOWN','market_status':'UNKNOWN','feed_type':'EODHD REST real-time endpoint; entitlement/cadence unconfirmed; currency='+('provider' if d.get('currency') else 'explicit session instrument'),'documented_delay_s':None,'verification':'verified','error_code':None,'interval_s':300,'price':format(price,'f'),'bid':None,'ask':None,'volume':None,'volume_type':'unknown','open':None,'high':None,'low':None,'close':None,'context':self.pluto.context(r,currency)}

class InboxAdapter:
 def __init__(self,connect,uid):self.connect=connect;self.uid=uid
 def poll(self,session):
  r=session['request_data']
  with self.connect() as c:row=c.execute('SELECT payload FROM hot_watch_observations WHERE user_id=? AND is_test=? AND candidate_id=? ORDER BY observed DESC,id DESC LIMIT 1',(self.uid,int(r['is_test']),r['candidate_id'])).fetchone()
  if not row:raise DataUnavailable('NO_INBOX_OBSERVATION')
  d=json.loads(row['payload']);m=d['market']
  if not m['price'] or not m['price_at'] or d['instrument']['asset_id']!=r['asset_id']:raise DataUnavailable('INBOX_PRICE_OR_IDENTITY_UNKNOWN')
  at=stamp(m['price_at'])
  return {'sample_id':d['observation_id'],'source':'report_inbox','ticker':r['ticker'],'asset_id':r['asset_id'],'venue':m['venue'],'currency':m['price']['currency'],'event_time':m['price_at'],'session_key':at.date().isoformat()+':UNKNOWN','market_status':'UNKNOWN','feed_type':'Sender-provided report observation; not a direct provider feed','documented_delay_s':m['delay_seconds'],'verification':'unverified','error_code':None,'interval_s':60,'price':m['price']['amount'],'bid':None,'ask':None,'volume':None,'volume_type':'unknown','open':None,'high':None,'low':None,'close':None,'context':unknown_context()}
