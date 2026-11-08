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
 from urllib.parse import urljoin,urlsplit
 opener=urllib.request.build_opener(NoRedirect());seen=set()
 for _ in range(4):
  u=urlsplit(url)
  if u.scheme!='https' or u.netloc!='www.ishares.com' or u.query or u.fragment or url in seen:raise HoldingsUnavailable('ISHARES_UNSAFE_REDIRECT')
  if not (u.path.startswith('/us/products/') or u.path.startswith('/de/privatanleger/de/produkte/') or u.path=='/de/product-sitemap.xml'):raise HoldingsUnavailable('ISHARES_UNSAFE_REDIRECT')
  seen.add(url)
  try:
   with opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'text/csv,text/html,*/*'}),timeout=15) as response:data=response.read(limit+1)
   break
  except urllib.error.HTTPError as error:
   location=error.headers.get('Location') if error.headers else None
   if error.code in (301,302,303,307,308) and location:url=urljoin(url,location);continue
   raise HoldingsUnavailable('ISHARES_HTTP_'+str(error.code)) from None
  except (OSError,ValueError):raise HoldingsUnavailable('ISHARES_NETWORK_ERROR') from None
 else:raise HoldingsUnavailable('ISHARES_TOO_MANY_REDIRECTS')
 if len(data)>limit:raise HoldingsUnavailable('ISHARES_RESPONSE_TOO_LARGE')
 return data

def fetch(symbol):
 if not isinstance(symbol,str) or not symbol.endswith('.US') or symbol[:-3] not in ALLOWED:raise HoldingsUnavailable('ISHARES_UNSUPPORTED')
 path,name=discover(_get(DIRECTORY,MAX_DIRECTORY),symbol[:-3]);return parse(_get(BASE+path+'/latest-holdings.csv',MAX_CSV),name)

EU_SITEMAP='https://www.ishares.com/de/product-sitemap.xml'
EU_PATH=re.compile(r'^/de/privatanleger/de/produkte/(\d{5,9})/([a-z0-9-]+-fund)$')
EU_CSV_PATH=re.compile(r'^/de/privatanleger/de/produkte/(\d{5,9})/[a-z0-9-]+/latest-holdings\.csv$')

def _fund_key(value):
 return re.sub(r'[^a-z0-9]','',value.casefold())

def discover_europe(raw,name):
 from xml.etree import ElementTree as ET
 from urllib.parse import urlsplit
 if not isinstance(raw,bytes) or len(raw)>8*1024*1024 or not isinstance(name,str):raise HoldingsUnavailable('ISHARES_INVALID_DIRECTORY')
 if not re.fullmatch(r'iShares STOXX Europe 600 .+ UCITS ETF \(DE\)',name,re.I):raise HoldingsUnavailable('ISHARES_FUND_NOT_VERIFIED')
 try:root=ET.fromstring(raw)
 except ET.ParseError:raise HoldingsUnavailable('ISHARES_INVALID_DIRECTORY') from None
 expected=_fund_key(name);matches=set()
 for node in root.iter():
  if node.tag.rsplit('}',1)[-1]!='loc' or not node.text:continue
  u=urlsplit(node.text.strip());match=EU_PATH.fullmatch(u.path)
  if u.scheme=='https' and u.netloc=='www.ishares.com' and not u.query and not u.fragment and match and _fund_key(match.group(2)[:-5])==expected:matches.add(u.path)
 if len(matches)!=1:raise HoldingsUnavailable('ISHARES_FUND_NOT_VERIFIED')
 return next(iter(matches))

