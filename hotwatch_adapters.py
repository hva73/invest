"""Read-only provider adapters. Missing entitlements/fields are explicit faults."""
import hashlib,json,os,re,sqlite3,time,urllib.request,urllib.error,threading,copy
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from urllib.parse import quote,urlencode
from hotwatch_contract import EngineError,checksum,stamp,provider_floor,PROFILES,GLOBAL_RISK
from hotwatch_engine import utc,effective_poll_interval,valid_cxe_evidence,provider_request_limit
from eodhd_capacity import Capacity,retry_seconds

class DataUnavailable(EngineError):pass

def local_budget_error(result):
 code=result.get('budget_reason')
 if code not in ('EODHD_DAILY_BUDGET','PROVIDER_RATE_BUDGET'):code='PROVIDER_RATE_BUDGET'
 failure=DataUnavailable(code,429)
 if result.get('retry_after_s') is not None:failure.retry_after_s=result['retry_after_s']
 return failure

_quote_cache={}
_quiet_intraday_empty={}
_ws_batch_cache={}
_ws_batch_lock=threading.Lock()
_ws_batch_inflight={}
_quote_locks=[threading.Lock() for _ in range(32)]

def shared_quote(key,symbol,fetch,enabled=True):
 """Share a successful raw quote briefly; preserve its original receive time."""
 if not enabled:return fetch()
 cache_key=(hashlib.sha256(key.encode()).digest(),symbol)
 with _quote_locks[hash(cache_key)%len(_quote_locks)]:
  now=time.monotonic();cached=_quote_cache.get(cache_key)
  if cached and 0<=now-cached[0]<5:return copy.deepcopy(cached[1])
  result=fetch()
  if len(_quote_cache)>=256:_quote_cache.clear()
  _quote_cache[cache_key]=(time.monotonic(),copy.deepcopy(result))
  return result

def quiet_intraday_lookup(key,symbol,last_data,quiet,fetch):
 """Reuse a verified empty lookup briefly only while quiet polling applies."""
 if not quiet:return fetch(),False
 cache_key=(hashlib.sha256(key.encode()).digest(),symbol,last_data)
 with _quote_locks[hash(cache_key)%len(_quote_locks)]:
  cached=_quiet_intraday_empty.get(cache_key)
  if cached and 0<=time.monotonic()-cached[0]<300:return copy.deepcopy(cached[1]),True
  result=fetch()
  if result.get('status')=='NO_DATA':
   if len(_quiet_intraday_empty)>=512:_quiet_intraday_empty.clear()
   _quiet_intraday_empty[cache_key]=(time.monotonic(),copy.deepcopy(result))
  return result,False

