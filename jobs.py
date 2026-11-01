"""Durable jobs for a cron invocation; no resident process or paid providers."""
import hashlib,json,math,sqlite3,time,uuid
from datetime import datetime,timezone,timedelta,date
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import urllib.request
from pluto import NoRedirect

ECB_URL='https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
SOURCE='Den Europæiske Centralbank'

def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id), dedupe TEXT NOT NULL UNIQUE, status TEXT NOT NULL, available REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, lease TEXT, lease_until REAL, result TEXT, created REAL NOT NULL)')
    if 'portfolio_id' not in {r['name'] for r in c.execute('PRAGMA table_info(jobs)')}:c.execute('ALTER TABLE jobs ADD COLUMN portfolio_id INTEGER REFERENCES portfolios(id)')
    c.execute('CREATE TABLE IF NOT EXISTS fx_snapshots(id INTEGER PRIMARY KEY, source_date TEXT NOT NULL, observed TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), slot TEXT NOT NULL, created TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(user_id,slot))')
    c.execute('CREATE TABLE IF NOT EXISTS news_items(id INTEGER PRIMARY KEY,title TEXT NOT NULL,url TEXT NOT NULL,published TEXT NOT NULL,summary TEXT NOT NULL,observed TEXT NOT NULL,digest TEXT NOT NULL UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS worker_state(id INTEGER PRIMARY KEY CHECK(id=1), heartbeat REAL NOT NULL)')

def parse_ecb(raw,observed=None):
    observed=observed or datetime.now(timezone.utc)
    if len(raw)>262144 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('invalid XML')
    root=ET.fromstring(raw);dated=[x for x in root.iter() if 'time' in x.attrib]
    if len(dated)!=1:raise ValueError('missing source date')
    source_date=date.fromisoformat(dated[0].attrib['time'])
    if source_date>observed.date():raise ValueError('future data')
    rates={}
    for element in dated[0]:
        code=element.attrib.get('currency','');value=float(element.attrib.get('rate','nan'))
        if len(code)!=3 or not code.isascii() or not code.isalpha() or code.upper()!=code or code in rates or not math.isfinite(value) or value<=0:raise ValueError('invalid rate')
        rates[code]=value
    if not rates or 'DKK' not in rates:raise ValueError('missing DKK reference')
    return {'source':SOURCE,'source_url':ECB_URL,'source_date':source_date.isoformat(),'observed':observed.isoformat(),'base':'EUR','rates':rates,'kind':'Daglige referencekurser — ikke livekurser eller handelspriser'}