def europe_csv_url(raw,path,code,name):
 import html
 from urllib.parse import urlsplit
 if not isinstance(raw,bytes) or len(raw)>4*1024*1024:raise HoldingsUnavailable('ISHARES_INVALID_RESPONSE')
 try:text=raw.decode('utf-8-sig')
 except UnicodeDecodeError:raise HoldingsUnavailable('ISHARES_INVALID_RESPONSE') from None
 title=re.search(r'<title[^>]*>(.*?)</title>',text,re.I|re.S)
 if not title:raise HoldingsUnavailable('ISHARES_FUND_NOT_VERIFIED')
 parts=[x.strip() for x in html.unescape(title.group(1)).split('|')]
 if len(parts)<3 or _fund_key(parts[0])!=_fund_key(name) or parts[1].upper()!=code or parts[2].casefold()!='ishares':raise HoldingsUnavailable('ISHARES_FUND_NOT_VERIFIED')
 current=EU_PATH.fullmatch(path)
 if not current:raise HoldingsUnavailable('ISHARES_FUND_NOT_VERIFIED')
 candidates=set()
 for match in re.finditer(r'"contentUrl"\s*:\s*"([^"]*latest-holdings\.csv)"',html.unescape(text).replace('\\/','/'),re.I):
  u=urlsplit(match.group(1));p=EU_CSV_PATH.fullmatch(u.path)
  if u.scheme in ('http','https') and u.netloc=='www.ishares.com' and not u.query and not u.fragment and p and p.group(1)==current.group(1):candidates.add(u.path)
 if len(candidates)!=1:raise HoldingsUnavailable('ISHARES_FUND_NOT_VERIFIED')
 return BASE+next(iter(candidates))

def parse_europe(raw):
 if not isinstance(raw,bytes) or len(raw)>MAX_CSV:raise HoldingsUnavailable('ISHARES_RESPONSE_TOO_LARGE')
 try:
  rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))));date=None;header=None
  clean=lambda x:' '.join(x.replace('\u00a0',' ').split()).casefold()
  months={'jan':1,'feb':2,'mär':3,'mrz':3,'apr':4,'mai':5,'jun':6,'jul':7,'aug':8,'sep':9,'okt':10,'nov':11,'dez':12}
  for i,row in enumerate(rows[:40]):
   if len(row)>1 and clean(row[0])=='fondsposition per':
    match=re.fullmatch(r'(\d{1,2})\.([A-Za-zÄÖÜäöü]{3})\.(\d{4})',row[1].strip())
    if match and match.group(2).casefold() in months:date=datetime(int(match.group(3)),months[match.group(2).casefold()],int(match.group(1))).date().isoformat()
   h=[clean(v) for v in row]
   if all(x in h for x in ('emittententicker','name','gewichtung (%)','anlageklasse')):header=(i,h);break
  if not date or not header:raise HoldingsUnavailable('ISHARES_FORMAT_UNRECOGNIZED')
  index,h=header;col={k:h.index(k) for k in ('emittententicker','name','gewichtung (%)','anlageklasse')};exchange=h.index('börse') if 'börse' in h else None
  result=[];seen=set()
  for row in rows[index+1:]:
   if len(row)<=max(col.values()):continue
   ticker=row[col['emittententicker']].strip();title=row[col['name']].strip();asset=clean(row[col['anlageklasse']]);venue=row[exchange].strip() if exchange is not None and exchange<len(row) else ''
   try:weight=float(row[col['gewichtung (%)']].replace('.','').replace(',','.').replace('%','').strip())
   except ValueError:continue
   key=(ticker.upper(),venue.upper())
   if asset!='aktien' or not title or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9. /\-]{0,19}',ticker) or not math.isfinite(weight) or not 0<weight<=100 or key in seen:continue
   seen.add(key);result.append({'ticker':ticker,'name':title[:200],'exchange':venue[:40] if venue and venue!='-' else None,'weight':weight,'identifier':None})
  if not result:raise HoldingsUnavailable('ISHARES_NO_HOLDINGS')
  return {'rows':sorted(result,key=lambda r:(-r['weight'],r['ticker'])),'as_of':date}
 except HoldingsUnavailable:raise
 except (UnicodeDecodeError,csv.Error,ValueError,TypeError,IndexError):raise HoldingsUnavailable('ISHARES_INVALID_RESPONSE') from None

def fetch_europe(symbol,name):
 if not isinstance(symbol,str) or not re.fullmatch(r'EX[HV][1-9]\.XETRA',symbol):raise HoldingsUnavailable('ISHARES_UNSUPPORTED')
 code=symbol.split('.')[0];path=discover_europe(_get(EU_SITEMAP,8*1024*1024),name)
 url=europe_csv_url(_get(BASE+path,4*1024*1024),path,code,name)
 return parse_europe(_get(url,MAX_CSV))
