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

def refresh(connect,fetcher=None,at=None):
    """Fetch immediately, with a shared one-minute cooldown; preserve last good news."""
    import time
    stamp=time.time() if at is None else at
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT attempted FROM news_refresh WHERE id=1').fetchone()
        if row and stamp-row['attempted']<60:
            return {'ok':True,'cached':True,'message':'Nyheder er netop forsøgt opdateret. Viser de senest gemte nyheder; prøv igen om et minut.'}
        c.execute("INSERT INTO news_refresh(id,attempted) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET attempted=excluded.attempted",(stamp,))
    try:
        items=(fetcher or fetch)()
        if not items:raise ValueError('empty feed')
        with connect() as c:
            before=c.execute('SELECT COUNT(*) FROM news_items').fetchone()[0]
            for item in items:
                c.execute('INSERT INTO news_items(title,url,published,summary,observed,digest) VALUES(?,?,?,?,?,?) ON CONFLICT(digest) DO UPDATE SET title=excluded.title,summary=excluded.summary',(item['title'],item['url'],item['published'],item['summary'],item['observed'],item['digest']))
            added=c.execute('SELECT COUNT(*) FROM news_items').fetchone()[0]-before
            c.execute("UPDATE news_refresh SET succeeded=?,error=NULL WHERE id=1",(stamp,))
        return {'ok':True,'cached':False,'message':f'ECB-nyheder hentet. {added} nye meddelelser; dubletter er fjernet.'}
    except Exception:
        message='ECB-feedet kunne ikke hentes. Tidligere nyheder er bevaret. Prøv igen om et minut.'
        with connect() as c:c.execute('UPDATE news_refresh SET error=? WHERE id=1',(message,))
        return {'ok':False,'message':message}
