"""Official ECB press-release RSS. Factual headlines, never trade signals."""
import hashlib,html,re
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import urllib.request
import xml.etree.ElementTree as ET
from pluto import NoRedirect

URL='https://www.ecb.europa.eu/rss/press.html'

def clean(text):return html.unescape(re.sub(r'<[^>]*>','',text or '')).strip()[:4000]

def parse(raw,observed=None):
    observed=observed or datetime.now(timezone.utc)
    if len(raw)>1048576 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('invalid feed')
    root=ET.fromstring(raw)
    if root.tag not in ['rss','{http://www.w3.org/2005/Atom}feed']:raise ValueError('not a news feed')
    entries=root.findall('./channel/item') if root.tag=='rss' else root.findall('{http://www.w3.org/2005/Atom}entry')
    items=[]
    for entry in entries[:50]:
        if root.tag=='rss':
            title=clean(entry.findtext('title'));link=(entry.findtext('link') or '').strip();published=parsedate_to_datetime(entry.findtext('pubDate') or '');summary=clean(entry.findtext('description'))
        else:
            ns='{http://www.w3.org/2005/Atom}'
            title=clean(entry.findtext(ns+'title'));summary=clean(entry.findtext(ns+'summary'))
            link=next((x.attrib.get('href','') for x in entry.findall(ns+'link') if x.attrib.get('rel','alternate')=='alternate'),'')
            published=datetime.fromisoformat((entry.findtext(ns+'published') or entry.findtext(ns+'updated') or '').replace('Z','+00:00'))
        parsed=urlsplit(link)
        if not title or parsed.scheme!='https' or parsed.hostname!='www.ecb.europa.eu' or parsed.username or parsed.password:raise ValueError('invalid source link')
        if not published.tzinfo or published>observed:raise ValueError('invalid publication time')
        timestamp=published.astimezone(timezone.utc).isoformat()
        digest=hashlib.sha256((link+'\n'+timestamp).encode()).hexdigest()
        items.append({'title':title,'url':link,'published':timestamp,'summary':summary,'observed':observed.isoformat(),'digest':digest})
    return items

def fetch():
    request=urllib.request.Request(URL,headers={'Accept':'application/rss+xml, application/xml','User-Agent':'ESCAPE/0.4'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=8) as response:return parse(response.read(1048577))
