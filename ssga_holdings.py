"""Read published holdings for the configured US Select Sector SPDR funds."""
import io, math, re, urllib.error, urllib.request, zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

ALLOWED={'XLK','XLV','XLF','XLI','XLE','XLY','XLP','XLB','XLU','XLRE','XLC'}
BASE='https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-'
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
MAX_FILE=5*1024*1024
MAX_XML=12*1024*1024

class HoldingsUnavailable(ValueError):pass

class _NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def _xml(z,name):
 info=z.getinfo(name)
 if info.file_size>MAX_XML:raise HoldingsUnavailable('ISSUER_RESPONSE_TOO_LARGE')
 return ET.fromstring(z.read(info))

def _style_percent(z):
 if 'xl/styles.xml' not in z.namelist():return set()
 root=_xml(z,'xl/styles.xml');custom={}
 for x in root.findall('s:numFmts/s:numFmt',NS):custom[x.get('numFmtId')]=x.get('formatCode','')
 result=set()
 for i,x in enumerate(root.findall('s:cellXfs/s:xf',NS)):
  num=x.get('numFmtId','0')
  if num in ('9','10') or '%' in custom.get(num,''):result.add(i)
 return result

def parse(raw,symbol):
 if symbol not in ALLOWED or not isinstance(raw,bytes) or len(raw)>MAX_FILE:raise HoldingsUnavailable('ISSUER_INVALID_RESPONSE')
 try:
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   names=z.namelist()
   if sum(i.file_size for i in z.infolist())>MAX_XML*2:raise HoldingsUnavailable('ISSUER_RESPONSE_TOO_LARGE')
   shared=[]
   if 'xl/sharedStrings.xml' in names:
    shared=[''.join(t.text or '' for t in x.findall('.//s:t',NS)) for x in _xml(z,'xl/sharedStrings.xml').findall('s:si',NS)]
   percent_styles=_style_percent(z)
   sheets=[x for x in names if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',x)]
   if not sheets:raise HoldingsUnavailable('ISSUER_INVALID_RESPONSE')
   tables=[]
   for sheet in sheets:
    for row in _xml(z,sheet).findall('.//s:row',NS):
     values=[]
     for cell in row.findall('s:c',NS):
      ref=cell.get('r','');col=re.match(r'[A-Z]+',ref)
      if not col:continue
      column=0
      for ch in col.group():column=column*26+ord(ch)-64
      if column>128:continue
      while len(values)<column:values.append(('',False))
      v=cell.find('s:v',NS);value=v.text if v is not None and v.text is not None else ''.join(x.text or '' for x in cell.findall('.//s:t',NS))
      if cell.get('t')=='s':value=shared[int(value)]
      values[column-1]=(str(value or '').strip(),int(cell.get('s','0')) in percent_styles)
     tables.append(values)
   ticker_seen=None;as_of=None
   for row in tables:
    if len(row)<2:continue
    key=row[0][0].strip().lower().rstrip(':');value=row[1][0].strip()
    if key=='ticker symbol':ticker_seen=value.upper()
    if key=='holdings':
     match=re.fullmatch(r'As of (\d{2}-[A-Za-z]{3}-\d{4})',value,re.I)
     if match:
      try:as_of=datetime.strptime(match.group(1),'%d-%b-%Y').date().isoformat()
      except ValueError:pass
   if ticker_seen!=symbol or not as_of:raise HoldingsUnavailable('ISSUER_IDENTITY_OR_DATE_INVALID')
   for i,row in enumerate(tables):
    headers=[re.sub(r'[^a-z0-9]+',' ',v.lower()).strip() for v,_ in row]
    def find(accepted):return next((j for j,v in enumerate(headers) if v in accepted),None)
    name=find({'name','holding name','security name','company name','security description','description'})
    ticker=find({'ticker','symbol','ticker symbol','identifier'})
    weight=find({'weight','weight %','weight percent','weight percentage','portfolio weight','portfolio weight %','% of fund','percent of fund'})
    if None in (name,ticker,weight):continue
    result=[];seen=set()
    for cells in tables[i+1:]:
     if max(name,ticker,weight)>=len(cells):continue
     n=cells[name][0];t=cells[ticker][0];w,percent=cells[weight]
     try:value=float(w.replace(',','').replace('%',''))*(100 if percent and '%' not in w else 1)
     except ValueError:continue
     if not n or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.\-/]{0,19}',t) or not math.isfinite(value) or not 0<value<=100 or t.upper() in seen:continue
     seen.add(t.upper());result.append({'ticker':t,'name':n[:200],'exchange':None,'weight':value})
    if result:return {'rows':sorted(result,key=lambda r:(-r['weight'],r['ticker'])),'as_of':as_of}
  raise HoldingsUnavailable('ISSUER_FORMAT_UNRECOGNIZED')
 except HoldingsUnavailable:raise
 except (ValueError,KeyError,TypeError,IndexError,ET.ParseError,zipfile.BadZipFile,OverflowError):raise HoldingsUnavailable('ISSUER_INVALID_RESPONSE') from None

def fetch(symbol):
 if not isinstance(symbol,str) or not symbol.endswith('.US') or symbol[:-3] not in ALLOWED:raise HoldingsUnavailable('ISSUER_UNSUPPORTED')
 code=symbol[:-3];url=BASE+code.lower()+'.xlsx'
 try:
  opener=urllib.request.build_opener(_NoRedirect())
  with opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}),timeout=12) as response:raw=response.read(MAX_FILE+1)
 except urllib.error.HTTPError as error:raise HoldingsUnavailable('ISSUER_HTTP_'+str(error.code)) from None
 except (OSError,ValueError):raise HoldingsUnavailable('ISSUER_NETWORK_ERROR') from None
 return parse(raw,code)
