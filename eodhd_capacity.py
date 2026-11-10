"""Shared EODHD transport accounting in the existing budget/health tables.

HTTP requests, daily call units and concurrent WebSocket subscriptions are
different budgets. No market, strategy, or order decisions belong here.
"""
import hashlib,json,math,os,re,secrets,time,urllib.error,urllib.request
from contextlib import contextmanager
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit,parse_qs
from hotwatch_contract import EngineError

SOURCE='eodhd_capacity'
UTILIZATION=80
DOCUMENTED_HTTP_LIMIT=1000

def configured_limit(provider_limit=DOCUMENTED_HTTP_LIMIT):
 limit=max(1,int(provider_limit)*UTILIZATION//100)
 # Only an explicit EODHD override applies. The old shared Pluto default
 # must not silently constrain EODHD. Expose overrides in the readback.
 try:override=int(os.environ.get('ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE','0'))
 except ValueError:override=0
 return min(limit,override) if override>0 else limit

def _credential():return hashlib.sha256(os.environ.get('ESCAPE_EODHD_API_KEY','').strip().encode()).hexdigest()
def read(c):
 row=c.execute('SELECT payload FROM hw_provider_health WHERE user_id=0 AND is_test=0 AND source=?',(SOURCE,)).fetchone()
 state=json.loads(row['payload']) if row else {}
 return state if state.get('credential')==_credential() else {'credential':_credential()}
def write(c,state,now):
 at=datetime.fromtimestamp(now,timezone.utc).isoformat()
 c.execute('INSERT INTO hw_provider_health VALUES(0,0,?,?,NULL,NULL,?) ON CONFLICT(user_id,is_test,source) DO UPDATE SET attempted=excluded.attempted,payload=excluded.payload',(SOURCE,at,json.dumps(state,separators=(',',':'))))
def http_limit(c):return configured_limit(read(c).get('http_provider_limit',DOCUMENTED_HTTP_LIMIT))
def retry_seconds(headers,now=None):
 now=time.time() if now is None else now
 value=(headers or {}).get('Retry-After')
 try:
  seconds=float(value)
  if not math.isfinite(seconds):raise ValueError()
  return max(1,seconds)
 except (TypeError,ValueError):
  try:return max(1,parsedate_to_datetime(value).timestamp()-now)
  except (TypeError,ValueError,OverflowError):return max(1,60-now%60)
def _integer(value):
 try:return int(value) if not isinstance(value,bool) and str(value).isdigit() else None
 except (ValueError,TypeError):return None
def cost(url):
 parsed=urlsplit(url);path=parsed.path
 if parsed.hostname!='eodhd.com':return None # /history has no documented core-call price.
 endpoint=path.removeprefix('/api/').split('/')[0]
 if endpoint=='user':return 0
 if endpoint in ('intraday','technical','news','screener'):return 5
 if endpoint=='fundamentals':return 10
 if endpoint=='real-time':return 1+len([s for s in parse_qs(parsed.query).get('s',[''])[0].split(',') if s])
 if endpoint in ('search','exchanges-list','exchange-details','exchange-symbol-list','calendar','eod','splits','div'):return 1
 return None

class Capacity:
 def __init__(self,connect):self.connect=connect
 def reserve(self,units=None,now=None,endpoint=None,market=None):
  now=time.time() if now is None else now;window=int(now//60)
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');state=read(c);limit=configured_limit(state.get('http_provider_limit',DOCUMENTED_HTTP_LIMIT))
   if state.get('http_retry_at',0)>now:
    error=EngineError('PROVIDER_RATE_BUDGET',429);error.retry_after_s=state['http_retry_at']-now;raise error
   row=c.execute("SELECT used FROM hw_request_budget WHERE user_id=0 AND source='eodhd' AND window=?",(window,)).fetchone();used=row['used'] if row else 0
   if used>=limit:raise EngineError('PROVIDER_RATE_BUDGET',429)
   # The provider's remaining count also includes requests from other clients.
   if state.get('header_window')==window and state.get('header_remaining') is not None:
    remaining=state['header_remaining']-max(0,used-state.get('header_local_used',0))
    if remaining<=state.get('http_provider_limit',DOCUMENTED_HTTP_LIMIT)-limit:raise EngineError('PROVIDER_RATE_BUDGET',429)
   day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
   if state.get('local_day')!=day:state.update(local_day=day,known_units=0,unknown_cost_requests=0,requests=0,errors=0,http_429=0,latency_total_ms=0)
   account=state.get('account',{})
   if units!=0 and account.get('apiRequestsDate')==day and account.get('dailyRateLimit'):
    estimate=account['apiRequests']+max(0,state.get('known_units',0)-state.get('units_at_account',0))
    if estimate+(units or 0)>account['dailyRateLimit']*UTILIZATION//100:raise EngineError('EODHD_DAILY_BUDGET',429)
   state['known_units']=state.get('known_units',0)+(units or 0)
   state['unknown_cost_requests']=state.get('unknown_cost_requests',0)+(units is None)
   state['requests']=state.get('requests',0)+1
   # Hourly aggregate only: never store paths, symbols, keys or credentials.
   if endpoint:
    hour=int(now//3600);buckets=state.get('endpoint_hours',{})
    buckets={k:v for k,v in buckets.items() if k.isdigit() and hour-23<=int(k)<=hour}
    key=endpoint+':'+(market or 'UNKNOWN');bucket=buckets.setdefault(str(hour),{})
    counter=bucket.setdefault(key,{'requests':0,'known_units':0,'unknown_cost_requests':0})
    counter['requests']+=1;counter['known_units']+=units or 0;counter['unknown_cost_requests']+=units is None
    state['endpoint_hours']=buckets
   c.execute('DELETE FROM hw_request_budget WHERE window<?',(window-2,))
   c.execute("INSERT INTO hw_request_budget VALUES(0,'eodhd',?,1) ON CONFLICT(user_id,source,window) DO UPDATE SET used=used+1",(window,))
   write(c,state,now)
 def observe(self,status,headers,elapsed_ms,now=None):
  now=time.time() if now is None else now;window=int(now//60)
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');state=read(c)
   state['last_http_status']=status;state['last_http_at']=datetime.fromtimestamp(now,timezone.utc).isoformat()
   state['last_latency_ms']=round(elapsed_ms,2);state['latency_total_ms']=round(state.get('latency_total_ms',0)+elapsed_ms,2)
   state['errors']=state.get('errors',0)+(status is None or status>=400)
   limit=_integer((headers or {}).get('X-RateLimit-Limit'));remaining=_integer((headers or {}).get('X-RateLimit-Remaining'))
   if limit and limit>0:state['http_provider_limit']=limit;state['limit_source']='response_header'
   if remaining is not None:
    row=c.execute("SELECT used FROM hw_request_budget WHERE user_id=0 AND source='eodhd' AND window=?",(window,)).fetchone()
    if state.get('header_window')==window:remaining=min(remaining,state.get('header_remaining',remaining))
    state.update(header_window=window,header_remaining=remaining,header_local_used=row['used'] if row else 0)
   if status==429:
    state['http_429']=state.get('http_429',0)+1
    state['http_retry_at']=max(state.get('http_retry_at',0),now+retry_seconds(headers,now))
   write(c,state,now)
 @contextmanager
 def open(self,opener,request,timeout=8):
  parsed=urlsplit(request.full_url);parts=parsed.path.removeprefix('/api/').split('/')
  allowed={'user','intraday','technical','news','screener','fundamentals','real-time','search','exchanges-list','exchange-details','exchange-symbol-list','calendar','eod','splits','div'}
  endpoint=parts[0] if parsed.hostname=='eodhd.com' and parts[0] in allowed else 'other'
  raw=parts[1] if len(parts)>1 else '';market=raw.rsplit('.',1)[-1].upper() if '.' in raw else raw.upper() if endpoint in ('exchange-details','exchange-symbol-list') else ''
  market=market if re.fullmatch(r'[A-Z0-9_-]{1,16}',market) else 'UNKNOWN'
  self.reserve(cost(request.full_url),endpoint=endpoint,market=market);started=time.perf_counter();status=None;headers={}
  try:
   with opener.open(request,timeout=timeout) as response:
    status=getattr(response,'status',200);headers=getattr(response,'headers',{})
    yield response
  except urllib.error.HTTPError as error:
   status=error.code;headers=error.headers;raise
  finally:self.observe(status,headers,(time.perf_counter()-started)*1000)
 @contextmanager
 def websocket(self,count):
  # Short-lived capture leases are global to the installation/key. They do not
  # consume HTTP requests or daily call units. Expiry handles a killed worker.
  token=secrets.token_hex(12);now=time.time()
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');state=read(c)
   if state.get('ws_retry_at',0)>now:
    error=EngineError('EODHD_WS_CAPACITY',429);error.retry_after_s=state['ws_retry_at']-now;raise error
   leases={k:v for k,v in state.get('ws_leases',{}).items() if v['until']>now}
   if len(leases)>=64*UTILIZATION//100 or sum(v['symbols'] for v in leases.values())+count>50*UTILIZATION//100:raise EngineError('EODHD_WS_CAPACITY',429)
   leases[token]={'until':now+30,'symbols':count};state['ws_leases']=leases;write(c,state,now)
  try:yield
  finally:
   with self.connect() as c:
    c.execute('BEGIN IMMEDIATE');state=read(c);state.get('ws_leases',{}).pop(token,None);write(c,state,time.time())
 def ws_limited(self,headers=None):
  now=time.time();seconds=retry_seconds(headers,now)
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');state=read(c);state['ws_retry_at']=max(state.get('ws_retry_at',0),now+seconds);state['ws_429']=state.get('ws_429',0)+1;write(c,state,now)
  return seconds

def snapshot(c,now=None):
 now=time.time() if now is None else now;state=read(c);limit=state.get('http_provider_limit',DOCUMENTED_HTTP_LIMIT)
 row=c.execute("SELECT used FROM hw_request_budget WHERE user_id=0 AND source='eodhd' AND window=?",(int(now//60),)).fetchone()
 queue=c.execute("SELECT count(*) FROM hw_sessions WHERE status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND next_due<=? AND lease_until<=? AND json_extract(request,'$.provider')='eodhd'",(now,now)).fetchone()[0]
 leases=[x for x in state.get('ws_leases',{}).values() if x['until']>now]
 return {'utilization_pct':UTILIZATION,'http_provider_limit_per_minute':limit,'http_limit_basis':state.get('limit_source','documented_default'),'http_effective_limit_per_minute':configured_limit(limit),'http_configured_override':os.environ.get('ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE'),'http_used_this_minute':row['used'] if row else 0,'due_sessions':queue,'ws_connections':len(leases),'ws_subscriptions':sum(x['symbols'] for x in leases),'ws_subscription_limit':40,'ws_connection_limit':51,**{k:state.get(k) for k in ('local_day','requests','errors','http_429','last_http_status','last_http_at','last_latency_ms','latency_total_ms','known_units','unknown_cost_requests','http_retry_at','account','account_checked_at','account_status','ws_retry_at','ws_429')},'endpoint_hourly':state.get('endpoint_hours',{}),'daily_usage_note':'Account snapshot plus known local costs; other clients and unknown endpoint costs require the next account snapshot.'}

def refresh_account(connect,opener=None):
 key=os.environ.get('ESCAPE_EODHD_API_KEY','').strip()
 if not key:return
 now=time.time()
 with connect() as c:
  if read(c).get('account_next_at',0)>now:return
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');state=read(c)
  if state.get('account_next_at',0)>now:return
  state['account_next_at']=now+300;write(c,state,now)
 from eodhd_feeds import EODHDFeeds,HTTP_BASE
 result=EODHDFeeds(key,opener=opener,capacity=Capacity(connect))._http(HTTP_BASE,'/user',{'fmt':'json'})
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');state=read(c);state['account_checked_at']=datetime.now(timezone.utc).isoformat();state['account_status']=result['status']
  data=result.get('payload')
  if result['status']=='OK' and isinstance(data,dict) and all(_integer(data.get(k)) is not None for k in ('apiRequests','dailyRateLimit','extraLimit')) and isinstance(data.get('apiRequestsDate'),str):
   # Do not persist name, email, API key, payment or invitation fields.
   state['account']={k:_integer(data[k]) for k in ('apiRequests','dailyRateLimit','extraLimit')}
   state['account']['apiRequestsDate']=data['apiRequestsDate'][:10];state['units_at_account']=state.get('known_units',0)
  elif result['status']=='OK':state['account_status']='INVALID_RESPONSE'
  write(c,state,time.time())
