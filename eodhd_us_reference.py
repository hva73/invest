"""Bounded read-only EODHD US symbol catalogue, with the existing rate budget."""
import codecs,io,json,os,re,threading,time,urllib.error,urllib.request
from datetime import datetime,timezone
from urllib.parse import urlencode
from hotwatch_contract import EngineError

URL='https://eodhd.com/api/exchange-symbol-list/US'
LIMIT=64*1024*1024
_lock=threading.Lock()
_cache=None

class ReferenceUnavailable(ValueError):pass

class _NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def _parse_stream(stream):
 """Parse a bounded JSON array incrementally, retaining only US stock rows."""
 from report_validation import unique_object
 decoder=json.JSONDecoder(object_pairs_hook=unique_object,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()));utf8=codecs.getincrementaldecoder('utf-8')();buffer='';position=0;state='start';size=0;count=0;rows=[];eof=False
 try:
  while not eof:
   chunk=stream.read(65536);eof=not chunk;size+=len(chunk)
   if size>LIMIT:raise ReferenceUnavailable('EODHD_US_REFERENCE_SIZE')
   buffer+=utf8.decode(chunk,final=eof)
   while True:
    while position<len(buffer) and buffer[position].isspace():position+=1
    if position>=len(buffer):break
    char=buffer[position]
    if state=='start':
     if char!='[':raise ValueError()
     position+=1;state='first';continue
    if state in ('first','value'):
     if char==']' and state=='first':position+=1;state='end';continue
     if char!='{':raise ValueError()
     try:item,end=decoder.raw_decode(buffer,position)
     except json.JSONDecodeError:
      if eof or len(buffer)-position>1048576:raise ValueError()
      break
     if not isinstance(item,dict):raise ValueError()
     count+=1
     if count>500000:raise ValueError()
     code=item.get('Code');exchange=item.get('Exchange');isin=item.get('Isin') or item.get('ISIN')
     if isinstance(code,str) and re.fullmatch(r'[A-Za-z0-9.\-]{1,32}',code) and exchange in ('NYSE','NASDAQ') and item.get('Country')=='USA' and item.get('Currency')=='USD' and item.get('Type')=='Common Stock' and isinstance(isin,str) and re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',isin):
      rows.append({key:item.get(key) for key in ('Code','Name','Country','Exchange','Currency','Type')}|{'Isin':isin})
     position=end;state='delimiter';continue
    if state=='delimiter':
     if char==',':position+=1;state='value';continue
     if char==']':position+=1;state='end';continue
     raise ValueError()
    if state=='end':raise ValueError()
   if position>1048576:buffer=buffer[position:];position=0
  if state!='end':raise ValueError()
  if not rows:raise ValueError()
  return rows
 except ReferenceUnavailable:raise
 except (ValueError,TypeError,UnicodeError,RecursionError):raise ReferenceUnavailable('EODHD_US_REFERENCE_INVALID') from None

def parse_reference(raw,received_at):
 if not isinstance(raw,bytes):raise ReferenceUnavailable('EODHD_US_REFERENCE_INVALID')
 return {'received_at':received_at,'rows':_parse_stream(io.BytesIO(raw))}

def get_reference(connect,uid,opener=None):
 global _cache
 from hotwatch_adapters import reserve
 key=os.environ.get('ESCAPE_EODHD_API_KEY','').strip()
 if not key or os.environ.get('ESCAPE_HW_EODHD_REST_ENABLED')!='1':raise ReferenceUnavailable('EODHD_US_REFERENCE_DISABLED')
 with _lock:
  if opener is None and _cache and 0<=time.monotonic()-_cache[0]<3600:return _cache[1]
  try:
   reserve(connect,uid,'eodhd',purpose='holding_identity')
   client=opener or urllib.request.build_opener(_NoRedirect())
   url=URL+'?'+urlencode({'fmt':'json','api_token':key})
   with client.open(urllib.request.Request(url,headers={'Accept':'application/json'}),timeout=20) as response:rows=_parse_stream(response)
   result={'received_at':datetime.now(timezone.utc).isoformat(),'rows':rows}
  except EngineError:raise
  except ReferenceUnavailable:raise
  except urllib.error.HTTPError as error:raise ReferenceUnavailable('EODHD_US_REFERENCE_HTTP_'+str(error.code)) from None
  except Exception:raise ReferenceUnavailable('EODHD_US_REFERENCE_UNAVAILABLE') from None
  if opener is None:_cache=(time.monotonic(),result)
  return result
