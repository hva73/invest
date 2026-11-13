"""Bounded, read-only EODHD feed clients. No strategy or broker actions."""
import json, logging, re, time, urllib.error, urllib.request, threading, hashlib, copy
from datetime import datetime, timedelta, timezone, time as day_time
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlencode
from contextlib import nullcontext

HTTP_BASE='https://eodhd.com/api'
REALTIME_BASE='https://ws.eodhistoricaldata.com'
WS_BASE='wss://ws.eodhistoricaldata.com/ws'
_history_cache={}
_history_locks=[threading.Lock() for _ in range(32)]
_snapshot_cache={}
_snapshot_locks=[threading.Lock() for _ in range(32)]
_status_cache={}
_status_locks=[threading.Lock() for _ in range(32)]
STATUS_CACHE_TTL_S=60
WS_FEEDS={'us_trades':'us','us_quotes':'us-quote','us_status':'us-status','eu_trades':'eu','eu_quotes':'eu-quote','eu_status':'eu-status'}
_WS_LOGGER=logging.Logger('escape.eodhd.transport');_WS_LOGGER.disabled=True

class _NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def _valid_symbol(symbol):
 return isinstance(symbol,str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',symbol))

def _number(value):
 if isinstance(value,bool) or value is None:return None
 try:
  n=Decimal(str(value))
  if not n.is_finite() or n<0:return None
  out=format(n,'f')
  return out if re.fullmatch(r'\d{1,18}(?:\.\d{1,12})?',out) else None
 except (ValueError,InvalidOperation):return None

def _timestamp(value,unit):
 if type(value) is not int or value<=0:return None
 try:return (datetime.fromtimestamp(value//unit,timezone.utc)+timedelta(microseconds=(value%unit)*1000000//unit)).isoformat()
 except (ValueError,OverflowError,OSError):return None

def _result(status,endpoint,**kwargs):
 return {'status':status,'endpoint':endpoint,**kwargs}

def _unique_bars(bars):
 by_time={}
 for bar in bars:
  previous=by_time.get(bar['bar_open_at'])
  if previous is not None and previous!=bar:return None
  by_time[bar['bar_open_at']]=bar
 return sorted(by_time.values(),key=lambda row:row['bar_open_at'])

def _calendar(data):
 """Preserve only explicitly supplied exchange schedule evidence."""
 hours=data.get('TradingHours');holidays=data.get('ExchangeHolidays');early=data.get('ExchangeEarlyCloseDays')
 if not isinstance(hours,dict) or not isinstance(holidays,(dict,list)) or not isinstance(early,(dict,list)):return None
 try:
  opening=day_time.fromisoformat(hours['Open']);closing=day_time.fromisoformat(hours['Close'])
  if opening.tzinfo or closing.tzinfo or opening>=closing:raise ValueError()
  days=[x.strip() for x in hours['WorkingDays'].split(',')]
  if not days or len(days)>7 or any(x not in ('Mon','Tue','Wed','Thu','Fri','Sat','Sun') for x in days):raise ValueError()
  excluded=[]
  for collection in (holidays,early):
   for item in (collection.values() if isinstance(collection,dict) else collection):
    value=item.get('Date') if isinstance(item,dict) else None
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
    datetime.fromisoformat(value);excluded.append(value)
  if len(set(excluded))>400:raise ValueError()
  return {'open':opening.isoformat(),'close':closing.isoformat(),'working_days':days,'excluded_dates':sorted(set(excluded))}
 except (KeyError,ValueError,TypeError,AttributeError):return None

class EODHDFeeds:
 def __init__(self,key,reserve=None,opener=None,ws_factory=None,share_status=None,capacity=None):
  self._key=key.strip() if isinstance(key,str) else ''
  self._reserve=reserve or (lambda:None)
  self._opener=opener or urllib.request.build_opener(_NoRedirect())
  self._shared_snapshots=opener is None
  self._shared_status=opener is None if share_status is None else share_status
  self._ws_factory=ws_factory
  self._capacity=capacity
 def _http(self,base,path,params):
  if not self._key:return _result('KEY_MISSING',path)
  try:
   if self._capacity is None:self._reserve()
   url=base+path+'?'+urlencode({**params,'api_token':self._key})
   request=urllib.request.Request(url,headers={'Accept':'application/json'})
   with (self._capacity.open(self._opener,request) if self._capacity else self._opener.open(request,timeout=8)) as response:
    raw=response.read(1048577);received=datetime.now(timezone.utc).isoformat()
   if len(raw)>1048576: return _result('RESPONSE_TOO_LARGE',path)
   payload=json.loads(raw,parse_float=str,parse_constant=lambda _:None)
   if isinstance(payload,dict) and ('error' in payload or 'errors' in payload):
    detail=payload.get('error',payload.get('errors'));permission=isinstance(detail,str) and bool(re.search(r'(?i)subscri|entitle|permission|authoriz|access|api.?key|token|plan',detail))
    return _result('ENTITLEMENT_UNVERIFIED' if permission else 'PROVIDER_REJECTED',path)
   return _result('OK',path,received_at=received,payload=payload)
  except urllib.error.HTTPError as error:
   status='ENTITLEMENT_UNVERIFIED' if error.code in (401,402,403) else 'RATE_LIMIT' if error.code==429 else 'HTTP_ERROR'
   from eodhd_capacity import retry_seconds
   return _result(status,path,http_status=error.code,**({'retry_after_s':retry_seconds(error.headers)} if error.code==429 else {}))
  except Exception as error:
   if getattr(error,'code',None) in ('PROVIDER_RATE_BUDGET','EODHD_DAILY_BUDGET'):return _result('LOCAL_BUDGET_EXHAUSTED',path,budget_reason=error.code,retry_after_s=getattr(error,'retry_after_s',None))
   return _result('NETWORK_OR_RESPONSE_ERROR',path)
 def minute_bars(self,market,symbol):
  if market not in ('us','eu') or not _valid_symbol(symbol):return _result('INVALID_INPUT','/history')
  if not self._shared_status or not self._key:return self._minute_bars_uncached(market,symbol)
  key=(hashlib.sha256(self._key.encode()).digest(),market,symbol)
  with _history_locks[hash(key)%len(_history_locks)]:
   cached=_history_cache.get(key);now=time.monotonic()
   if cached and 0<=now-cached[0]<20:return copy.deepcopy(cached[1])
   result=self._minute_bars_uncached(market,symbol)
   if result.get('status')=='OK':
    if len(_history_cache)>=256:_history_cache.clear()
    _history_cache[key]=(time.monotonic(),copy.deepcopy(result))
   return result
 def _minute_bars_uncached(self,market,symbol):
  if market not in ('us','eu') or not _valid_symbol(symbol):return _result('INVALID_INPUT','/history')
  res=self._http(REALTIME_BASE,'/history',{'market':market,'symbol':symbol})
  if res['status']!='OK':return res
  rows=res.pop('payload')
  if not isinstance(rows,list):return _result('INVALID_RESPONSE','/history')
  out=[]
  for row in sorted((x for x in rows if isinstance(x,dict) and type(x.get('t')) is int),key=lambda x:x['t'])[-1000:]:
   if not isinstance(row,dict) or row.get('s') not in ([symbol,symbol+'.US'] if market=='us' and not symbol.endswith('.US') else [symbol]) or row.get('i')!='1m':continue
   ts=_timestamp(row.get('t'),1000);values={k:_number(row.get(k)) for k in ('o','h','l','c','v')}
   if ts and all(values[k] is not None for k in ('o','h','l','c')):out.append({'symbol':symbol,'bar_open_at':ts,'interval_s':60,'open':values['o'],'high':values['h'],'low':values['l'],'close':values['c'],'volume':values['v'],'volume_type':'interval'})
  out=_unique_bars(out)
  if out is None:return _result('INVALID_RESPONSE','/history')
  return {**res,'status':'OK' if out else 'NO_DATA','bars':out}
 def snapshot(self,symbol):
  if not _valid_symbol(symbol):return _result('INVALID_INPUT','/real-time')
  if not self._key:return _result('KEY_MISSING','/real-time')
  if not self._shared_snapshots:return self._snapshot_uncached(symbol)
  key=(hashlib.sha256(self._key.encode()).digest(),symbol)
  with _snapshot_locks[hash(key)%len(_snapshot_locks)]:
   now=time.monotonic();cached=_snapshot_cache.get(key)
   if cached and 0<=now-cached[0]<5:return copy.deepcopy(cached[1])
   result=self._snapshot_uncached(symbol)
   if result.get('status')=='OK':
    if len(_snapshot_cache)>=256:_snapshot_cache.clear()
    _snapshot_cache[key]=(time.monotonic(),copy.deepcopy(result))
   return result
 def _snapshot_uncached(self,symbol):
  res=self._http(HTTP_BASE,'/real-time/'+quote(symbol,safe=''),{'fmt':'json'})
  if res['status']!='OK':return res
  data=res.pop('payload')
  if not isinstance(data,dict) or data.get('code') not in (symbol,symbol.rsplit('.',1)[0]):return _result('INVALID_RESPONSE','/real-time/{symbol}')
  price=_number(data.get('close'));at=_timestamp(data.get('timestamp'),1)
  return {**res,'status':'OK' if price is not None and Decimal(price)>0 and at else 'NO_DATA','price':price,'event_time':at,'volume':_number(data.get('volume')),'volume_type':'unknown'}
 def intraday(self,symbol,interval='1m',start=None,end=None,max_points=1000):
  if not _valid_symbol(symbol) or interval not in ('1m','5m','1h') or any(x is not None and (type(x) is not int or x<0) for x in (start,end)) or start is not None and end is not None and start>end or max_points is not None and (type(max_points) is not int or max_points<1):return _result('INVALID_INPUT','/intraday')
  params={'interval':interval,'fmt':'json'}
  if start is not None:params['from']=start
  if end is not None:params['to']=end
  res=self._http(HTTP_BASE,'/intraday/'+quote(symbol,safe=''),params)
  if res['status']!='OK':return res
  rows=res.pop('payload')
  if not isinstance(rows,list):return _result('INVALID_RESPONSE','/intraday/{symbol}')
  out=[]
  ordered=sorted((x for x in rows if isinstance(x,dict) and type(x.get('timestamp')) is int),key=lambda x:x['timestamp'])
  for row in (ordered[-max_points:] if max_points is not None else ordered):
   if not isinstance(row,dict):continue
   ts=_timestamp(row.get('timestamp'),1);values={k:_number(row.get(k)) for k in ('open','high','low','close','volume')}
   if ts and all(values[k] is not None for k in ('open','high','low','close')):out.append({'symbol':symbol,'bar_open_at':ts,**values,'volume_type':'interval'})
  out=_unique_bars(out)
  if out is None:return _result('INVALID_RESPONSE','/intraday/{symbol}')
  return {**res,'status':'OK' if out else 'NO_DATA','bars':out}
 def us_quotes(self,symbol):
  if not _valid_symbol(symbol) or not symbol.endswith('.US'):return _result('INVALID_INPUT','/us-quote-delayed')
  res=self._http(HTTP_BASE,'/us-quote-delayed',{'s':symbol,'fmt':'json'})
  if res['status']!='OK':return res
  payload=res.pop('payload');rows=payload.get('data') if isinstance(payload,dict) else payload
  row=rows.get(symbol) if isinstance(rows,dict) else next((x for x in rows if isinstance(x,dict) and x.get('code')==symbol),None) if isinstance(rows,list) else None
  if not isinstance(row,dict):return {**res,'status':'NO_DATA'}
  if row.get('symbol',row.get('code',symbol))!=symbol:return _result('INVALID_RESPONSE','/us-quote-delayed')
  return {**res,'quote':{'symbol':symbol,'bid':_number(row.get('bidPrice',row.get('bid'))),'bid_at':_timestamp(row.get('bidTime'),1000),'bid_size':_number(row.get('bidSize')),'ask':_number(row.get('askPrice',row.get('ask'))),'ask_at':_timestamp(row.get('askTime'),1000),'ask_size':_number(row.get('askSize')),'documented_delay':'15-minute delayed endpoint'}}
 def market_status(self,exchange):
  if not isinstance(exchange,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,16}',exchange):return _result('INVALID_INPUT','/exchange-details')
  if not self._shared_status or not self._key:return self._market_status_uncached(exchange)
  key=(hashlib.sha256(self._key.encode()).digest(),exchange)
  with _status_locks[hash(key)%len(_status_locks)]:
   cached=_status_cache.get(key);now=time.monotonic()
   if cached and 0<=now-cached[0]<STATUS_CACHE_TTL_S:return copy.deepcopy(cached[1])
   result=self._market_status_uncached(exchange)
   if result.get('status')=='OK':
    if len(_status_cache)>=128:_status_cache.clear()
    _status_cache[key]=(time.monotonic(),copy.deepcopy(result))
   return result
 def _market_status_uncached(self,exchange):
  res=self._http(HTTP_BASE,'/exchange-details/'+quote(exchange,safe=''),{'fmt':'json'})
  if res['status']!='OK':return res
  data=res.pop('payload')
  if not isinstance(data,dict) or not isinstance(data.get('isOpen'),bool) or not isinstance(data.get('Code',exchange),str) or data.get('Code',exchange).upper()!=exchange.upper():return _result('INVALID_RESPONSE','/exchange-details/{exchange}')
  return {**res,'exchange':exchange,'exchange_open':data['isOpen'],'source_time':None,'timezone':data.get('Timezone') if isinstance(data.get('Timezone'),str) and re.fullmatch(r'[A-Za-z0-9_+/-]{1,64}',data['Timezone']) else None,'calendar':_calendar(data)}
 def websocket_trades(self,market,symbol,duration=2):return self.capture(str(market)+'_trades',symbol,duration)
 def websocket_quotes(self,market,symbol,duration=2):return self.capture(str(market)+'_quotes',symbol,duration)
 def websocket_status(self,market,symbol,duration=2):return self.capture(str(market)+'_status',symbol,duration)
 def capture(self,feed,symbol,duration=2,max_messages=50):
  transport={'connections_opened':0,'subscriptions_sent':0}
  def measured(*args,**kwargs):return _result(*args,**kwargs,**transport)
  endpoint=WS_FEEDS.get(feed)
  symbols=[symbol] if isinstance(symbol,str) else symbol
  if not endpoint or not isinstance(symbols,list) or not 1<=len(symbols)<=10 or any(not _valid_symbol(s) for s in symbols) or len(set(symbols))!=len(symbols) or type(duration) is not int or not 1<=duration<=5 or type(max_messages) is not int or not 1<=max_messages<=250:return measured('INVALID_INPUT','/ws')
  path='/ws/'+endpoint
  if not self._key:return measured('KEY_MISSING',path)
  try:
   factory=self._ws_factory
   if factory is None:
    try:from websockets.sync.client import connect as factory
    except ImportError:return measured('WEBSOCKET_DEPENDENCY_MISSING',path)
   url=WS_BASE+'/'+endpoint+'?'+urlencode({'api_token':self._key});messages=[];partial_messages=[]
   with (self._capacity.websocket(len(symbols)) if self._capacity else nullcontext()),factory(url,open_timeout=8,close_timeout=2,max_size=131072,max_queue=16,logger=_WS_LOGGER) as ws:
    transport['connections_opened']=1
    deadline=time.monotonic()+duration
    ws.send(json.dumps({'action':'subscribe','symbols':','.join(symbols)}));transport['subscriptions_sent']=len(symbols)
    while time.monotonic()<deadline and len(messages)<max_messages:
     try:raw=ws.recv(timeout=max(.01,deadline-time.monotonic()))
     except TimeoutError:break
     received_at=datetime.now(timezone.utc).isoformat()
     if not isinstance(raw,(str,bytes)) or len(raw)>131072:continue
     try:row=json.loads(raw,parse_float=str,parse_constant=lambda _:None)
     except (ValueError,TypeError):continue
     if not isinstance(row,dict):continue
     if str(row.get('status_code',row.get('status'))) in ('401','402','403'):return measured('ENTITLEMENT_UNVERIFIED',path)
     if str(row.get('status_code'))=='429':
      from eodhd_capacity import retry_seconds
      seconds=self._capacity.ws_limited() if self._capacity else retry_seconds(None)
      return measured('RATE_LIMIT',path,retry_after_s=seconds)
     actual=row.get('s')
     if actual not in symbols:continue
     at=_timestamp(row.get('t'),1000)
     if not at:
      if feed.endswith('trades'):
       price=_number(row.get('p'))
       if price is not None and Decimal(price)>0:partial_messages.append({'symbol':actual,'received_at':received_at,'price':price,'trade_size':_number(row.get('v'))})
      elif feed.endswith('quotes'):
       bid=_number(row.get('bp'));ask=_number(row.get('ap'))
       if bid is not None or ask is not None:partial_messages.append({'symbol':actual,'received_at':received_at,'bid':bid,'ask':ask})
      if len(partial_messages)>=max_messages:break
      continue
     if feed.endswith('trades'):
      price=_number(row.get('p'))
      if price is None or Decimal(price)<=0:continue
      messages.append({'symbol':actual,'event_time':at,'received_at':received_at,'price':price,'trade_size':_number(row.get('v')),'market_session':row.get('ms') if row.get('ms') in ('open','closed','extended-hours','extended hours') else None})
     elif feed.endswith('quotes'):
      messages.append({'symbol':actual,'event_time':at,'received_at':received_at,'bid':_number(row.get('bp')),'ask':_number(row.get('ap')),'bid_size':_number(row.get('bs')),'ask_size':_number(row.get('as'))})
     else:
      status=row.get('h');reason=row.get('r')
      messages.append({'symbol':actual,'event_time':at,'received_at':received_at,'trading_status':status if isinstance(status,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,16}',status) else None,'reason':reason if isinstance(reason,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,16}',reason) else None})
   # Counts describe the whole batch, before the adapter splits it by symbol.
   # Reaching the bound does not prove that an unread message exists.
   return measured('OK' if messages else 'NO_MESSAGES',path,messages=messages,message_count=len(messages),partial_messages=partial_messages,batch_valid_count=len(messages),batch_partial_count=len(partial_messages),batch_limit_reached=len(messages)>=max_messages or len(partial_messages)>=max_messages)
  except Exception as error:
   code=getattr(getattr(error,'response',None),'status_code',None)
   if code in (401,402,403):return measured('ENTITLEMENT_UNVERIFIED',path,http_status=code)
   if getattr(error,'code',None) in ('PROVIDER_RATE_BUDGET','EODHD_WS_CAPACITY'):return measured('LOCAL_BUDGET_EXHAUSTED',path,budget_reason=error.code,retry_after_s=getattr(error,'retry_after_s',None))
   if code==429:
    from eodhd_capacity import retry_seconds
    headers=getattr(error.response,'headers',None)
    seconds=self._capacity.ws_limited(headers) if self._capacity else retry_seconds(headers)
    return measured('RATE_LIMIT',path,retry_after_s=seconds)
   return measured('NETWORK_OR_RESPONSE_ERROR',path)