def reserve(connect,uid,source,now=None,purpose=None):
 if source=='eodhd':
  try:return Capacity(connect).reserve(now=now.timestamp() if now is not None else None)
  except EngineError as error:raise DataUnavailable(error.code,error.status) from None
 uid=0 if source=='eodhd' else uid
 now=now or utc();window=int(now.timestamp()//60);limit=provider_request_limit(source)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM hw_request_budget WHERE window<?',(window-2,))
  row=c.execute('SELECT used FROM hw_request_budget WHERE user_id=? AND source=? AND window=?',(uid,source,window)).fetchone()
  # Charge only actual requests against the configured provider-wide limit.
  # Priority and fair scheduling are handled before a session is claimed;
  # idle reservations must not consume capacity or delay new identities.
  if row and row['used']>=limit:raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
  c.execute('INSERT INTO hw_request_budget VALUES(?,?,?,1) ON CONFLICT(user_id,source,window) DO UPDATE SET used=used+1',(uid,source,window))

def unknown_context(diagnostic=None):
 result={'tradability':'unknown','status':'unknown','as_of':None,'position':'unknown','quantity':None,'cost_price':None,'portfolio_equity_dkk':None,'exposure_dkk':None,'fx_to_dkk':None,'fees_dkk':None,'orders':[]}
 if diagnostic:result['diagnostic']=diagnostic
 return result

def providers(connect=None,uid=None,mode=False):
 result={'pluto':{'adapter':'existing read-only contracts','minimum_poll_s':300,'known_limits':['Quote timestamp may be absent','Bid/ask, volume and market session are not guaranteed','Fees/FX remain unknown unless actually supplied']},'eodhd':{'plan_reported_by_owner':'Active Trader','key_configured':bool(os.environ.get('ESCAPE_EODHD_API_KEY','').strip()),'enabled':os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')=='1','endpoint':'/api/real-time/{symbol}','minimum_poll_s':provider_floor('eodhd'),'entitlements_verified':False,'websocket_enabled':os.environ.get('ESCAPE_HW_EODHD_WS_TRADES_ENABLED')=='1','known_limits':['Account/feed rights must be verified on the installation','REST quote is not assumed tick-level, regular-session or a complete OHLC bar']},'report_inbox':{'adapter':'existing observation inbox','trusted_for_new_buy':False},'synthetic':{'test_only':True}}
 result['eodhd'].update(fusion_enabled=os.environ.get('ESCAPE_HW_EODHD_FUSE_ENABLED')=='1',minute_bars_enabled=os.environ.get('ESCAPE_HW_EODHD_BARS_ENABLED')=='1')

 if connect is not None and uid is not None:
  with connect() as c:
   for row in c.execute('SELECT * FROM hw_provider_health WHERE user_id=? AND is_test=?',(uid,int(mode))):
    result[row['source']].update(last_attempt=row['attempted'],last_success=row['succeeded'],last_error=row['code'],observed_capabilities=json.loads(row['payload']))
 return result

def search_eodhd_symbols(connect,uid,data,opener=None,candidate_override=None,purpose=None):
 """Search only a candidate owned by the current user; never expose API credentials."""
 import market_data
 if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1':raise DataUnavailable('EODHD_FEED_NOT_ENABLED')
 key=os.environ.get('ESCAPE_EODHD_API_KEY','').strip()
 if not key:raise DataUnavailable('EODHD_KEY_NOT_CONFIGURED')
 candidate=candidate_override if candidate_override is not None else market_data.holding_candidate(connect,uid,data) if 'holding_portfolio_id' in data else market_data.candidate(connect,uid,data);ticker=candidate.get('ticker')
 if not isinstance(ticker,str) or not re.fullmatch(r'[A-Za-z0-9.\-]{1,32}',ticker):raise DataUnavailable('EODHD_SYMBOL_MAPPING_REQUIRED')
 name_key=lambda x:re.sub(r'[^a-z0-9]','',x.casefold()) if isinstance(x,str) else ''
 issuer=candidate.get('company_name');issuer_key=name_key(issuer)
 expected_currency=data.get('quote_currency')
 if not isinstance(expected_currency,str) or not re.fullmatch('[A-Z]{3}',expected_currency):expected_currency=None
 crypto=str(candidate.get('asset_type') or '').upper()=='CRYPTO'
 choices=[];seen=set();client=opener or urllib.request.build_opener(NoRedirect());not_found=[];successful=[]
 def search(query,allow_alias=False,allow_ticker_alias=False):
  url='https://eodhd.com/api/search/'+quote(query,safe='')+'?'+urlencode({'api_token':key,'fmt':'json','limit':50})
  try:
   with Capacity(connect).open(client,urllib.request.Request(url,headers={'Accept':'application/json'})) as response:raw=response.read(131073)
   if len(raw)>131072:raise ValueError()
   rows=json.loads(raw)
   if not isinstance(rows,list):raise ValueError()
   successful.append(True)
  except urllib.error.HTTPError as error:
   if error.code==404:not_found.append(True);return
   if error.code in [401,403]:raise DataUnavailable('EODHD_SEARCH_HTTP_'+str(error.code),502) from None
   if error.code==429:
    failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=retry_seconds(error.headers);raise failure from None
   raise DataUnavailable('EODHD_SEARCH_HTTP_'+str(error.code),502) from None
  except EngineError:raise
  except Exception:raise DataUnavailable('EODHD_SEARCH_NETWORK_OR_RESPONSE_ERROR',502) from None
  for row in rows[:50]:
   if not isinstance(row,dict):continue
   code=row.get('Code');exchange=row.get('Exchange');name=row.get('Name');currency=row.get('Currency');isin=row.get('ISIN')
   if not isinstance(code,str) or not isinstance(exchange,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',code) or not re.fullmatch(r'[A-Za-z0-9_-]{1,16}',exchange):continue
   if currency not in (None,'') and (not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency)):continue
   base=code.rsplit('.',1)[0] if code.upper().endswith('.'+exchange.upper()) else code
   ticker_equivalent=allow_ticker_alias and re.sub(r'[^a-z0-9]','',base.casefold())==re.sub(r'[^a-z0-9]','',ticker.casefold())
   # A quoted crypto pair is a search candidate, not an identity proof.
   crypto_pair=bool(crypto and expected_currency and exchange.upper()=='CC' and str(row.get('Type','')).casefold()=='currency' and base.upper()==ticker.upper()+'-'+expected_currency and currency in (None,'',expected_currency))
   from instrument_resolver import same_us_class_ticker
   exact_class_alias=exchange.upper()=='US' and same_us_class_ticker(base,ticker)
   if base.casefold()!=ticker.casefold() and not exact_class_alias and not ticker_equivalent and not crypto_pair and not (allow_alias and issuer_key and name_key(name)==issuer_key):continue
   symbol=code if code.upper().endswith('.'+exchange.upper()) else code+'.'+exchange
   if symbol.casefold() in seen:continue
   seen.add(symbol.casefold());choices.append({'symbol':symbol,'name':name[:200] if isinstance(name,str) else None,'exchange':exchange,'currency':currency if isinstance(currency,str) and re.fullmatch('[A-Z]{3}',currency) else None,'isin':isin[:32] if isinstance(isin,str) else None})
 search(ticker)
 needs_issuer=not choices or (expected_currency and not any(x['currency']==expected_currency for x in choices))
 # Search terms are path components: slashes in legal names can be rejected by
 # web servers. Search by the first two words and require the complete issuer
 # name to match in the returned metadata before offering an alias.
 words=re.findall(r'[^\W_]+',issuer,flags=re.UNICODE) if isinstance(issuer,str) else []
 issuer_query=' '.join(words[:2])
 if needs_issuer and len(name_key(issuer_query))>=3:search(issuer_query[:100],allow_alias=True)
 elif needs_issuer and len(ticker)>=3 and ticker.isalnum():
  # Some exchanges spell a share-class suffix with a hyphen (e.g. XYZB vs
  # XYZ-B). Search that exact variant; the user must still select the result.
  search(ticker[:-1]+'-'+ticker[-1],allow_ticker_alias=True)
 if not choices and not_found and not successful:raise DataUnavailable('EODHD_SEARCH_HTTP_404',502)
 return {'ticker':ticker,'choices':choices}

class PlutoAdapter:
 def __init__(self,connect,uid,purpose='scan'):self.connect=connect;self.uid=uid;self.purpose=purpose;self.gateway=None;self.order_cache={};self.permission_cache={};self.context_lock=threading.RLock()
 def safe_context(self,request,currency):
  try:return self.context(request,currency)
  except DataUnavailable as error:return unknown_context(error.code if error.code=='PROVIDER_RATE_BUDGET' else 'BROKER_CONTEXT_UNAVAILABLE')
  except sqlite3.Error:return unknown_context('BROKER_CONTEXT_DATABASE_ERROR')
  except urllib.error.HTTPError:return unknown_context('BROKER_CONTEXT_PROVIDER_HTTP_ERROR')
  except (TimeoutError,ConnectionError,urllib.error.URLError):return unknown_context('BROKER_CONTEXT_NETWORK_ERROR')
  except Exception as error:
   # These fixed categories are safe to persist in the session. Never store an
   # exception string: provider responses may contain credentials or user data.
   try:
    from mcp_client import PortfolioFormatError
    import oauth
   except Exception:return unknown_context('BROKER_CONTEXT_UNAVAILABLE')
   if isinstance(error,PortfolioFormatError):return unknown_context('BROKER_CONTEXT_READ_UNAVAILABLE')
   if isinstance(error,oauth.SetupRequired):return unknown_context('BROKER_CONTEXT_SETUP_REQUIRED')
   return unknown_context('BROKER_CONTEXT_UNAVAILABLE')
 def factory(self,token):
  if self.gateway and self.gateway.token==token:return self.gateway
  from mcp_client import MCP
  connect=self.connect;uid=self.uid;purpose=self.purpose
  class ReadOnlyGateway(MCP):
   allowed={'search_assets','get_asset','get_portfolio_value','get_accounts','get_positions','get_collection','list_orders','list_portfolios','list_collections','get_collection_activity','estimate_order'}
   def __init__(self,token):super().__init__(token);self.catalog=None;self.read_cache={}
   def tools(self):
    if self.catalog is None:self.catalog=super().tools()
    return self.catalog
   def request(self,method,params=None,notification=False):
    if method=='tools/call':
     name=(params or {}).get('name');metadata=next((t for t in self.catalog or [] if t['name']==name),None)
     if name not in self.allowed or not metadata or metadata.get('annotations',{}).get('readOnlyHint') is not True:raise DataUnavailable('PLUTO_WRITE_OR_UNKNOWN_TOOL_BLOCKED')
    elif method not in ['initialize','notifications/initialized','tools/list']:raise DataUnavailable('PLUTO_METHOD_BLOCKED')
    key=None
    if method=='tools/call' and name in ('list_portfolios','list_collections') and not (params or {}).get('arguments'):
     key=name;cached=self.read_cache.get(key)
     if cached and 0<=utc().timestamp()-cached[0]<300:return copy.deepcopy(cached[1])
    started=utc().timestamp();reserve(connect,uid,'pluto',purpose=purpose);result=super().request(method,params,notification)
    if key and isinstance(result,dict) and result.get('isError') is not True:self.read_cache[key]=(started,copy.deepcopy(result))
    return result
  if self.gateway is not None:self.order_cache.clear();self.permission_cache.clear()
  self.gateway=ReadOnlyGateway(token);return self.gateway
 def permission_key(self,request,currency,portfolios):
  return (request['asset_id'],request['ticker'].casefold(),str(request.get('exchange') or '').casefold(),currency,tuple(sorted((p['id'],p.get('external_id'),p.get('parent_external_id'),p.get('kind')) for p in portfolios)),request.get('risk',{}).get('proposed_quantity') is not None)
 def tradability(self,request,currency,portfolios):
  """Only use current read-only Pluto instrument and account evidence."""
  import trade_service
  if not portfolios:return 'unknown',None
  key=self.permission_key(request,currency,portfolios);now=utc().timestamp();cached=self.permission_cache.get(key)
  if cached and 0<=now-cached['at']<300:return cached['status'],cached['at']
  try:
   client,tools=trade_service.client(self.connect,self.uid,self.factory);raw=trade_service.call(client,tools,'get_asset',{'assetId':request['asset_id']})
   asset=raw.get('asset') if isinstance(raw,dict) else None;buy=raw.get('buyBy') if isinstance(raw,dict) else None
   if not isinstance(asset,dict) or asset.get('id')!=request['asset_id'] or str(asset.get('ticker','')).casefold()!=request['ticker'].casefold() or asset.get('currency')!=currency:return 'unknown',None
   if request.get('exchange') and str(asset.get('exchange','')).casefold()!=request['exchange'].casefold():return 'unknown',None
   if not isinstance(buy,dict) or not (buy.get('shares') is True or buy.get('amount') is True):return 'unknown',None
   if request.get('risk',{}).get('proposed_quantity') is not None and buy.get('shares') is not True:return 'unknown',None
   for portfolio in portfolios:trade_service.fresh_permission(client,tools,self.connect,self.uid,portfolio)
   kinds={v.upper() for node in (asset,raw) for field in ('type','assetType') if isinstance((v:=node.get(field)),str) and 1<=len(v)<=100}
   kind=next(iter(kinds)) if len(kinds)==1 else None
   # Cached account evidence retains its original verification time.
   used={'list_portfolios','list_collections'} if any(p.get('kind')=='collection' for p in portfolios) else {'list_portfolios'}
   now=min([now]+[v[0] for k,v in getattr(client,'read_cache',{}).items() if k in used])
   self.permission_cache[key]={'at':now,'status':'available','instrument_type':kind};return 'available',now
  except Exception:
   cache=getattr(locals().get('client'),'read_cache',None)
   if isinstance(cache,dict):cache.clear()
   return 'unknown',None
 def context(self,request,currency):
  # Serialize broker refreshes for this user only, never market-data work or
  # SQLite scopes. The next scan rechecks the shared DB snapshot after waiting.
  with self.context_lock:return self._context(request,currency)
 def _context(self,request,currency):
  import portfolio_data
  result=unknown_context();rows=[];portfolios=[];automatic=not request['portfolio_ids']
  with self.connect() as c:
   owned=[dict(p) for p in c.execute("SELECT * FROM portfolios WHERE user_id=? AND source='pluto' AND active=1 ORDER BY id",(self.uid,))]
   by_id={p['id']:p for p in owned}
   if any(pid not in by_id for pid in request['portfolio_ids']):return unknown_context('PORTFOLIO_NOT_ACTIVE')
   portfolios=owned if automatic else [by_id[pid] for pid in request['portfolio_ids']]
   scope=tuple((p['id'],p['external_id'],p.get('parent_external_id'),p['kind']) for p in owned)
   overlap=any(a['external_id']==b.get('parent_external_id') for a in portfolios for b in portfolios)
   if overlap and not automatic:return unknown_context('PORTFOLIO_SCOPE_OVERLAP')
  if getattr(self,'portfolio_scope',scope)!=scope:
   self.permission_cache.clear();self.order_cache.clear()
   if self.gateway is not None:getattr(self.gateway,'read_cache',{}).clear()
  self.portfolio_scope=scope
  for p in portfolios:
   with self.connect() as c:row=c.execute('SELECT * FROM portfolio_snapshots WHERE portfolio_id=? AND user_id=?',(p['id'],self.uid)).fetchone()
   payload=json.loads(row['payload']) if row and not row['last_error'] and 0<=(utc()-stamp(row['observed'])).total_seconds()<=300 else None
   # A partial legacy snapshot does not prove the positions list was checked
   # independently. Re-read it with strict pagination/count checks instead.
   expected_scope='DIRECT' if p.get('kind')=='portfolio' else 'COLLECTION'
   if payload is None or (not payload.get('complete') and not payload.get('positions_strict_verified')) or (automatic and overlap and payload.get('positions_scope')!=expected_scope):
    payload=portfolio_data.read(self.connect,self.uid,p['id'],client_factory=self.factory,strict_positions=True)
    with self.connect() as c:portfolio_data.save(c,self.uid,p['id'],payload)
   # Independently checked positions establish held/none for either watch.
   # Missing capital, FX, fees and permissions remain unknown to the buy gate.
   position_only=payload.get('positions_strict_verified') is True
   if not payload.get('positions_complete') or not (payload.get('complete') or position_only):return unknown_context('PORTFOLIO_SNAPSHOT_INCOMPLETE')
   rows.append(payload)
  if not rows:return unknown_context('NO_ACTIVE_PORTFOLIOS')
  if automatic and overlap:
   # Parent get_positions reports direct holdings and collection references,
   # not a flattened aggregate. Only combine separately verified scopes when
   # every referenced collection is present and independently complete.
   for p,payload in zip(portfolios,rows):
    expected='DIRECT' if p.get('kind')=='portfolio' else 'COLLECTION'
    if payload.get('positions_scope')!=expected or payload.get('positions_strict_verified') is not True:return unknown_context('HOLDING_SCOPE_OVERLAP')
    if expected=='DIRECT':
     listed=payload.get('positions_collection_ids')
     children=[v['external_id'].split(':',1)[1] for v in portfolios if v.get('kind')=='collection' and v.get('parent_external_id')==p['external_id']]
     if not isinstance(listed,list) or sorted(listed)!=sorted(children):return unknown_context('HOLDING_SCOPE_OVERLAP')
  # An unidentified holding could be this asset; absence is not proven.
  if any(p.get('kind','holding')=='holding' and not p.get('asset_id') for payload in rows for p in payload['positions']):return unknown_context('HOLDING_ID_MISSING')
  found=[position for payload in rows for position in payload['positions'] if position.get('asset_id')==request['asset_id']]
  # Buy permissions are irrelevant to exit-only holding watches and each
  # unnecessary check competes with identity/quote requests for Pluto budget.
  # Keep the value unknown rather than claiming a permission was checked.
  tradability_at=None
  if request.get('watch_mode')!='exit':
   result['tradability'],tradability_at=self.tradability(request,currency,portfolios)
   proof=self.permission_cache.get(self.permission_key(request,currency,portfolios)) if tradability_at is not None else None
   if proof and proof.get('instrument_type'):
    result['instrument_type']=proof['instrument_type'];result['instrument_type_at']=datetime.fromtimestamp(proof['at'],timezone.utc).isoformat()
  if any(p['quantity'] is None for p in found):return unknown_context('HOLDING_QUANTITY_MISSING')
  if any(p.get('ticker') and p['ticker'].casefold()!=request['ticker'].casefold() for p in found):raise DataUnavailable('PLUTO_ASSET_NOT_CONFIRMED')
  if any(Decimal(p['quantity'])<0 for p in found):raise DataUnavailable('PLUTO_SHORT_POSITION_NOT_SUPPORTED')
  quantity=sum((Decimal(p['quantity']) for p in found),Decimal(0))
  observed=[p['observed'] for p in rows]+([datetime.fromtimestamp(tradability_at,timezone.utc).isoformat()] if tradability_at is not None else [])
  result.update(status='verified',as_of=min(observed,key=stamp),position='held' if quantity>0 else 'none',quantity=format(quantity,'f'),fx_to_dkk='1' if currency=='DKK' else None)
  if len(found)==1 and found[0].get('average_entry',{}).get('currency')==currency:result['cost_price']=found[0]['average_entry']['amount']
  # A Pluto main portfolio already includes its collections. Only exclude a
  # collection when its parent is present; standalone scopes remain included.
  parent_ids={p['external_id'] for p in portfolios if p.get('kind')=='portfolio'}
  values=[(snapshot.get('value') or {}).get('value') for p,snapshot in zip(portfolios,rows) if not (p.get('kind')=='collection' and p.get('parent_external_id') in parent_ids)]
  if values and all(v and v['amount'] is not None and v['currency']=='DKK' for v in values):result['portfolio_equity_dkk']=format(sum(Decimal(v['amount']) for v in values),'f')
  exposures=[p.get('value_in_portfolio_currency') for p in found]
  if not found:result['exposure_dkk']='0'
  elif all(v and v['amount'] is not None and v['currency']=='DKK' for v in exposures):result['exposure_dkk']=format(sum(Decimal(v['amount']) for v in exposures),'f')
  # Existing broker snapshots only prove the order rows actually received.
  for payload in rows:
   for o in payload.get('pending_orders',[])+payload.get('unconfirmed_orders',[]):
    if o.get('ticker','').casefold()==request['ticker'].casefold() and o.get('key') and o.get('verified_id'):
     result['orders'].append({'order_id':o['key'].replace('order:','').replace('trade:',''),'status':o['status'],'requested_quantity':o.get('requested_quantity'),'filled_quantity':o.get('filled_quantity'),'side':o.get('side') if o.get('side') in ['BUY','SELL'] else None})
  result['orders_complete']=False
  if not request.get('is_test') and request.get('watch_mode')=='entry':
   import hotwatch_buy_plan
   try:hotwatch_buy_plan.refresh(self.connect,self.uid,request,self.factory)
   except Exception:pass  # Expired/missing evidence remains blocked centrally.
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
   cache_key=(p['id'],p.get('external_id'),p.get('parent_external_id'),p.get('kind'));cached=self.order_cache.get(cache_key)
   if not cached or now-cached['at']>=300:
    parent=p['external_id'] if p['kind']=='portfolio' else p['parent_external_id']
    if not parent:continue
    cl=self.factory(oauth.access_token(self.connect,self.uid));tools={t['name']:t for t in cl.tools()}
    raw=trade_service.call(cl,tools,'list_orders',{'portfolioId':parent.split(':',1)[1],'statusGroup':'INACTIVE','scope':'DIRECT' if p['kind']=='portfolio' else 'COLLECTION','limit':50})
    rows=portfolio_data.list_data(raw,['orders','items','data']);cached={'at':now,'rows':rows[:50]};self.order_cache[cache_key]=cached
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
  with self.context_lock:return self._poll(session)
 def _poll(self,session):
  import market_data
  r=session['request_data']
  if r['report_id']=='manual-pluto':
   import trade_service
   client,tools=trade_service.client(self.connect,self.uid,self.factory)
   q=market_data.normalized(trade_service.call(client,tools,'get_asset',{'assetId':r['asset_id'],'period':'ONE_WEEK'}),r['asset_id'])
  elif r['report_id']=='automatic-holdings' and len(r['portfolio_ids'])==1:
   q=market_data.quote(self.connect,self.uid,{'holding_portfolio_id':r['portfolio_ids'][0],'holding_asset_id':r['asset_id']},factory=self.factory)
  else:q=market_data.quote(self.connect,self.uid,{'report_id':r['report_id'],'candidate_id':r['candidate_id'],'is_test':r['is_test'],'asset_id':r['asset_id']},factory=self.factory)
  if q.get('pending'):raise DataUnavailable('PLUTO_REQUEST_PENDING')
  if q.get('selection_required') or q.get('asset_id')!=r['asset_id'] or str(q.get('ticker','')).casefold()!=r['ticker'].casefold():raise DataUnavailable('PLUTO_ASSET_NOT_CONFIRMED')
  if q.get('last_error'):raise DataUnavailable('PLUTO_PROVIDER_ERROR')
  context=self.safe_context(r,q['currency'])
  if not q.get('price_time'):
   error=DataUnavailable('PLUTO_QUOTE_TIME_UNKNOWN');error.position_context=context
   if q.get('price') is not None and q.get('currency')==r.get('quote_currency'):
    error.partial_observation={'source':'pluto','price':q['price'],'currency':q['currency'],'source_time':None,'received_at':q.get('fetched_at'),'quality':'TIME_UNKNOWN'}
   raise error
  at=stamp(q['price_time'])
  return {'sample_id':'pluto-'+hashlib.sha256((r['asset_id']+q['price_time']).encode()).hexdigest()[:32],'source':'pluto','ticker':r['ticker'],'asset_id':r['asset_id'],'venue':q.get('exchange'),'currency':q['currency'],'event_time':q['price_time'],'session_key':at.date().isoformat()+':UNKNOWN','market_status':'UNKNOWN','feed_type':'Pluto get_asset price; cadence/session unconfirmed','documented_delay_s':None,'verification':'verified','error_code':None,'interval_s':300,'price':q['price'],'bid':None,'ask':None,'volume':None,'volume_type':'unknown','open':None,'high':None,'low':None,'close':None,'context':context}

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def extended_session(trade,schedule,now,max_age_s):
 """Classify an explicitly extended-hours trade using a verified exchange calendar."""
 from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
 try:
  if trade.get('market_session') not in ('extended-hours','extended hours') or schedule.get('status')!='OK' or schedule.get('exchange_open') is not False:return None
  received=stamp(schedule['received_at']);at=stamp(trade['event_time'])
  if not 0<=(now-received).total_seconds()<=max_age_s or not 0<=(now-at).total_seconds()<=max_age_s:return None
  zone=ZoneInfo(schedule['timezone']);local=at.astimezone(zone);calendar=schedule['calendar']
  opening=datetime.strptime(calendar['open'],'%H:%M:%S').time();closing=datetime.strptime(calendar['close'],'%H:%M:%S').time()
  weekday=('Mon','Tue','Wed','Thu','Fri','Sat','Sun')[local.weekday()]
  if opening>=closing or received.astimezone(zone).date()!=local.date() or weekday not in calendar['working_days'] or local.date().isoformat() in calendar['excluded_dates']:return None
  return 'PRE' if local.time()<opening else 'AFTER' if local.time()>=closing else None
 except (KeyError,ValueError,TypeError,ZoneInfoNotFoundError):return None

def realtime_symbol(symbol):
 """Translate only observed feed spellings; keep REST/security IDs unchanged."""
 # Direct trades, quotes and minute history verified 2026-11-09. The US
 # catalog identifies BRK-B.US, while all three real-time feeds emit BRK.B.
 if symbol=='BRK-B.US':return 'BRK.B'
 return symbol[:-3] if symbol.endswith('.US') else symbol

class EODHDAdapter:
 def __init__(self,connect,uid,opener=None):self.connect=connect;self.uid=uid;self.opener=opener or urllib.request.build_opener(NoRedirect());self._shared_quotes=opener is None;self.pluto=PlutoAdapter(connect,uid);self.last_telemetry={};self.last_partial_observations=[]
 def interval(self,request,profile):
  if self.connect is None:return max(PROFILES.get(profile,PROFILES[request['profile']]),provider_floor('eodhd'))
  with self.connect() as c:return effective_poll_interval(c,request,profile)
 def feeds(self,request=None):
  from eodhd_feeds import EODHDFeeds
  return EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),capacity=Capacity(self.connect,'essential' if request and (request.get('watch_mode')=='exit' or request.get('priority') in ('HIGH','CRITICAL')) else 'routine') if self.connect else None,opener=self.opener,share_status=self._shared_quotes)
 def market_status(self,client,exchange,max_age):
  """Reuse the maintenance worker's same-response evidence without refreshing its age."""
  if self.connect is not None:
   with self.connect() as c:
    row=c.execute('SELECT s.received,s.is_open,c.received AS calendar_received,c.timezone,c.calendar FROM hw_exchange_status s JOIN hw_exchange_calendar c ON c.exchange=s.exchange WHERE s.exchange=?',(exchange,)).fetchone()
   if row and row['received']==row['calendar_received'] and row['is_open'] in (0,1):
    try:
     if 0<=(utc()-stamp(row['received'])).total_seconds()<=max_age:
      calendar=json.loads(row['calendar'])
      if isinstance(calendar,dict) and isinstance(row['timezone'],str):return {'status':'OK','exchange':exchange,'exchange_open':bool(row['is_open']),'received_at':row['received'],'timezone':row['timezone'],'calendar':calendar}
    except (ValueError,TypeError,KeyError):pass
  return client.market_status(exchange)
 def capture(self,client,feed,symbol,session):
  """Share one bounded stream across due, independently verified watches."""
  req=session['request_data'];capture_started=time.monotonic()
  def record(value,symbols,reused):
   if not hasattr(self,'capture_metrics'):self.capture_metrics=[]
   messages=value.get('messages',[]);latest=max(messages,key=lambda m:stamp(m['event_time'])) if messages else {}
   age=(utc()-stamp(latest['event_time'])).total_seconds() if latest.get('event_time') else None
   received_age=(utc()-stamp(latest['received_at'])).total_seconds() if latest.get('received_at') else None
   self.capture_metrics.append({'source_age_s':round(age,3) if age is not None else None,'received_age_s':round(received_age,3) if received_age is not None else None,'feed':feed,'subscriptions_sent':0 if reused else value.get('subscriptions_sent'),'connections_opened':0 if reused else value.get('connections_opened'),'batch_symbols':symbols,'capture_attempts':0 if reused else 1,'cache_hit':reused and value.get('status')!='COLLECTING','status':value.get('status'),'wait_ms':round((time.monotonic()-capture_started)*1000,3),'messages':len(value.get('messages',[]))})
   return value
  if not self._shared_quotes or self.connect is None or session.get('id') is None or req.get('is_test'):
   return record(client.capture(feed,symbol,duration=2),1,False)
  credential=hashlib.sha256(os.environ.get('ESCAPE_EODHD_API_KEY','').strip().encode()).digest()
  profile=json.loads(session.get('state') or '{}').get('adaptive_profile') or req['profile']
  key=(self.uid,credential,feed,symbol)
  group=(self.uid,credential,feed)
  def reusable(cached,request,profile,allow_older=False):
   if not cached:return False
   value=cached[1];age=time.monotonic()-cached[0]
   max_age=min(request['risk']['max_quote_age_s'],GLOBAL_RISK['max_quote_age_s'])
   fresh=any(m.get('event_time') and 0<=(utc()-stamp(m['event_time'])).total_seconds()<=max_age for m in value.get('messages',[]))
   # A capture that already returned only old trades/quotes is also a recent
   # availability check. Share that negative result like NO_MESSAGES. Data
   # which was fresh when captured but has since expired must be refetched.
   captured=value.get('captured_at');messages=value.get('messages',[])
   already_stale=bool(captured and messages and value.get('status')=='OK' and all(m.get('event_time') and (stamp(captured)-stamp(m['event_time'])).total_seconds()>max_age for m in messages))
   interval=PROFILES.get(profile,60)
   # Share fresh observations for the requesting profile's existing cadence.
   # Empty/status responses keep their short response cache; neither cache
   # duration nor reuse changes a market event's original timestamp.
   # Trade refresh cadence is unchanged, including in extended hours. Only
   # repeat empty/stale quote lookups less often on slower profiles.
   negative_ttl=min(30,interval) if feed.endswith('_quotes') else min(20,interval)
   return (fresh and 0<=age<interval) or (0<=age<negative_ttl and (already_stale or value.get('status')=='NO_MESSAGES' or feed.endswith('_status') and value.get('status')=='OK')) or (allow_older and age>=0 and fresh)
  with _ws_batch_lock:
   cached=_ws_batch_cache.get(key);collecting=group in _ws_batch_inflight
   # A running capture must not tie up both workers. A still-fresh observation
   # can be analysed immediately, with its original source/receive timestamps.
   if reusable(cached,req,profile,allow_older=collecting):return record(copy.deepcopy(cached[1]),0,True)
   if collecting:
    self.pending_feed=_ws_batch_inflight[group]
    return record({'status':'COLLECTING','messages':[]},0,True)
   completed=threading.Event();_ws_batch_inflight[group]=completed
  try:
   # Fill the existing batch with due watches that lack a reusable response.
   # Do not spend its ten slots repeatedly subscribing to already cached data.
   market='us' if feed.startswith('us_') else 'eu';symbols=[symbol]
   allowed_eu={x.strip().upper() for x in os.environ.get('ESCAPE_HW_EODHD_WS_EU_EXCHANGES','CO,XETRA,AS').split(',') if re.fullmatch(r'[A-Za-z0-9_-]{1,16}',x.strip())}
   from hotwatch_engine import verified_automatic_feed,capacity
   with self.connect() as c:
    rows=c.execute("SELECT s.request,s.state FROM hw_sessions s LEFT JOIN hw_control k ON k.user_id=s.user_id WHERE s.user_id=? AND s.is_test=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND COALESCE(k.killed,0)=0 AND s.next_due<=? AND json_extract(s.request,'$.provider')='eodhd' ORDER BY s.next_due,CASE WHEN json_extract(s.request,'$.watch_mode')='exit' THEN 0 ELSE 1 END,s.id LIMIT ?",(self.uid,utc().timestamp()+15,capacity())).fetchall()
    for row in rows:
     candidate=json.loads(row['request']);full=candidate.get('provider_symbol') or ''
     if not isinstance(full,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',full):continue
     if (market=='us')!=full.endswith('.US') or (market=='eu' and ('.' not in full or full.rsplit('.',1)[1].upper() not in allowed_eu)):continue
     stream=realtime_symbol(full)
     candidate_profile=json.loads(row['state'] or '{}').get('adaptive_profile') or candidate['profile']
     with _ws_batch_lock:
      if reusable(_ws_batch_cache.get((self.uid,credential,feed,stream)),candidate,candidate_profile):continue
     if not verified_automatic_feed(c,self.uid,candidate,utc()):continue
     if stream not in symbols:symbols.append(stream)
     if len(symbols)>=10:break

   result=client.capture(feed,symbols if len(symbols)>1 else symbol,duration=2,max_messages=250 if len(symbols)>1 else 50)
   if result.get('status') not in ('OK','NO_MESSAGES'):return record(result,len(symbols),False)
   with _ws_batch_lock:
    if len(_ws_batch_cache)>=512:_ws_batch_cache.clear()
    saved=time.monotonic();captured_at=utc().isoformat()
    for item in symbols:
     messages=[m for m in result.get('messages',[]) if m.get('symbol')==item]
     # A quiet capture must not erase a more recent, still-valid observation
     # from another batch. Keep original event/receive times and feed identity;
     # the requesting session applies its own freshness limit in poll().
     prior=_ws_batch_cache.get((self.uid,credential,feed,item))
     if prior:
      retained=[m for m in prior[1].get('messages',[]) if m.get('event_time') and 0<=(utc()-stamp(m['event_time'])).total_seconds()<=GLOBAL_RISK['max_quote_age_s']]
      if retained:
       latest=max(retained,key=lambda m:stamp(m['event_time']))
       prior_time=stamp(latest['event_time']);new_time=max((stamp(m['event_time']) for m in messages),default=None)
       if not new_time or prior_time>new_time:
        messages=[m for m in retained if stamp(m['event_time'])==prior_time] if feed.endswith('_quotes') else [latest]
       elif feed.endswith('_quotes') and prior_time==new_time:
        # Equal source times cannot order different quotes, even when they
        # arrived in separate batches. Retain distinct quotes at that instant
        # so poll() can reject an ambiguous spread; bound identical repeats.
        candidates=[m for m in retained+messages if stamp(m['event_time'])==new_time];seen=set();messages=[]
        for candidate in candidates:
         try:quote=(Decimal(str(candidate.get('bid'))),Decimal(str(candidate.get('ask'))))
         except (InvalidOperation,TypeError,ValueError):continue
         if not all(v.is_finite() for v in quote) or quote[0]<=0 or quote[1]<quote[0]:continue
         if quote not in seen:messages.append(candidate);seen.add(quote)
         if len(messages)==2:break
        if not messages:messages=candidates[-1:]
     partial=[m for m in result.get('partial_messages',[]) if m.get('symbol')==item]
     value={**result,'status':'OK' if messages else 'NO_MESSAGES','messages':messages,'message_count':len(messages),'partial_messages':partial,'captured_at':captured_at}
     _ws_batch_cache[(self.uid,credential,feed,item)]=(saved,copy.deepcopy(value))
    # Diagnose the requested symbol, not the newest unrelated trade in its
    # batch. Connection/subscription counts still describe the actual call.
    return record(copy.deepcopy(_ws_batch_cache[key][1]),len(symbols),False)
  finally:
   with _ws_batch_lock:
    _ws_batch_inflight.pop(group,None)
    completed.set()

 def poll(self,session):
  self.last_partial_observations=[];self.capture_metrics=[];self.pending_feed=None;self.last_feed_diagnostics={};self.last_telemetry={}
  if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1':raise DataUnavailable('EODHD_FEED_NOT_ENABLED')
  key=os.environ.get('ESCAPE_EODHD_API_KEY','').strip()
  if not key:raise DataUnavailable('EODHD_KEY_NOT_CONFIGURED')
  r=session['request_data'];symbol=r.get('provider_symbol')
  try:scan_state=json.loads(session.get('state') or '{}')
  except (ValueError,TypeError):scan_state={}
  priority_request=dict(r)
  if scan_state.get('adaptive_profile')=='CRITICAL' or isinstance(scan_state.get('catalyst_priority_until'),(int,float)) and scan_state['catalyst_priority_until']>utc().timestamp():priority_request['priority']='CRITICAL'
  if not symbol:raise DataUnavailable('EODHD_SYMBOL_MAPPING_REQUIRED')
  if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',symbol):raise DataUnavailable('EODHD_SYMBOL_MAPPING_REQUIRED')
  cxe_valid=None;automatic_missing=False
  if self.connect is not None:
   with self.connect() as c:
    cxe_valid=valid_cxe_evidence(c,self.uid,r,utc())
    if not r.get('is_test') and r.get('purpose') in ('automatic discovery','automatic holding watch'):
     from hotwatch_engine import verified_automatic_feed,capacity
     automatic_missing=not verified_automatic_feed(c,self.uid,r,utc())
  from instrument_resolver import BTC_PLUTO_ASSET_ID,PEPE_PLUTO_ASSET_ID
  if r.get('asset_id')==PEPE_PLUTO_ASSET_ID:raise DataUnavailable('EODHD_INSTRUMENT_UNVERIFIED')
  if cxe_valid is False or r.get('asset_id')==BTC_PLUTO_ASSET_ID and cxe_valid is not True:
   failure=DataUnavailable('EODHD_INSTRUMENT_REVALIDATION_REQUIRED')
   failure.position_context=self.pluto.safe_context(r,r.get('quote_currency'))
   raise failure
  self.last_feed_diagnostics={};self.last_telemetry={}
  provisional=None
  if session.get('id') is not None:
   with self.connect() as c:provisional=c.execute('SELECT symbol FROM hw_provisional_feed_links WHERE watch_row_id=?',(session['id'],)).fetchone()
  if provisional:
   failure=DataUnavailable('EODHD_INSTRUMENT_UNVERIFIED')
   failure.position_context=self.pluto.safe_context(r,r.get('quote_currency'))
   raise failure
  if automatic_missing:
   failure=DataUnavailable('EODHD_INSTRUMENT_REVALIDATION_REQUIRED')
   failure.position_context=self.pluto.safe_context(r,r.get('quote_currency'))
   raise failure
  # Explicit opt-in: one bounded live trade capture. If unavailable, use the
  # unchanged REST adapter. No inferred venue/session or fabricated bid/ask.
  exchange=symbol.rsplit('.',1)[1].upper() if '.' in symbol else ''
  eu_exchanges={x.strip().upper() for x in os.environ.get('ESCAPE_HW_EODHD_WS_EU_EXCHANGES','CO,XETRA,AS').split(',') if re.fullmatch(r'[A-Za-z0-9_-]{1,16}',x.strip())}
  # CC is EODHD's virtual crypto market, not a supported EU equity stream.
  eu_exchanges.discard('CC')
  if os.environ.get('ESCAPE_HW_EODHD_WS_TRADES_ENABLED')=='1' and exchange and exchange!='US' and exchange not in eu_exchanges:self.last_feed_diagnostics={'websocket_trade_status':'MARKET_MAPPING_UNVERIFIED'}
  if os.environ.get('ESCAPE_HW_EODHD_WS_TRADES_ENABLED')=='1' and (exchange=='US' or exchange in eu_exchanges):
   market='us' if exchange=='US' else 'eu';stream_symbol=realtime_symbol(symbol)
   # Complete slow broker refreshes before acquiring the actionable trade.
   # This prevents a fresh source observation aging in a broker/network queue.
   context_started=time.perf_counter();context=self.pluto.safe_context(r,r.get('quote_currency'));context_ms=(time.perf_counter()-context_started)*1000
   client=self.feeds(priority_request);stream_started=time.perf_counter();feed=self.capture(client,market+'_trades',stream_symbol,session);stream_ms=(time.perf_counter()-stream_started)*1000
   partial=feed.get('partial_messages',[])
   if partial:
    item=partial[-1];self.last_partial_observations.append({'source':'eodhd','price':item.get('price'),'currency':r.get('quote_currency'),'source_time':None,'received_at':item.get('received_at'),'quality':'TIME_UNKNOWN','trade_size':item.get('trade_size')})
   self.last_feed_diagnostics={'websocket_trade_status':feed['status']}
   if feed['status']=='COLLECTING':
    failure=DataUnavailable('FEED_COLLECTING');failure.feed_ready=self.pending_feed;raise failure
   if feed['status']=='LOCAL_BUDGET_EXHAUSTED':raise local_budget_error(feed)
   if feed['status']=='RATE_LIMIT':
    failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=feed.get('retry_after_s') or retry_seconds(None);raise failure
   valid=[x for x in feed.get('messages',[]) if stamp(x['event_time'])<=utc() and (utc()-stamp(x['event_time'])).total_seconds()<=r['risk']['max_quote_age_s']] if feed['status']=='OK' else []
   if feed['status'] in ('OK','NO_MESSAGES') and not valid and os.environ.get('ESCAPE_HW_EODHD_FUSE_ENABLED')=='1':
    standalone=self.capture(client,market+'_quotes',stream_symbol,session)
    self.last_feed_diagnostics['websocket_quote_status']=standalone.get('status')
    if standalone.get('status')=='COLLECTING':
     failure=DataUnavailable('FEED_COLLECTING');failure.feed_ready=self.pending_feed;raise failure
    if standalone.get('status')=='RATE_LIMIT':
     failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=standalone.get('retry_after_s') or retry_seconds(None);raise failure
    quotes=standalone.get('messages',[]);partial_quotes=standalone.get('partial_messages',[])
    if quotes:
     item=max(quotes,key=lambda x:stamp(x['event_time']))
     if item.get('bid') is not None or item.get('ask') is not None:self.last_partial_observations.append({'source':'eodhd','price':None,'currency':r.get('quote_currency'),'source_time':item['event_time'],'received_at':item.get('received_at'),'quality':'TRADE_MISSING','bid':item.get('bid'),'ask':item.get('ask')})
    elif partial_quotes:
     item=partial_quotes[-1];self.last_partial_observations.append({'source':'eodhd','price':None,'currency':r.get('quote_currency'),'source_time':None,'received_at':item.get('received_at'),'quality':'TIME_UNKNOWN','bid':item.get('bid'),'ask':item.get('ask')})
   if feed['status']=='OK':
    if not valid:self.last_feed_diagnostics['websocket_trade_status']='STALE_OR_FUTURE'
    if valid:
     trade=max(valid,key=lambda x:stamp(x['event_time']));at=stamp(trade['event_time']);currency=r.get('quote_currency')
     if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):raise DataUnavailable('EODHD_CURRENCY_UNCONFIRMED')
     self.last_telemetry={'websocket_capture_ms':round(stream_ms,3),'pluto_context_ms':round(context_ms,3),'event_to_websocket_receive_ms':round((stamp(trade['received_at'])-at).total_seconds()*1000,3) if trade.get('received_at') else None}
     state=json.loads(session.get('state') or '{}');profile=state.get('adaptive_profile') or r['profile']
     interval=self.interval(r,profile)
     sample={'sample_id':'eodhd-ws-'+hashlib.sha256((symbol+trade['event_time']).encode()).hexdigest()[:28],'source':'eodhd','ticker':r['ticker'],'asset_id':r['asset_id'],'venue':None,'currency':currency,'event_time':trade['event_time'],'session_key':at.date().isoformat()+':UNKNOWN','market_status':'UNKNOWN','feed_type':'EODHD WebSocket '+market+' trade; venue not supplied; not necessarily consolidated','documented_delay_s':None,'verification':'verified','error_code':None,'interval_s':interval,'price':trade['price'],'trade_size':trade.get('trade_size'),'bid':None,'ask':None,'volume':None,'volume_type':'unknown','open':None,'high':None,'low':None,'close':None,'context':context,'price_time_kind':'trade'}
     if trade.get('market_session')=='closed':sample.update(market_status='CLOSED',session_key=at.date().isoformat()+':CLOSED',status_at=trade['event_time'],status_feed=market+'_trades')
     if trade.get('market_session')=='open':sample.update(market_status='REGULAR',session_key=at.date().isoformat()+':REGULAR',status_at=trade['event_time'],status_feed=market+'_trades')
     if os.environ.get('ESCAPE_HW_EODHD_FUSE_ENABLED')=='1':
      quote_feed=self.capture(client,market+'_quotes',stream_symbol,session)
      partial_quotes=quote_feed.get('partial_messages',[])
      if partial_quotes:
       item=partial_quotes[-1];self.last_partial_observations.append({'source':'eodhd','price':None,'currency':r.get('quote_currency'),'source_time':None,'received_at':item.get('received_at'),'quality':'TIME_UNKNOWN','bid':item.get('bid'),'ask':item.get('ask')})
      if quote_feed['status']=='LOCAL_BUDGET_EXHAUSTED':
       self.last_feed_diagnostics['websocket_quote_status']='LOCAL_BUDGET_EXHAUSTED';return sample
      status_feed=self.capture(client,market+'_status',stream_symbol,session) if quote_feed['status'] not in ('RATE_LIMIT','COLLECTING') else {'status':quote_feed['status']}
      self.last_feed_diagnostics.update(websocket_quote_status=quote_feed['status'],websocket_status_status=status_feed['status'])
      now=utc();max_age=r['risk']['max_quote_age_s']
      fresh=lambda item:bool(item.get('event_time') and 0<=(now-stamp(item['event_time'])).total_seconds()<=max_age)
      quotes=[x for x in quote_feed.get('messages',[]) if fresh(x) and x.get('bid') and x.get('ask') and Decimal(x['bid'])>0 and Decimal(x['ask'])>=Decimal(x['bid'])]
      if quotes:
       latest=max(stamp(q['event_time']) for q in quotes);same_time=[q for q in quotes if stamp(q['event_time'])==latest]
       if len({(Decimal(q['bid']),Decimal(q['ask'])) for q in same_time})==1:
        q=same_time[0];sample.update(bid=q['bid'],ask=q['ask'],bid_at=q['event_time'],ask_at=q['event_time'],quote_feed=market+'_quotes')
       else:
        # Equal provider timestamps do not establish quote ordering. Keep the
        # independently timed trade but do not invent a tradable spread.
        sample.update(bid=None,ask=None,bid_at=same_time[0]['event_time'],ask_at=same_time[0]['event_time'],quote_feed=None)
        self.last_feed_diagnostics['websocket_quote_status']='AMBIGUOUS_SAME_TIMESTAMP'
      # A subsequent quote/status failure must not discard an already
      # received trade. Missing evidence remains unknown and cannot permit BUY.
      if quote_feed['status']=='RATE_LIMIT' or status_feed['status'] in ('RATE_LIMIT','LOCAL_BUDGET_EXHAUSTED'):return sample
      statuses=[x for x in status_feed.get('messages',[]) if fresh(x) and x.get('trading_status')]
      if statuses and trade.get('market_session')=='open':
       status=max(statuses,key=lambda x:stamp(x['event_time']))
       if status['trading_status']=='T':sample.update(market_status='REGULAR',session_key=at.date().isoformat()+':REGULAR',status_at=status['event_time'],status_feed=market+'_status')
       else:sample.update(market_status='UNKNOWN',session_key=at.date().isoformat()+':UNKNOWN');sample.pop('status_at',None);sample.pop('status_feed',None)
      if sample['market_status']=='UNKNOWN' and trade.get('market_session') in ('extended-hours','extended hours') and (not statuses or max(statuses,key=lambda x:stamp(x['event_time']))['trading_status']=='T'):
       schedule=self.market_status(client,exchange,max_age);self.last_feed_diagnostics['exchange_status']=schedule['status']
       if schedule['status']=='RATE_LIMIT':return sample
       phase=extended_session(trade,schedule,utc(),max_age)
       if phase:
        # After-hours trading can cross midnight UTC while remaining on the
        # same exchange-local trading day. Do not split its warmup history.
        from zoneinfo import ZoneInfo
        local_day=at.astimezone(ZoneInfo(schedule['timezone'])).date().isoformat()
        sample.update(market_status=phase,session_key=local_day+':'+phase,status_at=trade['event_time'],status_feed=market+'_trades')
      if sample['market_status'] in ('REGULAR','PRE','AFTER') and os.environ.get('ESCAPE_HW_EODHD_BARS_ENABLED')=='1':
       schedule=self.market_status(client,exchange,max_age);self.last_feed_diagnostics['exchange_status']=schedule['status']
       if schedule['status']=='LOCAL_BUDGET_EXHAUSTED':return sample
       if schedule['status']=='RATE_LIMIT':return sample
       if schedule.get('status')=='OK' and schedule.get('exchange_open') is (sample['market_status']=='REGULAR') and schedule.get('calendar') and schedule.get('timezone'):
        bars=client.minute_bars(market,stream_symbol);self.last_feed_diagnostics['minute_bars_status']=bars['status']
        if bars['status']=='LOCAL_BUDGET_EXHAUSTED':return sample
        if bars['status']=='RATE_LIMIT':return sample
        if bars['status']=='OK':
         try:
          from zoneinfo import ZoneInfo
          from hotwatch_features import verified_bar_samples
          zone=ZoneInfo(schedule['timezone']);local=at.astimezone(zone);calendar=schedule['calendar'];start=datetime.strptime(calendar['open'],'%H:%M:%S').time();end=datetime.strptime(calendar['close'],'%H:%M:%S').time()
          same_session=[]
          for bar in bars.get('bars',[]):
           opened=stamp(bar['bar_open_at']);closed=opened+timedelta(seconds=60);lo=opened.astimezone(zone);lc=closed.astimezone(zone)
           phase=sample['market_status'];in_phase=lambda t:(start<=t<end) if phase=='REGULAR' else (t<start if phase=='PRE' else t>=end)
           if lo.date()==local.date()==lc.date() and in_phase(lo.time()) and in_phase((closed-timedelta(microseconds=1)).astimezone(zone).time()) and closed<=at:
            same_session.append({k:bar[k] for k in ('bar_open_at','open','high','low','close','volume')})
          evidence={'provider_symbol':symbol,'market':market,'exchange':exchange,'timezone':schedule['timezone'],'session_date':local.date().isoformat(),'open':calendar['open'],'close':calendar['close'],'working_days':calendar['working_days'],'excluded_dates':calendar['excluded_dates'],'schedule_received_at':schedule['received_at'],'exchange_open':schedule['exchange_open'],'feed':'eodhd_realtime_history'}
          if same_session:
           sample.update(bar_history=same_session[-120:],bar_evidence=evidence)
           if verified_bar_samples(sample,r,utc()) is None:self.last_feed_diagnostics['bar_history_status']='EVIDENCE_UNVERIFIED'
           else:self.last_feed_diagnostics['bar_history_status']='VERIFIED'
          else:self.last_feed_diagnostics['bar_history_status']='NO_COMPARABLE_BARS'
         except (KeyError,ValueError,TypeError,ArithmeticError):self.last_feed_diagnostics['bar_history_status']='EVIDENCE_UNVERIFIED'
       else:self.last_feed_diagnostics['bar_history_status']='SCHEDULE_UNVERIFIED'
     return sample
  # Bar open times and close prices are recorded as such; never pretend that
  # the bar timestamp is the timestamp of its final trade.
  if os.environ.get('ESCAPE_HW_EODHD_BARS_ENABLED')=='1' and (exchange=='US' or exchange in eu_exchanges):
   market='us' if exchange=='US' else 'eu';stream_symbol=realtime_symbol(symbol);client=self.feeds(priority_request);bars=client.minute_bars(market,stream_symbol);kind='realtime'
   self.last_feed_diagnostics['minute_bars_status']=bars['status']
   if bars['status']=='LOCAL_BUDGET_EXHAUSTED':raise local_budget_error(bars)
   if bars['status']=='RATE_LIMIT':
    failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=bars.get('retry_after_s') or retry_seconds(None);raise failure
   if bars['status']!='OK':
    end=int(utc().timestamp());start=end-86400
    # Only bars at or after the already journalled observation can be used
    # below. Request a one-minute overlap for boundary/rounding safety.
    try:
     if session.get('last_data'):
      last=stamp(session['last_data']).timestamp()
      if last<=end:start=max(start,int(last)-60)
    except (ValueError,TypeError,AttributeError,OverflowError):pass
    # Reuse only a short, genuinely empty response while the verified
    # calendar permits conservative polling. Wake/open, a new trade or a
    # changed last observation immediately bypasses this negative cache.
    quiet=False
    if self.connect is not None:
     try:
      from hotwatch_engine import quiet_market_interval
      profile=scan_state.get('adaptive_profile') or r['profile'];base=self.interval(r,profile)
      with self.connect() as c:quiet=quiet_market_interval(c,r,profile,utc(),base)>base
     except (KeyError,TypeError,ValueError):pass
    bars,reused=quiet_intraday_lookup(key,symbol,session.get('last_data'),quiet,lambda:client.intraday(symbol,start=start,end=end))
    if reused:self.last_feed_diagnostics['intraday_cache_hit']=True
    kind='intraday';self.last_feed_diagnostics['intraday_status']=bars['status']
    if bars['status']=='LOCAL_BUDGET_EXHAUSTED':raise local_budget_error(bars)
    if bars['status']=='RATE_LIMIT':
     failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=bars.get('retry_after_s') or retry_seconds(None);raise failure
   if bars['status']=='OK':
    closed=[b for b in bars.get('bars',[]) if b.get('bar_open_at') and stamp(b['bar_open_at'])+timedelta(seconds=60)<=utc() and b.get('close') and Decimal(b['close'])>0 and (not session.get('last_data') or stamp(b['bar_open_at'])>=stamp(session['last_data']))]
    if closed:
     bar=max(closed,key=lambda b:stamp(b['bar_open_at']));at=stamp(bar['bar_open_at']);currency=r.get('quote_currency')
     if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):raise DataUnavailable('EODHD_CURRENCY_UNCONFIRMED')
     sample_id='eodhd-bar-'+hashlib.sha256((kind+symbol+bar['bar_open_at']).encode()).hexdigest()[:27];old=None
     if session.get('id') is not None:
      with self.connect() as c:old=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? AND source=? AND sample_id=?',(session['id'],'eodhd',sample_id)).fetchone()
     if old:
      previous=json.loads(old['payload']);previous['context']=self.pluto.safe_context(r,currency);return previous
     if not session.get('last_data') or at>stamp(session['last_data']):
      context=self.pluto.safe_context(r,currency)
      return {'sample_id':sample_id,'source':'eodhd','ticker':r['ticker'],'asset_id':r['asset_id'],'venue':None,'currency':currency,'event_time':bar['bar_open_at'],'session_key':at.date().isoformat()+':UNKNOWN','market_status':'UNKNOWN','feed_type':'EODHD '+kind+' closed 1m bar; time is bar open','documented_delay_s':None,'verification':'verified','error_code':None,'interval_s':60,'price':bar['close'],'bid':None,'ask':None,'volume':bar.get('volume'),'volume_type':'interval','open':bar['open'],'high':bar['high'],'low':bar['low'],'close':bar['close'],'context':context,'price_time_kind':'bar_open'}
  # Exchange is an explicit EODHD code, not inferred from a display name.
  self.last_telemetry={}
  def fetch_quote():
   url='https://eodhd.com/api/real-time/'+quote(symbol,safe='')+'?'+urlencode({'api_token':key,'fmt':'json'});http_started=time.perf_counter()
   try:
    with Capacity(self.connect,'essential' if priority_request.get('watch_mode')=='exit' or priority_request.get('priority') in ('HIGH','CRITICAL') else 'routine').open(self.opener,urllib.request.Request(url,headers={'Accept':'application/json'})) as response:
     raw=response.read(131073)
     if len(raw)>131072:raise ValueError()
     received=utc();http_ms=(time.perf_counter()-http_started)*1000
     d=json.loads(raw,parse_float=str)
    permitted_codes=[symbol,symbol.rsplit('.',1)[0]]+([] if symbol.upper().endswith('.CC') else [r['ticker']])
    if not isinstance(d,dict) or d.get('code') not in permitted_codes or not isinstance(d.get('timestamp'),(int,str)) or type(d.get('timestamp')) is bool:raise ValueError()
    at=datetime.fromtimestamp(int(d['timestamp']),timezone.utc);price=Decimal(str(d['close']))
    if not price.is_finite() or price<=0:raise ValueError()
    return d,received,http_ms,at,price
   except urllib.error.HTTPError as error:
    if error.code==429:
     failure=DataUnavailable('EODHD_RATE_LIMIT',429)
     failure.retry_after_s=retry_seconds(error.headers)
     raise failure from None
    raise DataUnavailable('EODHD_ENTITLEMENT_REJECTED' if error.code in [401,403] else 'EODHD_READ_ERROR') from None
   except EngineError:raise
   except Exception:raise DataUnavailable('EODHD_READ_OR_CONTRACT_ERROR') from None
  d,received,http_ms,at,price=shared_quote(key,symbol,fetch_quote,self._shared_quotes)
  permitted_codes=[symbol,symbol.rsplit('.',1)[0]]+([] if symbol.upper().endswith('.CC') else [r['ticker']])
  if d.get('code') not in permitted_codes:raise DataUnavailable('EODHD_READ_OR_CONTRACT_ERROR')
  # A fallback snapshot can be older than a trade or bar already journalled.
  # Treat it as stale rather than attempting to rewrite market history.
  if session.get('last_data') and at<stamp(session['last_data']):
   failure=DataUnavailable('DATA_STALE')
   # A stale market observation must not prevent an independent, verified
   # Pluto holding check. The runner journals it separately without a signal.
   if r.get('watch_mode')=='exit':
    context=self.pluto.safe_context(r,r.get('quote_currency'))
    if context.get('status')=='verified' and context.get('as_of'):failure.position_context=context
   raise failure
  # This documented price endpoint does not prove bid/ask, interval volume,
  # market status or account entitlement. Never invent these capabilities.
  currency=d.get('currency') or r.get('quote_currency')
  if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):raise DataUnavailable('EODHD_CURRENCY_UNCONFIRMED')
  if d.get('currency') and d['currency']!=r.get('quote_currency'):raise DataUnavailable('quote_currency_mismatch')
  # The EODHD symbol suffix identifies its feed market; the Pluto venue is
  # a separate instrument reference and must never label this observation.
  market=symbol.rsplit('.',1)[1] if '.' in symbol else None
  venue='EODHD:'+market.upper() if market and re.fullmatch(r'[A-Za-z0-9_-]{1,16}',market) else None
  # The field is provider-reported volume, but its accumulation period has not
  # been verified. Keep it visible without feeding it into interval metrics.
  raw_volume=d.get('volume');volume=str(raw_volume) if type(raw_volume) in (int,str) else None
  if volume is not None and not re.fullmatch(r'\d{1,18}(?:\.\d{1,12})?',volume):volume=None
  sample_id='eodhd-'+hashlib.sha256((symbol+at.isoformat()).encode()).hexdigest()[:32]
  # An observation already journalled at this source time is immutable. A
  # software upgrade or a repeated quote must not turn it into a conflicting
  # sample merely because volume is now exposed or has changed.
  old_sample=None
  if session.get('id') is not None:
   with self.connect() as c:
    old=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? AND source=? AND sample_id=?',(session['id'],'eodhd',sample_id)).fetchone()
    if not old and session.get('last_data') and stamp(session['last_data'])==at:
     old=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? AND source=? AND event_epoch=? ORDER BY id DESC LIMIT 1',(session['id'],'eodhd',at.timestamp())).fetchone()
   if old:old_sample=json.loads(old['payload']);volume=old_sample.get('volume')
  context_started=time.perf_counter();context=self.pluto.safe_context(r,currency);context_ms=(time.perf_counter()-context_started)*1000
  self.last_telemetry={'eodhd_http_ms':round(http_ms,3),'pluto_context_ms':round(context_ms,3),'event_to_http_receive_ms':round((received-at).total_seconds()*1000,3)}
  state=json.loads(session.get('state') or '{}');profile=state.get('adaptive_profile') or r['profile']
  interval=self.interval(r,profile)
  if old_sample:interval=old_sample['interval_s']
  result={'sample_id':sample_id,'source':'eodhd','ticker':r['ticker'],'asset_id':r['asset_id'],'venue':venue,'currency':currency,'event_time':at.isoformat(),'session_key':at.date().isoformat()+':UNKNOWN','market_status':'UNKNOWN','feed_type':'EODHD REST real-time endpoint; entitlement/cadence unconfirmed; currency='+('provider' if d.get('currency') else 'explicit session instrument'),'documented_delay_s':None,'verification':'verified','error_code':None,'interval_s':interval,'price':format(price,'f'),'bid':None,'ask':None,'volume':volume,'volume_type':'unknown','open':None,'high':None,'low':None,'close':None,'context':context}
  # Repeated readings of the same price and event time retain their original
  # market evidence across software upgrades; only broker context is current.
  # A changed price remains a conflict, never a fabricated new observation.
  if old_sample:
   try:
    same=all(old_sample.get(k)==result.get(k) for k in ('source','ticker','asset_id','currency')) and stamp(old_sample['event_time'])==at and Decimal(old_sample['price'])==price
    if same:return dict(old_sample,context=context)
   except (KeyError,TypeError,ValueError,ArithmeticError):pass
  previous=old_sample.get('previous_close') if old_sample else str(d.get('previousClose')) if type(d.get('previousClose')) in (int,str) else None
  if previous is not None and re.fullmatch(r'\d{1,18}(?:\.\d{1,12})?',previous) and Decimal(previous)>0:result['previous_close']=previous
  return result

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
