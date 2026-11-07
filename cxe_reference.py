"""Read and validate Cboe's public CXE instrument reference, without orders."""
import csv,io,re,threading,time,urllib.request
from datetime import datetime,timedelta,timezone

URL='https://accounteu.cboe.com/cxe/market_data/symbol_listing/csv/'
LIMIT=32*1024*1024
_lock=threading.Lock()
_cache=None

class ReferenceUnavailable(ValueError):pass

class _NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def parse_reference(raw,now=None):
 now=now or datetime.now(timezone.utc)
 if not isinstance(raw,bytes) or len(raw)>LIMIT:raise ReferenceUnavailable('CXE_REFERENCE_SIZE')
 try:
  stream=io.StringIO(raw.decode('utf-8-sig'));metadata=next(csv.reader([stream.readline()]))
  fields=dict(item.split('=',1) for item in metadata if '=' in item)
  if fields.get('environment')!='PROD' or fields.get('warning'):raise ValueError()
  created=datetime.strptime(fields['created']+' '+fields['time'],'%Y-%m-%d %H:%MZ').replace(tzinfo=timezone.utc)
  if created>now+timedelta(minutes=5) or now-created>timedelta(hours=72):raise ReferenceUnavailable('CXE_REFERENCE_STALE')
  reader=csv.DictReader(stream)
  required={'company_name','bats_name','isin','currency','mic','bloomberg_primary','asset_class','live','corporate_action_status'}
  if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):raise ValueError()
  rows=[]
  for index,row in enumerate(reader):
   if index>=250000:raise ValueError()
   if row.get('live','').lower()!='t' or row.get('corporate_action_status','').strip():continue
   symbol=row.get('bats_name','');isin=row.get('isin','');primary=row.get('bloomberg_primary','').split()
   if not symbol or not re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]',isin) or len(primary)<3 or primary[-1]!='Equity':continue
   rows.append({'symbol':symbol,'primary_ticker':primary[0],'name':row.get('company_name',''),'isin':isin,'currency':row.get('currency',''),'instrument_type':row.get('asset_class',''),'mic':row.get('mic','')})
  if not rows:raise ValueError()
  return {'created_at':created.isoformat(),'rows':rows}
 except ReferenceUnavailable:raise
 except (KeyError,ValueError,TypeError,UnicodeError,StopIteration,csv.Error):raise ReferenceUnavailable('CXE_REFERENCE_INVALID') from None

def get_reference(now=None,opener=None):
 global _cache
 now=now or datetime.now(timezone.utc)
 with _lock:
  if opener is None and _cache and 0<=time.monotonic()-_cache[0]<1800:
   if now-datetime.fromisoformat(_cache[1]['created_at'])<=timedelta(hours=72):return _cache[1]
  try:
   client=opener or urllib.request.build_opener(_NoRedirect())
   with client.open(urllib.request.Request(URL,headers={'Accept':'text/csv','User-Agent':'Mozilla/5.0'}),timeout=15) as response:
    raw=response.read(LIMIT+1)
   result=parse_reference(raw,now)
  except ReferenceUnavailable:raise
  except Exception:raise ReferenceUnavailable('CXE_REFERENCE_UNAVAILABLE') from None
  if opener is None:_cache=(time.monotonic(),result)
  return result
