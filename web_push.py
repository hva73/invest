"""Privacy-preserving Web Push for current HOT WATCH transitions."""
import base64,hashlib,json,os,secrets,time,tempfile
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import oauth

SIGNAL_EVENTS={'BUY_SIGNAL','SELL_SIGNAL','REDUCE_SIGNAL','WAIT_SIGNAL','NO_DATA','WATCH_PAUSED','WATCH_COMPLETED','WATCH_EXPIRED','DATA_STALE','DATA_ERROR','CANDIDATE_WATCH_EXPIRED','WATCH_RESET','KILL_SWITCH','OPERATOR_KILL_SWITCH','WATCH_ERROR'}

def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS push_devices(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),endpoint_hash TEXT NOT NULL UNIQUE,payload BLOB NOT NULL,buy INTEGER NOT NULL DEFAULT 1,sell INTEGER NOT NULL DEFAULT 1,created REAL NOT NULL,updated REAL NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS push_jobs(id INTEGER PRIMARY KEY,event_key TEXT NOT NULL,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),device_id INTEGER NOT NULL REFERENCES push_devices(id) ON DELETE CASCADE,created REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,lease_until REAL NOT NULL DEFAULT 0,lease_owner TEXT,status TEXT NOT NULL DEFAULT 'pending',UNIQUE(event_key,device_id))''')
    c.execute('CREATE INDEX IF NOT EXISTS push_due ON push_jobs(status,next_attempt,lease_until,id)')
    c.execute('''CREATE TABLE IF NOT EXISTS push_last(device_id INTEGER NOT NULL REFERENCES push_devices(id) ON DELETE CASCADE,watch_row_id INTEGER NOT NULL REFERENCES hw_sessions(id),signal TEXT NOT NULL,event_key TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(device_id,watch_row_id))''')


def key_path():
    from app import DB
    return Path(os.environ.get('ESCAPE_PUSH_KEY_FILE',str(Path(DB).parent/'keys/push_vapid.pem')))


def setup_key():
    path=key_path();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not path.exists():
        key=ec.generate_private_key(ec.SECP256R1());raw=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        fd,temp=tempfile.mkstemp(prefix='.push-key-',dir=path.parent)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            try:os.link(temp,path,follow_symlinks=False)
            except FileExistsError:pass
        finally:Path(temp).unlink(missing_ok=True)
    return public_key()


def public_key():
    path=key_path()
    if path.is_symlink() or path.stat().st_mode&0o077:raise ValueError('Notifikationsnøglen skal være privat (0600).')
    key=serialization.load_pem_private_key(path.read_bytes(),password=None)
    if not isinstance(key,ec.EllipticCurvePrivateKey) or not isinstance(key.curve,ec.SECP256R1):raise ValueError('Notifikationsnøglen er ugyldig.')
    raw=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def public_origin():
    value=os.environ.get('ESCAPE_PUBLIC_URL','').rstrip('/');url=urlsplit(value)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:raise ValueError('Appens HTTPS-adresse er ikke konfigureret.')
    return value


def config(connect,uid):
    import importlib.util
    try:
        ready=bool(importlib.util.find_spec('pywebpush'));origin=public_origin();key=public_key();oauth.cipher()
        if not ready:raise ValueError('Web-push-pakken er ikke installeret på serveren.')
        error=None
    except (ValueError,OSError):key=None;ready=False;error='Notifikationer er ikke klargjort på serveren. Kontrollér installation og HTTPS-adresse.'
    with connect() as c:count=c.execute('SELECT count(*) FROM push_devices WHERE user_id=?',(uid,)).fetchone()[0]
    return {'available':ready,'public_key':key,'device_count':count,'message':error}


def seal(uid,data):
    nonce=secrets.token_bytes(12);aad=('escape-push:'+str(uid)).encode()
    return nonce+oauth.cipher().encrypt(nonce,json.dumps(data).encode(),aad)


def unseal(uid,payload):
    return json.loads(oauth.cipher().decrypt(payload[:12],payload[12:],('escape-push:'+str(uid)).encode()))


def endpoint_hash(endpoint):return hashlib.sha256(endpoint.encode()).hexdigest()

def validate_subscription(data):
    if not isinstance(data,dict) or not isinstance(data.get('endpoint'),str) or len(data['endpoint'])>2048:raise ValueError('Ugyldig notifikationsadresse.')
    endpoint=data['endpoint'];url=urlsplit(endpoint);host=(url.hostname or '').lower()
    permitted=host=='fcm.googleapis.com' or host=='updates.push.services.mozilla.com' or host.endswith('.push.apple.com')
    if url.scheme!='https' or not permitted or url.username or url.password or url.port not in (None,443) or url.fragment:raise ValueError('Notifikationstjenesten understøttes ikke.')
    keys=data.get('keys');keys=keys if isinstance(keys,dict) else {}
    def decode(name,length):
        v=keys.get(name)
        if not isinstance(v,str) or len(v)>128:raise ValueError('Ugyldige notifikationsnøgler.')
        try:raw=base64.b64decode(v+'='*((-len(v))%4),altchars=b'-_',validate=True)
        except Exception:raise ValueError('Ugyldige notifikationsnøgler.')
        if len(raw)!=length:raise ValueError('Ugyldige notifikationsnøgler.')
        return raw
    public=decode('p256dh',65);decode('auth',16)
    try:ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),public)
    except ValueError:raise ValueError('Ugyldige notifikationsnøgler.')
    return {'endpoint':endpoint,'keys':{'p256dh':keys['p256dh'],'auth':keys['auth']}}


def subscribe(connect,uid,data):
    sub=validate_subscription(data.get('subscription'));buy=data.get('buy');sell=data.get('sell')
    if type(buy) is not bool or type(sell) is not bool or not (buy or sell):raise ValueError('Vælg mindst én type notifikation.')
    public_origin();public_key();encrypted=seal(uid,sub);now=time.time();digest=endpoint_hash(sub['endpoint'])
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT user_id FROM push_devices WHERE endpoint_hash=?',(digest,)).fetchone()
        if row and row['user_id']!=uid:raise ValueError('Denne enhed er allerede tilmeldt en anden bruger.')
        if not row and c.execute('SELECT count(*) FROM push_devices WHERE user_id=?',(uid,)).fetchone()[0]>=20:raise ValueError('Maksimalt 20 enheder kan modtage notifikationer.')
        c.execute('''INSERT INTO push_devices(user_id,endpoint_hash,payload,buy,sell,created,updated) VALUES(?,?,?,?,?,?,?) ON CONFLICT(endpoint_hash) DO UPDATE SET payload=excluded.payload,buy=excluded.buy,sell=excluded.sell,updated=excluded.updated''',(uid,digest,encrypted,int(buy),int(sell),now,now))
    return {'ok':True}


def unsubscribe(connect,uid,endpoint):
    if not isinstance(endpoint,str) or len(endpoint)>2048:raise ValueError('Ugyldig notifikationsadresse.')
    with connect() as c:c.execute('DELETE FROM push_devices WHERE user_id=? AND endpoint_hash=?',(uid,endpoint_hash(endpoint)))
    return {'ok':True}


def device_preferences(connect,uid,endpoint):
    if not isinstance(endpoint,str) or len(endpoint)>2048:raise ValueError('Ugyldig notifikationsadresse.')
    with connect() as c:row=c.execute('SELECT buy,sell FROM push_devices WHERE user_id=? AND endpoint_hash=?',(uid,endpoint_hash(endpoint))).fetchone()
    return {'subscribed':bool(row),'buy':bool(row['buy']) if row else False,'sell':bool(row['sell']) if row else False}


def enqueue(c,row,kind,event_key,now):
    if kind not in SIGNAL_EVENTS or row['is_test']:return
    c.execute('''INSERT OR IGNORE INTO push_jobs(event_key,watch_row_id,device_id,created)
                 SELECT ?,?,id,? FROM push_devices WHERE user_id=?''',(event_key,row['id'],now.timestamp(),row['user_id']))


def _actionable(c,row,now):
    import hotwatch_engine as engine
    if row['status']!='ACTIVE':return None
    view=engine.view(c,row,now);signal=view.get('signal')
    return signal if view.get('display_status')=={'BUY':'KØBSSIGNAL','SELL':'SÆLGSSIGNAL','REDUCE':'EXIT WATCH'}.get(signal) else None


def _reconcile(c,now):
    # Rotate through previously delivered signals without holding a write lock
    # while calculating currentness. A later dispatch rechecks the result.
    rows=c.execute("SELECT device_id,watch_row_id,event_key FROM push_last WHERE signal IN ('BUY','SELL','REDUCE') ORDER BY updated ASC LIMIT 100").fetchall()
    checked=[]
    for item in rows:
        watch=c.execute('SELECT * FROM hw_sessions WHERE id=?',(item['watch_row_id'],)).fetchone()
        if not watch:continue
        try:effective=_actionable(c,watch,now)
        except Exception:continue
        checked.append((item,effective))
    for item,effective in checked:
        c.execute('UPDATE push_last SET updated=? WHERE device_id=? AND watch_row_id=? AND event_key=?',(now.timestamp(),item['device_id'],item['watch_row_id'],item['event_key']))
        if effective not in ('BUY','SELL','REDUCE'):
            c.execute("""INSERT INTO push_jobs(event_key,watch_row_id,device_id,created) VALUES(?,?,?,?)
                ON CONFLICT(event_key,device_id) DO UPDATE SET status='pending',created=excluded.created,attempts=0,next_attempt=0
                WHERE push_jobs.status IN ('expired','failed') AND push_jobs.created<?""",('stale:'+item['event_key'],item['watch_row_id'],item['device_id'],now.timestamp(),now.timestamp()-300))


def _send(subscription,payload,topic):
    from pywebpush import webpush
    import requests
    class NoRedirectSession(requests.Session):
        def post(self,url,**kwargs):kwargs['allow_redirects']=False;return super().post(url,**kwargs)
    return webpush(subscription_info=subscription,data=json.dumps(payload,ensure_ascii=False),vapid_private_key=str(key_path()),vapid_claims={'sub':public_origin()},ttl=90,timeout=8,headers={'Topic':topic},requests_session=NoRedirectSession())


def dispatch_one(connect,now=None,sender=None):
    """Lease one event, verify current signal, and send without holding a DB lock."""
    from datetime import datetime,timezone
    import hotwatch_engine as engine
    now=now or datetime.now(timezone.utc);t=now.timestamp();owner=secrets.token_hex(16)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE push_jobs SET status='expired' WHERE status='pending' AND created<?",(t-300,))
        job=c.execute("SELECT j.*,d.user_id,d.payload,d.buy,d.sell FROM push_jobs j JOIN push_devices d ON d.id=j.device_id JOIN users u ON u.id=d.user_id AND u.active=1 WHERE j.status='pending' AND j.next_attempt<=? AND j.lease_until<? ORDER BY j.id LIMIT 1",(t,t)).fetchone()
        if not job:return False
        c.execute('UPDATE push_jobs SET lease_owner=?,lease_until=?,attempts=attempts+1 WHERE id=?',(owner,t+30,job['id']))
    with connect() as c:
        watch=c.execute('SELECT * FROM hw_sessions WHERE id=? AND user_id=? AND is_test=0',(job['watch_row_id'],job['user_id'])).fetchone()
        previous=c.execute('SELECT * FROM push_last WHERE device_id=? AND watch_row_id=?',(job['device_id'],job['watch_row_id'])).fetchone()
        if not watch:
            c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
        try:current=_actionable(c,watch,now)
        except Exception:current=None
        if (current=='BUY' and not job['buy'] or current in ('SELL','REDUCE') and not job['sell']):
            if previous and previous['signal']==current:
                c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
            current=None
        is_action=current in ('BUY','SELL','REDUCE')
        previous_action=previous and previous['signal'] in ('BUY','SELL','REDUCE')
        if not is_action and not previous_action:
            c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
        if is_action and previous and previous['signal']==current:
            c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
        signal=current if is_action else 'CHANGED'
        # Generic lock-screen text avoids exposing holdings or account details.
        payload={'title':('ESCAPE · købssignal' if current=='BUY' else 'ESCAPE · salgssignal') if is_action else 'ESCAPE · signal ændret','body':'Åbn ESCAPE for at se den aktuelle status.','watch_id':watch['watch_id'],'tag':'escape-'+hashlib.sha256((str(job['user_id'])+'|'+watch['watch_id']).encode()).hexdigest()[:24]}
        data=bytes(job['payload']);job_id=job['id'];device_id=job['device_id'];watch_id=job['watch_row_id'];event_key=job['event_key'];uid=job['user_id'];attempts=job['attempts']+1
    try:
        sub=unseal(uid,data);validate_subscription(sub);(sender or _send)(sub,payload,payload['tag'])
    except Exception as error:
        response=getattr(error,'response',None);status=getattr(response,'status_code',None)
        with connect() as c:
            if status in (404,410):c.execute('DELETE FROM push_devices WHERE id=? AND user_id=?',(device_id,uid))
            else:c.execute("UPDATE push_jobs SET status=?,lease_owner=NULL,lease_until=0,next_attempt=? WHERE id=? AND lease_owner=?",('failed' if attempts>=4 else 'pending',t+min(60,2**attempts),job_id,owner))
        return True
    with connect() as c:
        changed=c.execute("UPDATE push_jobs SET status='sent',lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?",(job_id,owner)).rowcount
        if changed:c.execute('''INSERT INTO push_last VALUES(?,?,?,?,?) ON CONFLICT(device_id,watch_row_id) DO UPDATE SET signal=excluded.signal,event_key=excluded.event_key,updated=excluded.updated''',(device_id,watch_id,signal,event_key,t))
    return True


def send_test(connect,uid,endpoint,sender=None):
    if not isinstance(endpoint,str) or len(endpoint)>2048:raise ValueError('Ugyldig notifikationsadresse.')
    with connect() as c:row=c.execute('SELECT payload FROM push_devices WHERE user_id=? AND endpoint_hash=?',(uid,endpoint_hash(endpoint))).fetchone()
    if not row:raise ValueError('Denne enhed er ikke tilmeldt notifikationer.')
    sub=unseal(uid,bytes(row['payload']));validate_subscription(sub)
    (sender or _send)(sub,{'title':'ESCAPE · test','body':'Notifikationer er slået til på denne enhed.','tag':'escape-test'},'escape-test')
    return {'ok':True}


def reconcile_stale(connect,now=None):
    from datetime import datetime,timezone
    now=now or datetime.now(timezone.utc)
    with connect() as c:
        _reconcile(c,now)
        c.execute("DELETE FROM push_jobs WHERE status IN ('sent','skipped','expired','failed') AND created<?",(now.timestamp()-7*86400,))
