"""Read-only provider adapters. Missing entitlements/fields are explicit faults."""
import hashlib,json,os,re,time,urllib.request,urllib.error
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from urllib.parse import quote,urlencode
from hotwatch_contract import EngineError,checksum,stamp,provider_floor,PROFILES
from hotwatch_engine import utc,effective_poll_interval,valid_cxe_evidence,provider_request_limit

class DataUnavailable(EngineError):pass

def reserve(connect,uid,source,now=None,purpose=None):
 uid=0 if source=='eodhd' else uid
 now=now or utc();window=int(now.timestamp()//60);limit=provider_request_limit(source)
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM hw_request_budget WHERE window<?',(window-2,))
  row=c.execute('SELECT used FROM hw_request_budget WHERE user_id=? AND source=? AND window=?',(uid,source,window)).fetchone()
  lane_name='identity' if purpose in ('identity','candidate_identity','holding_identity') else purpose
  if source=='pluto' and lane_name in ('identity','scan') and limit>=10:
   candidate_report="SELECT r.report_id FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=d.user_id AND l.is_test=0 AND l.candidate_id=d.candidate_id AND r.report_type!='deep_analysis' ORDER BY l.generated DESC,r.id DESC LIMIT 1"
   c.execute('DELETE FROM hw_pluto_budget_lane WHERE window<?',(window-2,))
   if purpose=='candidate_identity' and window%2:
    waiting=c.execute("SELECT 1 FROM hw_holding_autowatch WHERE user_id=? AND status NOT IN ('LINKED','STOPPED','POSITION_CLOSED','AMBIGUOUS','CAPACITY_LIMIT') AND (status='VERIFYING' OR next_attempt<=?) UNION ALL SELECT 1 FROM hw_feed_recovery f JOIN hw_sessions s ON s.id=f.watch_row_id WHERE s.user_id=? AND s.is_test=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND f.status!='MATCHED' AND f.next_attempt<=? LIMIT 1",(uid,now.timestamp()+60,uid,now.timestamp()+60)).fetchone()
    if waiting:raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
   if purpose=='holding_identity' and not window%2:
    waiting=c.execute("SELECT 1 FROM hw_discovery_attempts d WHERE d.user_id=? AND d.is_test=0 AND d.report_id=("+candidate_report+") AND d.status NOT IN ('CREATED','ACTIVE','ALREADY_ACTIVE','NOT_NEW','REJECTED','global_capacity_limit','capacity_limit') AND d.next_attempt BETWEEN ? AND ? LIMIT 1",(uid,now.timestamp()-60,now.timestamp()+60)).fetchone()
    if waiting:raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
   if lane_name=='identity':
    competing=c.execute("SELECT 1 FROM hw_sessions WHERE user_id=? AND is_test=0 AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND json_extract(request,'$.provider')='pluto' AND next_due<=? LIMIT 1",(uid,now.timestamp()+60)).fetchone()
    cap=limit-max(4,limit*5//12)
   else:
    competing=c.execute("SELECT 1 FROM hw_holding_autowatch WHERE user_id=? AND status NOT IN ('LINKED','STOPPED','POSITION_CLOSED','AMBIGUOUS','CAPACITY_LIMIT') AND (status='VERIFYING' OR next_attempt<=?) UNION ALL SELECT 1 FROM hw_discovery_attempts d WHERE d.user_id=? AND d.is_test=0 AND d.report_id=("+candidate_report+") AND d.status NOT IN ('CREATED','ACTIVE','ALREADY_ACTIVE','NOT_NEW','REJECTED','global_capacity_limit','capacity_limit') AND d.next_attempt BETWEEN ? AND ? UNION ALL SELECT 1 FROM hw_feed_recovery f JOIN hw_sessions s ON s.id=f.watch_row_id WHERE s.user_id=? AND s.is_test=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND f.status!='MATCHED' AND f.next_attempt<=? LIMIT 1",(uid,now.timestamp()+60,uid,now.timestamp()-60,now.timestamp()+60,uid,now.timestamp()+60)).fetchone()
    cap=max(4,limit*5//12)
   lane=c.execute('SELECT used FROM hw_pluto_budget_lane WHERE user_id=? AND window=? AND lane=?',(uid,window,lane_name)).fetchone()
   if competing and lane and lane['used']>=cap:raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
  # Leave room within the existing shared limit for identity and exchange
  # checks; neither kind of request may exceed the provider-wide budget.
  if source=='eodhd' and limit>3:
   reserved=0
   if purpose!='holding_identity':
    pending=c.execute("SELECT 1 FROM hw_holding_autowatch WHERE (status='VERIFYING' AND next_attempt>=?) OR (status='PROVIDER_RATE_BUDGET' AND next_attempt BETWEEN ? AND ?) UNION ALL SELECT 1 FROM hw_feed_recovery f JOIN hw_sessions s ON s.id=f.watch_row_id WHERE s.is_test=0 AND s.status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND f.status!='MATCHED' AND f.next_attempt BETWEEN ? AND ? LIMIT 1",(now.timestamp()-60,now.timestamp()-60,now.timestamp()+60,now.timestamp()-60,now.timestamp()+60)).fetchone()
    if pending:reserved+=2
   if purpose!='exchange_status' and c.execute('SELECT 1 FROM hw_exchange_status WHERE next_attempt BETWEEN ? AND ? LIMIT 1',(now.timestamp()-60,now.timestamp()+60)).fetchone():reserved+=1
   limit=max(1,limit-reserved)
  if row and row['used']>=limit:raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
  c.execute('INSERT INTO hw_request_budget VALUES(?,?,?,1) ON CONFLICT(user_id,source,window) DO UPDATE SET used=used+1',(uid,source,window))
  if source=='pluto' and lane_name in ('identity','scan'):
   c.execute('INSERT INTO hw_pluto_budget_lane VALUES(?,?,?,1) ON CONFLICT(user_id,window,lane) DO UPDATE SET used=used+1',(uid,window,lane_name))

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
  reserve(connect,uid,'eodhd',purpose=purpose or ('holding_identity' if 'holding_portfolio_id' in data else None))
  url='https://eodhd.com/api/search/'+quote(query,safe='')+'?'+urlencode({'api_token':key,'fmt':'json','limit':50})
  try:
   with client.open(urllib.request.Request(url,headers={'Accept':'application/json'}),timeout=8) as response:raw=response.read(131073)
   if len(raw)>131072:raise ValueError()
   rows=json.loads(raw)
   if not isinstance(rows,list):raise ValueError()
   successful.append(True)
  except urllib.error.HTTPError as error:
   if error.code==404:not_found.append(True);return
   if error.code in [401,403]:raise DataUnavailable('EODHD_SEARCH_HTTP_'+str(error.code),502) from None
   if error.code==429:raise DataUnavailable('EODHD_RATE_LIMIT',429) from None
   raise DataUnavailable('EODHD_SEARCH_HTTP_'+str(error.code),502) from None
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
   if base.casefold()!=ticker.casefold() and not ticker_equivalent and not crypto_pair and not (allow_alias and issuer_key and name_key(name)==issuer_key):continue
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
 def __init__(self,connect,uid,purpose='scan'):self.connect=connect;self.uid=uid;self.purpose=purpose;self.gateway=None;self.order_cache={};self.permission_cache={}
 def safe_context(self,request,currency):
  try:return self.context(request,currency)
  except DataUnavailable as error:return unknown_context(error.code if error.code=='PROVIDER_RATE_BUDGET' else 'BROKER_CONTEXT_UNAVAILABLE')
  except Exception:return unknown_context('BROKER_CONTEXT_UNAVAILABLE')
 def factory(self,token):
  if self.gateway and self.gateway.token==token:return self.gateway
  from mcp_client import MCP
  connect=self.connect;uid=self.uid;purpose=self.purpose
  class ReadOnlyGateway(MCP):
   allowed={'search_assets','get_asset','get_portfolio_value','get_accounts','get_positions','get_collection','list_orders','list_portfolios','list_collections','get_collection_activity'}
   def __init__(self,token):super().__init__(token);self.catalog=None
   def tools(self):
    if self.catalog is None:self.catalog=super().tools()
    return self.catalog
   def request(self,method,params=None,notification=False):
    if method=='tools/call':
     name=(params or {}).get('name');metadata=next((t for t in self.catalog or [] if t['name']==name),None)
     if name not in self.allowed or not metadata or metadata.get('annotations',{}).get('readOnlyHint') is not True:raise DataUnavailable('PLUTO_WRITE_OR_UNKNOWN_TOOL_BLOCKED')
    elif method not in ['initialize','notifications/initialized','tools/list']:raise DataUnavailable('PLUTO_METHOD_BLOCKED')
    reserve(connect,uid,'pluto',purpose=purpose);return super().request(method,params,notification)
  self.gateway=ReadOnlyGateway(token);return self.gateway
 def tradability(self,request,currency,portfolios):
  """Only use current read-only Pluto instrument and account evidence."""
  import trade_service
  if not portfolios:return 'unknown',None
  key=(request['asset_id'],request['ticker'].casefold(),str(request.get('exchange') or '').casefold(),currency,tuple(sorted(p['id'] for p in portfolios)),request.get('risk',{}).get('proposed_quantity') is not None);now=utc().timestamp();cached=self.permission_cache.get(key)
  if cached and 0<=now-cached['at']<300:return cached['status'],cached['at']
  try:
   client,tools=trade_service.client(self.connect,self.uid,self.factory);raw=trade_service.call(client,tools,'get_asset',{'assetId':request['asset_id']})
   asset=raw.get('asset') if isinstance(raw,dict) else None;buy=raw.get('buyBy') if isinstance(raw,dict) else None
   if not isinstance(asset,dict) or asset.get('id')!=request['asset_id'] or str(asset.get('ticker','')).casefold()!=request['ticker'].casefold() or asset.get('currency')!=currency:return 'unknown',None
   if request.get('exchange') and str(asset.get('exchange','')).casefold()!=request['exchange'].casefold():return 'unknown',None
   if not isinstance(buy,dict) or not (buy.get('shares') is True or buy.get('amount') is True):return 'unknown',None
   if request.get('risk',{}).get('proposed_quantity') is not None and buy.get('shares') is not True:return 'unknown',None
   for portfolio in portfolios:trade_service.fresh_permission(client,tools,self.connect,self.uid,portfolio)
   self.permission_cache[key]={'at':now,'status':'available'};return 'available',now
  except Exception:return 'unknown',None
 def context(self,request,currency):
  import portfolio_data
  result=unknown_context();rows=[];portfolios=[];automatic=not request['portfolio_ids']
  with self.connect() as c:
   if automatic:
    portfolios=[dict(p) for p in c.execute("SELECT * FROM portfolios WHERE user_id=? AND source='pluto' AND active=1 ORDER BY id",(self.uid,))]
   else:
    for pid in request['portfolio_ids']:
     p=c.execute("SELECT * FROM portfolios WHERE id=? AND user_id=? AND source='pluto' AND active=1",(pid,self.uid)).fetchone()
     if not p:return unknown_context('PORTFOLIO_NOT_ACTIVE')
     portfolios.append(dict(p))
   overlap=any(a['external_id']==b.get('parent_external_id') for a in portfolios for b in portfolios)
   if overlap and not automatic:return unknown_context('PORTFOLIO_SCOPE_OVERLAP')
  for p in portfolios:
   with self.connect() as c:row=c.execute('SELECT * FROM portfolio_snapshots WHERE portfolio_id=? AND user_id=?',(p['id'],self.uid)).fetchone()
   if not row or row['last_error'] or (utc()-stamp(row['observed'])).total_seconds()>300:
    payload=portfolio_data.read(self.connect,self.uid,p['id'],client_factory=self.factory)
    with self.connect() as c:portfolio_data.save(c,self.uid,p['id'],payload)
   else:payload=json.loads(row['payload'])
   if not payload.get('positions_complete') or not payload.get('complete'):return unknown_context('PORTFOLIO_SNAPSHOT_INCOMPLETE')
   rows.append(payload)
  if not rows:return unknown_context('NO_ACTIVE_PORTFOLIOS')
  # An unidentified holding could be this asset; absence is not proven.
  if any(p.get('kind','holding')=='holding' and not p.get('asset_id') for payload in rows for p in payload['positions']):return unknown_context('HOLDING_ID_MISSING')
  found=[position for payload in rows for position in payload['positions'] if position.get('asset_id')==request['asset_id']]
  # Parent and collection snapshots may overlap. Their complete absence can
  # establish zero holdings, but a matching position cannot be safely summed.
  if overlap and found:return unknown_context('HOLDING_SCOPE_OVERLAP')
  # Buy permissions are irrelevant to exit-only holding watches and each
  # unnecessary check competes with identity/quote requests for Pluto budget.
  # Keep the value unknown rather than claiming a permission was checked.
  tradability_at=None
  if request.get('watch_mode')!='exit':result['tradability'],tradability_at=self.tradability(request,currency,portfolios)
  if any(p['quantity'] is None for p in found):return unknown_context('HOLDING_QUANTITY_MISSING')
  if any(p.get('ticker') and p['ticker'].casefold()!=request['ticker'].casefold() for p in found):raise DataUnavailable('PLUTO_ASSET_NOT_CONFIRMED')
  if any(Decimal(p['quantity'])<0 for p in found):raise DataUnavailable('PLUTO_SHORT_POSITION_NOT_SUPPORTED')
  quantity=sum((Decimal(p['quantity']) for p in found),Decimal(0))
  observed=[p['observed'] for p in rows]+([datetime.fromtimestamp(tradability_at,timezone.utc).isoformat()] if tradability_at is not None else [])
  result.update(status='verified',as_of=min(observed,key=stamp),position='held' if quantity>0 else 'none',quantity=format(quantity,'f'),fx_to_dkk='1' if currency=='DKK' else None)
  if len(found)==1 and found[0].get('average_entry',{}).get('currency')==currency:result['cost_price']=found[0]['average_entry']['amount']
  values=[p.get('value',{}).get('value') for p in rows]
  if not overlap and all(v and v['amount'] is not None and v['currency']=='DKK' for v in values):result['portfolio_equity_dkk']=format(sum(Decimal(v['amount']) for v in values),'f')
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
   error=DataUnavailable('PLUTO_QUOTE_TIME_UNKNOWN');error.position_context=context;raise error
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

class EODHDAdapter:
 def __init__(self,connect,uid,opener=None):self.connect=connect;self.uid=uid;self.opener=opener or urllib.request.build_opener(NoRedirect());self.pluto=PlutoAdapter(connect,uid);self.last_telemetry={}
 def interval(self,request,profile):
  if self.connect is None:return max(PROFILES.get(profile,PROFILES[request['profile']]),provider_floor('eodhd'))
  with self.connect() as c:return effective_poll_interval(c,request,profile)
 def feeds(self):
  from eodhd_feeds import EODHDFeeds
  return EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),reserve=lambda:reserve(self.connect,self.uid,'eodhd'),opener=self.opener)
 def poll(self,session):
  if os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1':raise DataUnavailable('EODHD_FEED_NOT_ENABLED')
  key=os.environ.get('ESCAPE_EODHD_API_KEY','').strip()
  if not key:raise DataUnavailable('EODHD_KEY_NOT_CONFIGURED')
  r=session['request_data'];symbol=r.get('provider_symbol')
  if not symbol:raise DataUnavailable('EODHD_SYMBOL_MAPPING_REQUIRED')
  if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',symbol):raise DataUnavailable('EODHD_SYMBOL_MAPPING_REQUIRED')
  cxe_valid=None
  if self.connect is not None:
   with self.connect() as c:cxe_valid=valid_cxe_evidence(c,self.uid,r,utc())
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
  # Explicit opt-in: one bounded live trade capture. If unavailable, use the
  # unchanged REST adapter. No inferred venue/session or fabricated bid/ask.
  exchange=symbol.rsplit('.',1)[1].upper() if '.' in symbol else ''
  eu_exchanges={x.strip().upper() for x in os.environ.get('ESCAPE_HW_EODHD_WS_EU_EXCHANGES','').split(',') if re.fullmatch(r'[A-Za-z0-9_-]{1,16}',x.strip())}
  # CC is EODHD's virtual crypto market, not a supported EU equity stream.
  eu_exchanges.discard('CC')
  if os.environ.get('ESCAPE_HW_EODHD_WS_TRADES_ENABLED')=='1' and exchange and exchange!='US' and exchange not in eu_exchanges:self.last_feed_diagnostics={'websocket_trade_status':'MARKET_MAPPING_UNVERIFIED'}
  if os.environ.get('ESCAPE_HW_EODHD_WS_TRADES_ENABLED')=='1' and (exchange=='US' or exchange in eu_exchanges):
   market='us' if exchange=='US' else 'eu';stream_symbol=symbol[:-3] if market=='us' else symbol
   client=self.feeds();stream_started=time.perf_counter();feed=client.capture(market+'_trades',stream_symbol,duration=2);stream_ms=(time.perf_counter()-stream_started)*1000
   self.last_feed_diagnostics={'websocket_trade_status':feed['status']}
   if feed['status']=='LOCAL_BUDGET_EXHAUSTED':raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
   if feed['status']=='RATE_LIMIT':
    failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=600;raise failure
   if feed['status']=='OK':
    valid=[x for x in feed['messages'] if stamp(x['event_time'])<=utc() and (utc()-stamp(x['event_time'])).total_seconds()<=r['risk']['max_quote_age_s']]
    if not valid:self.last_feed_diagnostics={'websocket_trade_status':'STALE_OR_FUTURE'}
    if valid:
     trade=max(valid,key=lambda x:stamp(x['event_time']));at=stamp(trade['event_time']);currency=r.get('quote_currency')
     if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):raise DataUnavailable('EODHD_CURRENCY_UNCONFIRMED')
     context_started=time.perf_counter();context=self.pluto.safe_context(r,currency);context_ms=(time.perf_counter()-context_started)*1000
     self.last_telemetry={'websocket_capture_ms':round(stream_ms,3),'pluto_context_ms':round(context_ms,3),'event_to_websocket_receive_ms':round((stamp(trade['received_at'])-at).total_seconds()*1000,3) if trade.get('received_at') else None}
     state=json.loads(session.get('state') or '{}');profile=state.get('adaptive_profile') or r['profile']
     interval=self.interval(r,profile)
     sample={'sample_id':'eodhd-ws-'+hashlib.sha256((symbol+trade['event_time']).encode()).hexdigest()[:28],'source':'eodhd','ticker':r['ticker'],'asset_id':r['asset_id'],'venue':None,'currency':currency,'event_time':trade['event_time'],'session_key':at.date().isoformat()+':UNKNOWN','market_status':'UNKNOWN','feed_type':'EODHD WebSocket '+market+' trade; venue not supplied; not necessarily consolidated','documented_delay_s':None,'verification':'verified','error_code':None,'interval_s':interval,'price':trade['price'],'bid':None,'ask':None,'volume':None,'volume_type':'unknown','open':None,'high':None,'low':None,'close':None,'context':context,'price_time_kind':'trade'}
     if trade.get('market_session')=='closed':sample.update(market_status='CLOSED',session_key=at.date().isoformat()+':CLOSED',status_at=trade['event_time'],status_feed=market+'_trades')
     if trade.get('market_session')=='open':sample.update(market_status='REGULAR',session_key=at.date().isoformat()+':REGULAR',status_at=trade['event_time'],status_feed=market+'_trades')
     if session.get('id') is not None:
      with self.connect() as c:old=c.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? AND source=? AND sample_id=?',(session['id'],'eodhd',sample['sample_id'])).fetchone()
      if old:
       previous=json.loads(old['payload']);previous['context']=context;return previous
     if os.environ.get('ESCAPE_HW_EODHD_FUSE_ENABLED')=='1':
      quote_feed=client.capture(market+'_quotes',stream_symbol,duration=2)
      if quote_feed['status']=='LOCAL_BUDGET_EXHAUSTED':
       self.last_feed_diagnostics['websocket_quote_status']='LOCAL_BUDGET_EXHAUSTED';return sample
      status_feed=client.capture(market+'_status',stream_symbol,duration=2) if quote_feed['status']!='RATE_LIMIT' else {'status':'RATE_LIMIT'}
      self.last_feed_diagnostics.update(websocket_quote_status=quote_feed['status'],websocket_status_status=status_feed['status'])
      if 'RATE_LIMIT' in (quote_feed['status'],status_feed['status']):
       failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=600;raise failure
      now=utc();max_age=r['risk']['max_quote_age_s']
      fresh=lambda item:bool(item.get('event_time') and 0<=(now-stamp(item['event_time'])).total_seconds()<=max_age)
      quotes=[x for x in quote_feed.get('messages',[]) if fresh(x) and x.get('bid') and x.get('ask') and Decimal(x['bid'])>0 and Decimal(x['ask'])>=Decimal(x['bid'])]
      if quotes:
       q=max(quotes,key=lambda x:stamp(x['event_time']));sample.update(bid=q['bid'],ask=q['ask'],bid_at=q['event_time'],ask_at=q['event_time'],quote_feed=market+'_quotes')
      if status_feed['status']=='LOCAL_BUDGET_EXHAUSTED':return sample
      statuses=[x for x in status_feed.get('messages',[]) if fresh(x) and x.get('trading_status')]
      if statuses and trade.get('market_session')=='open':
       status=max(statuses,key=lambda x:stamp(x['event_time']))
       if status['trading_status']=='T':sample.update(market_status='REGULAR',session_key=at.date().isoformat()+':REGULAR',status_at=status['event_time'],status_feed=market+'_status')
       else:sample.update(market_status='UNKNOWN',session_key=at.date().isoformat()+':UNKNOWN');sample.pop('status_at',None);sample.pop('status_feed',None)
      if sample['market_status']=='UNKNOWN' and trade.get('market_session') in ('extended-hours','extended hours') and (not statuses or max(statuses,key=lambda x:stamp(x['event_time']))['trading_status']=='T'):
       schedule=client.market_status(exchange);self.last_feed_diagnostics['exchange_status']=schedule['status']
       if schedule['status']=='RATE_LIMIT':
        failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=600;raise failure
       phase=extended_session(trade,schedule,utc(),max_age)
       if phase:
        # After-hours trading can cross midnight UTC while remaining on the
        # same exchange-local trading day. Do not split its warmup history.
        from zoneinfo import ZoneInfo
        local_day=at.astimezone(ZoneInfo(schedule['timezone'])).date().isoformat()
        sample.update(market_status=phase,session_key=local_day+':'+phase,status_at=trade['event_time'],status_feed=market+'_trades')
      if sample['market_status']=='REGULAR' and os.environ.get('ESCAPE_HW_EODHD_BARS_ENABLED')=='1':
       schedule=client.market_status(exchange);self.last_feed_diagnostics['exchange_status']=schedule['status']
       if schedule['status']=='LOCAL_BUDGET_EXHAUSTED':return sample
       if schedule['status']=='RATE_LIMIT':
        failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=600;raise failure
       if schedule.get('status')=='OK' and schedule.get('exchange_open') is True and schedule.get('calendar') and schedule.get('timezone'):
        bars=client.minute_bars(market,stream_symbol);self.last_feed_diagnostics['minute_bars_status']=bars['status']
        if bars['status']=='LOCAL_BUDGET_EXHAUSTED':return sample
        if bars['status']=='RATE_LIMIT':
         failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=600;raise failure
        if bars['status']=='OK':
         try:
          from zoneinfo import ZoneInfo
          from hotwatch_features import verified_bar_samples
          zone=ZoneInfo(schedule['timezone']);local=at.astimezone(zone);calendar=schedule['calendar'];start=datetime.strptime(calendar['open'],'%H:%M:%S').time();end=datetime.strptime(calendar['close'],'%H:%M:%S').time()
          same_session=[]
          for bar in bars.get('bars',[]):
           opened=stamp(bar['bar_open_at']);closed=opened+timedelta(seconds=60);lo=opened.astimezone(zone);lc=closed.astimezone(zone)
           if lo.date()==local.date()==lc.date() and start<=lo.time()<end and lc.time()<=end and closed<=at:
            same_session.append({k:bar[k] for k in ('bar_open_at','open','high','low','close','volume')})
          evidence={'provider_symbol':symbol,'market':market,'exchange':exchange,'timezone':schedule['timezone'],'session_date':local.date().isoformat(),'open':calendar['open'],'close':calendar['close'],'working_days':calendar['working_days'],'excluded_dates':calendar['excluded_dates'],'schedule_received_at':schedule['received_at'],'exchange_open':True,'feed':'eodhd_realtime_history'}
          if same_session:
           sample.update(bar_history=same_session[-120:],bar_evidence=evidence)
           if verified_bar_samples(sample,r,utc()) is None:sample.pop('bar_history');sample.pop('bar_evidence');self.last_feed_diagnostics['bar_history_status']='EVIDENCE_UNVERIFIED'
           else:self.last_feed_diagnostics['bar_history_status']='VERIFIED'
          else:self.last_feed_diagnostics['bar_history_status']='NO_COMPARABLE_BARS'
         except (KeyError,ValueError,TypeError,ArithmeticError):self.last_feed_diagnostics['bar_history_status']='EVIDENCE_UNVERIFIED'
       else:self.last_feed_diagnostics['bar_history_status']='SCHEDULE_UNVERIFIED'
     return sample
  # Bar open times and close prices are recorded as such; never pretend that
  # the bar timestamp is the timestamp of its final trade.
  if os.environ.get('ESCAPE_HW_EODHD_BARS_ENABLED')=='1' and (exchange=='US' or exchange in eu_exchanges):
   market='us' if exchange=='US' else 'eu';stream_symbol=symbol[:-3] if market=='us' else symbol;client=self.feeds();bars=client.minute_bars(market,stream_symbol);kind='realtime'
   self.last_feed_diagnostics['minute_bars_status']=bars['status']
   if bars['status']=='LOCAL_BUDGET_EXHAUSTED':raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
   if bars['status']=='RATE_LIMIT':
    failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=600;raise failure
   if bars['status']!='OK':
    end=int(utc().timestamp());bars=client.intraday(symbol,start=end-86400,end=end);kind='intraday';self.last_feed_diagnostics['intraday_status']=bars['status']
    if bars['status']=='LOCAL_BUDGET_EXHAUSTED':raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
    if bars['status']=='RATE_LIMIT':
     failure=DataUnavailable('EODHD_RATE_LIMIT',429);failure.retry_after_s=600;raise failure
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
  reserve(self.connect,self.uid,'eodhd');url='https://eodhd.com/api/real-time/'+quote(symbol,safe='')+'?'+urlencode({'api_token':key,'fmt':'json'})
  self.last_telemetry={};http_started=time.perf_counter()
  try:
   with self.opener.open(urllib.request.Request(url,headers={'Accept':'application/json'}),timeout=8) as response:
    raw=response.read(131073)
    if len(raw)>131072:raise ValueError()
    received=utc();http_ms=(time.perf_counter()-http_started)*1000
    d=json.loads(raw,parse_float=str)
   permitted_codes=[symbol,symbol.rsplit('.',1)[0]]+([] if symbol.upper().endswith('.CC') else [r['ticker']])
   if not isinstance(d,dict) or d.get('code') not in permitted_codes or not isinstance(d.get('timestamp'),(int,str)) or type(d.get('timestamp')) is bool:raise ValueError()
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
