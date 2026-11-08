"""Read verified public holdings of configured US-listed iShares ETFs."""
import csv, io, math, re, urllib.error, urllib.request
from datetime import datetime
from html.parser import HTMLParser

ALLOWED={'IXN','IXJ','IXG','EXI','IXC','RXI','KXI','MXI','JXI','IXP','EUFN'}
DIRECTORY='https://www.ishares.com/us/products/etf-investments'
BASE='https://www.ishares.com'
MAX_DIRECTORY=4*1024*1024
MAX_CSV=5*1024*1024
PATH=re.compile(r'^/us/products/\d{5,9}/[a-z0-9-]+$')

class HoldingsUnavailable(ValueError):pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

class ProductLinks(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.current=None;self.links=[]
 def handle_starttag(self,tag,attrs):
  if tag=='a':
   href=dict(attrs).get('href','')
   self.current=[href,[]] if PATH.fullmatch(href) else None
 def handle_data(self,data):
  if self.current:self.current[1].append(data)
 def handle_endtag(self,tag):
  if tag=='a' and self.current:
   self.links.append((self.current[0],' '.join(''.join(self.current[1]).split())));self.current=None

def discover(raw,code):
 if code not in ALLOWED or len(raw)>MAX_DIRECTORY:raise HoldingsUnavailable('ISHARES_INVALID_DIRECTORY')
 try:text=raw.decode('utf-8-sig')
 except (UnicodeDecodeError,AttributeError):raise HoldingsUnavailable('ISHARES_INVALID_DIRECTORY') from None
 parser=ProductLinks();parser.feed(text)
 paths={path for path,label in parser.links if label.upper()==code}
 if len(paths)!=1:raise HoldingsUnavailable('ISHARES_FUND_NOT_VERIFIED')
 path=next(iter(paths));names={label for link,label in parser.links if link==path and label.lower().startswith('ishares ') and len(label)>len(code)}
 if len(names)!=1:raise HoldingsUnavailable('ISHARES_FUND_NOT_VERIFIED')
 return path,next(iter(names))

def parse(raw,name):
 if not isinstance(raw,bytes) or len(raw)>MAX_CSV:raise HoldingsUnavailable('ISHARES_RESPONSE_TOO_LARGE')
 try:
  text=raw.decode('utf-8-sig');rows=list(csv.reader(io.StringIO(text)))
  clean=lambda x:' '.join(x.replace('\u00a0',' ').split()).casefold()
  if not rows or not rows[0] or clean(rows[0][0])!=clean(name):raise HoldingsUnavailable('ISHARES_IDENTITY_MISMATCH')
  date=None;header=None
  for i,row in enumerate(rows[:40]):
   if len(row)>1 and clean(row[0])=='fund holdings as of':
    for fmt in ('%b %d, %Y','%B %d, %Y','%d/%b/%Y','%d %b %Y'):
     try:date=datetime.strptime(row[1].strip(),fmt).date().isoformat();break
     except ValueError:pass
   h=[clean(v) for v in row]
   if all(x in h for x in ('ticker','name','weight (%)','asset class')):header=(i,h);break
  if not date or not header:raise HoldingsUnavailable('ISHARES_FORMAT_UNRECOGNIZED')
  index,h=header;col={k:h.index(k) for k in ('ticker','name','weight (%)','asset class')};exchange=h.index('exchange') if 'exchange' in h else None
  result=[];seen=set()
  for row in rows[index+1:]:
   if len(row)<=max(col.values()):continue
   ticker=row[col['ticker']].strip();title=row[col['name']].strip();asset=clean(row[col['asset class']]);venue=row[exchange].strip() if exchange is not None and exchange<len(row) else ''
   try:weight=float(row[col['weight (%)']].replace(',','').replace('%','').strip())
   except ValueError:continue
   key=(ticker.upper(),venue.upper())
   if asset!='equity' or not title or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.\-/]{0,19}',ticker) or not math.isfinite(weight) or not 0<weight<=100 or key in seen:continue
   seen.add(key);result.append({'ticker':ticker,'name':title[:200],'exchange':venue[:40] if venue and venue!='-' else None,'weight':weight,'identifier':None})
  if not result:raise HoldingsUnavailable('ISHARES_NO_HOLDINGS')
  return {'rows':sorted(result,key=lambda r:(-r['weight'],r['ticker'])),'as_of':date}
 except HoldingsUnavailable:raise
 except (UnicodeDecodeError,csv.Error,ValueError,TypeError,IndexError):raise HoldingsUnavailable('ISHARES_INVALID_RESPONSE') from None

def _get(url,limit):
 try:
  opener=urllib.request.build_opener(NoRedirect())
  with opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'text/csv,text/html,*/*'}),timeout=15) as response:data=response.read(limit+1)
 except urllib.error.HTTPError as error:raise HoldingsUnavailable('ISHARES_HTTP_'+str(error.code)) from None
 except (OSError,ValueError):raise HoldingsUnavailable('ISHARES_NETWORK_ERROR') from None
 if len(data)>limit:raise HoldingsUnavailable('ISHARES_RESPONSE_TOO_LARGE')
 return data

def fetch(symbol):
 if not isinstance(symbol,str) or not symbol.endswith('.US') or symbol[:-3] not in ALLOWED:raise HoldingsUnavailable('ISHARES_UNSUPPORTED')
 path,name=discover(_get(DIRECTORY,MAX_DIRECTORY),symbol[:-3]);return parse(_get(BASE+path+'/latest-holdings.csv',MAX_CSV),name)