def fetch_ecb():
    request=urllib.request.Request(ECB_URL,headers={'Accept':'application/xml','User-Agent':'ESCAPE/0.4'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=8) as response:
        return parse_ecb(response.read(262145))

def enqueue(c,kind,user_id,dedupe,when=None,portfolio_id=None):
    when=time.time() if when is None else when
    c.execute("INSERT INTO jobs(kind,user_id,dedupe,status,available,created,portfolio_id) VALUES(?,?,?,'queued',?,?,?) ON CONFLICT(dedupe) DO NOTHING",(kind,user_id,dedupe,when,when,portfolio_id))

def schedule(connect,at=None):
    at=at or datetime.now(timezone.utc)
    utc=at.astimezone(timezone.utc);local=at.astimezone(ZoneInfo('Europe/Copenhagen'));stamp=utc.timestamp()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        admin=c.execute("SELECT id FROM users WHERE role='admin' AND active=1 ORDER BY id LIMIT 1").fetchone()
        if admin:
            enqueue(c,'ecb',admin['id'],'ecb:'+utc.strftime('%Y-%m-%dT%H'),stamp)
            enqueue(c,'news',admin['id'],'news:'+utc.strftime('%Y-%m-%dT%H'),stamp)
        for portfolio in c.execute("SELECT p.id,p.user_id FROM portfolios p JOIN users u ON u.id=p.user_id JOIN oauth_tokens t ON t.user_id=p.user_id WHERE p.source='pluto' AND p.active=1 AND u.active=1 AND t.expires>?",(stamp,)).fetchall():
            enqueue(c,'pluto_data',portfolio['user_id'],'pluto:'+str(portfolio['id'])+':'+utc.strftime('%Y-%m-%dT%H'),stamp,portfolio['id'])
        # Reports are factual local status, never fabricated AI market reports.
        if local.hour in (8,14,22):
            slot=local.strftime('%Y-%m-%dT%H:%z')
            for user in c.execute('SELECT id FROM users WHERE active=1').fetchall():enqueue(c,'report',user['id'],'report:'+str(user['id'])+':'+slot,stamp)
        c.execute('INSERT INTO worker_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat',(stamp,))

def run_one(connect,fetcher=None,at=None):
    stamp=time.time() if at is None else at;lease=uuid.uuid4().hex
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        # Expired work can be retried after a process crash. Old completions cannot commit.
        c.execute("UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,lease=NULL,lease_until=NULL WHERE status='running' AND lease_until<?",(stamp,))
        row=c.execute("SELECT * FROM jobs WHERE status='queued' AND available<=? ORDER BY available,id LIMIT 1",(stamp,)).fetchone()
        if not row:return False
        job=dict(row)
        c.execute("UPDATE jobs SET status='running',attempts=attempts+1,lease=?,lease_until=? WHERE id=?",(lease,stamp+(600 if job['kind']=='pluto_data' else 120),job['id']))
    try:
        if job['kind']=='pluto_data':
            import portfolio_data
            payload=portfolio_data.read(connect,job['user_id'],job['portfolio_id'])
        elif job['kind']=='news':
            import news
            payload=(fetcher or news.fetch)()
        else:payload=(fetcher or fetch_ecb)() if job['kind']=='ecb' else None
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT 1 FROM jobs WHERE id=? AND lease=? AND status='running'",(job['id'],lease)).fetchone():return True
            if job['kind']=='pluto_data':
                import portfolio_data
                portfolio_data.save(c,job['user_id'],job['portfolio_id'],payload)
                result='Pluto-data hentet'+(' med delvise fejl' if payload['errors'] or payload.get('order_errors') else '')
            elif job['kind']=='ecb':
                # Validate supplied adapters as well as actual network responses.
                if not isinstance(payload,dict) or payload.get('source_url')!=ECB_URL or payload.get('base')!='EUR' or not isinstance(payload.get('rates'),dict):raise ValueError('invalid adapter')
                for code,value in payload['rates'].items():
                    if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('invalid adapter rate')
                normalized=json.dumps({'source_date':payload['source_date'],'rates':payload['rates']},sort_keys=True)
                digest=hashlib.sha256(normalized.encode()).hexdigest()
                before=c.total_changes
                c.execute('INSERT INTO fx_snapshots(source_date,observed,payload,digest) VALUES(?,?,?,?) ON CONFLICT(digest) DO NOTHING',(payload['source_date'],payload['observed'],json.dumps(payload),digest))
                result='Ny ECB-reference gemt' if c.total_changes>before else 'Ingen ændring i ECB-reference'
            elif job['kind']=='news':
                added=0
                for item in payload:
                    before=c.total_changes
                    c.execute('INSERT INTO news_items(title,url,published,summary,observed,digest) VALUES(?,?,?,?,?,?) ON CONFLICT(digest) DO UPDATE SET title=excluded.title,summary=excluded.summary',(item['title'],item['url'],item['published'],item['summary'],item['observed'],item['digest']))
                    added+=c.total_changes-before
                result=f'ECB-nyhedsfeed behandlet: {len(payload)} kildeposter'
            elif job['kind']=='report':
                uid=job['user_id'];snapshot=c.execute('SELECT source_date FROM fx_snapshots ORDER BY source_date DESC,id DESC LIMIT 1').fetchone()
                ideas=c.execute('SELECT count(*) FROM opportunities WHERE user_id=?',(uid,)).fetchone()[0]
                proposals=c.execute('SELECT count(*) FROM proposals WHERE user_id=?',(uid,)).fetchone()[0]
                saved=c.execute('SELECT count(*) FROM portfolio_snapshots WHERE user_id=?',(uid,)).fetchone()[0]
                body=f'Datastatus: {ideas} egne markedsidéer og {proposals} egne handelsforslag. {saved} gemte Pluto-datasæt (se dato og fejlstatus i appen). ECB-reference: '+(snapshot['source_date'] if snapshot else 'ikke hentet')+'. Eksternt aktiekursfeed og AI-analyse er ikke tilsluttet. ECB-nyheder kan læses i appen efter et vellykket feedopslag. Dette er ikke en markedsanalyse.'
                c.execute('INSERT INTO reports(user_id,slot,created,body) VALUES(?,?,?,?) ON CONFLICT(user_id,slot) DO NOTHING',(uid,job['dedupe'],datetime.fromtimestamp(stamp,timezone.utc).isoformat(),body))
                result='Datastatusrapport gemt'
            else:raise ValueError('unknown job')
            c.execute("UPDATE jobs SET status='done',result=?,lease=NULL,lease_until=NULL WHERE id=? AND lease=?",(result,job['id'],lease))
    except Exception:
        # Never persist exception text: network/library errors may include credentials.
        with connect() as c:
            if job['kind']=='pluto_data':
                import portfolio_data
                portfolio_data.mark_failed(c,job['user_id'],job['portfolio_id'],'Automatisk Pluto-læsning fejlede; gemte data kan være forældede')
            c.execute("UPDATE jobs SET status=?,result='Kørslen fejlede; kontrollér datakilde og serveropsætning',available=?,lease=NULL,lease_until=NULL WHERE id=? AND lease=?",('failed' if job['attempts']+1>=3 else 'queued',stamp+900,job['id'],lease))
    return True

def status(connect,user_id):
    with connect() as c:
        snapshot=c.execute('SELECT payload FROM fx_snapshots ORDER BY source_date DESC,id DESC LIMIT 1').fetchone()
        fx=json.loads(snapshot['payload']) if snapshot else None
        if fx:fx['age_days']=(datetime.now(timezone.utc).date()-date.fromisoformat(fx['source_date'])).days
        heartbeat=c.execute('SELECT heartbeat FROM worker_state WHERE id=1').fetchone()
        news=[dict(r) for r in c.execute('SELECT id,title,url,published,summary,observed FROM news_items ORDER BY published DESC,id DESC LIMIT 30')]
        rows=[dict(r) for r in c.execute('SELECT id,kind,status,attempts,result,created FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT 20',(user_id,))]
        reports=[dict(r) for r in c.execute('SELECT created,body FROM reports WHERE user_id=? ORDER BY id DESC LIMIT 20',(user_id,))]
    return {'news':news,'fx':fx,'jobs':rows,'reports':reports,'worker_last_seen':heartbeat['heartbeat'] if heartbeat else None,'worker_recent':bool(heartbeat and heartbeat['heartbeat']>time.time()-180),'ai_status':'Ikke tilsluttet','schedule_timezone':'Europe/Copenhagen'}
