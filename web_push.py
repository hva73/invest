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
    c.execute('CREATE INDEX IF NOT EXISTS push_active_watch_device ON push_jobs(device_id,watch_row_id,status,lease_until)')
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


def enqueue(c,row,kind,event_key,now,severity='info',reason=''):
    urgent=kind=='RISK_REJECTION' and severity=='critical' and reason in ('STOP_BREACHED','EXIT_DEADLINE')
    if (kind not in SIGNAL_EVENTS and kind!='TRAILING_EXIT_WORSENED' and not urgent) or row['is_test']:return
    c.execute('''INSERT OR IGNORE INTO push_jobs(event_key,watch_row_id,device_id,created)
                 SELECT ?,?,id,? FROM push_devices WHERE user_id=?''',(event_key,row['id'],now.timestamp(),row['user_id']))


def _actionable(c,row,now):
    import hotwatch_engine as engine
    if row['status']!='ACTIVE':return None
    view=engine.view(c,row,now);signal=view.get('signal')
    return signal if view.get('display_status')=={'BUY':'KØBSSIGNAL','SELL':'SÆLGSSIGNAL','REDUCE':'EXIT WATCH'}.get(signal) else None


def _message(c,watch,current):
    # The user chose short instrument-specific notifications. The app still
    # checks currentness when opened; a push is never an instruction to trade.
    try:
        ticker=str(json.loads(watch['request']).get('ticker') or '').strip()[:24]
    except (TypeError,ValueError,AttributeError):ticker=''
    ticker=''.join(ch for ch in ticker if ch.isalnum() or ch in '.-_')
    label={'BUY':'købssignal','SELL':'salgssignal','REDUCE':'reduktionssignal'}.get(current)
    title=(ticker+' · ' if ticker else 'ESCAPE · ')+(label or 'signal ændret')
    row=c.execute('SELECT payload FROM hw_calculations WHERE watch_row_id=? ORDER BY id DESC LIMIT 1',(watch['id'],)).fetchone()
    try:codes=set(json.loads(row['payload']).get('reason_codes',[])) if row else set()
    except (ValueError,TypeError,AttributeError):codes=set()
    if current=='SELL' and 'STOP_BREACHED' in codes:body='Stopgrænsen er brudt. Tryk for at se status.'
    elif current=='SELL' and 'EXIT_DEADLINE' in codes:body='Exitfristen er nået. Tryk for at se status.'
    elif current=='SELL' and 'TRAILING_EXIT' in codes:body='Trailing-exit er udløst. Tryk for at se status.'
    elif current=='BUY':body='Tryk for at gennemgå købssignalet.'
    elif current in ('SELL','REDUCE'):body='Tryk for at gennemgå exitsignalet.'
    else:body='Tryk for at se den aktuelle status.'
    return title,body


def _reconcile(c,now):
    # Rotate through previously delivered signals without holding a write lock
    # while calculating currentness. A later dispatch rechecks the result.
    rows=c.execute("SELECT device_id,watch_row_id,event_key,signal FROM push_last WHERE signal IN ('BUY','SELL','REDUCE') ORDER BY updated ASC LIMIT 100").fetchall()
    checked=[]
    for item in rows:
        watch=c.execute('SELECT * FROM hw_sessions WHERE id=?',(item['watch_row_id'],)).fetchone()
        if not watch:continue
        try:effective=_actionable(c,watch,now)
        except Exception:continue
        checked.append((item,effective))
    for item,effective in checked:
        c.execute('UPDATE push_last SET updated=? WHERE device_id=? AND watch_row_id=? AND event_key=?',(now.timestamp(),item['device_id'],item['watch_row_id'],item['event_key']))
        if effective not in ('BUY','SELL','REDUCE') and item['signal']!='SELL':
            c.execute("""INSERT INTO push_jobs(event_key,watch_row_id,device_id,created) VALUES(?,?,?,?)
                ON CONFLICT(event_key,device_id) DO UPDATE SET status='pending',created=excluded.created,attempts=0,next_attempt=0
                WHERE push_jobs.status IN ('expired','failed') AND push_jobs.created<?""",('stale:'+item['event_key'],item['watch_row_id'],item['device_id'],now.timestamp(),now.timestamp()-300))


def _exit_rearmed(c,watch_id,event_key,through=None):
    """Rearm only after verified recovery, changed exposure or closure/re-entry."""
    event=c.execute('SELECT created FROM hw_events WHERE watch_row_id=? AND event_id=?',(watch_id,event_key)).fetchone()
    if not event:return False
    first=c.execute('SELECT payload FROM hw_calculations WHERE watch_row_id=? AND calculated=? ORDER BY id DESC LIMIT 1',(watch_id,event['created'])).fetchone()
    try:prior_result=json.loads(first['payload']) if first else {};prior_key=prior_result.get('exit_context_key')
    except (ValueError,TypeError,AttributeError):prior_result={};prior_key=None
    from hotwatch_contract import stamp
    closed=[]
    def remember_closed(context,observed):
        try:
            as_of=stamp(context['as_of']);seen=stamp(observed)
            if context.get('status')=='verified' and context.get('position')=='none' and as_of>stamp(event['created']) and 0<=(seen-as_of).total_seconds()<=300:closed.append(as_of)
        except (KeyError,ValueError,TypeError,AttributeError):pass
    time_bound=' AND observed<=?' if through else ''
    args=(watch_id,event['created'],through) if through else (watch_id,event['created'])
    for row in c.execute('SELECT observed,payload FROM hw_context_events WHERE watch_row_id=? AND observed>?'+time_bound+' ORDER BY id',args):
        try:remember_closed(json.loads(row['payload']),row['observed'])
        except (ValueError,TypeError):pass
    time_bound=' AND calculated<=?' if through else ''
    rows=c.execute('SELECT calculated,payload FROM hw_calculations WHERE watch_row_id=? AND calculated>?'+time_bound+' ORDER BY id',args).fetchall()
    for row in rows:
        try:
            result=json.loads(row['payload']);codes=set(result.get('reason_codes',[]))
            context=result.get('position_context') or {};remember_closed(context,row['calculated'])
            if result.get('signal')=='WAIT' and codes=={'NO_TRIGGER'} and result.get('new_market_observation') is True and result.get('position_context',{}).get('position')=='held' and result.get('risk_level')=='normal':return True
            current_key=result.get('exit_context_key')
            if result.get('new_market_observation') is True and context.get('status')=='verified' and context.get('position')=='held':
                as_of=stamp(context['as_of']);calculated=stamp(row['calculated'])
                if not 0<=(calculated-as_of).total_seconds()<=300:continue
                if result.get('risk_level')=='normal' and prior_key and current_key and current_key!=prior_key:return True
                if result.get('risk_level')=='normal' and not prior_key:
                    # Old persisted calculations have no key but may retain a
                    # verified position snapshot. Compare only observed amounts;
                    # equality is never treated as proof of uninterrupted ownership.
                    from hotwatch_strategy import exit_context_key
                    old_context=prior_result.get('position_context') or {}
                    try:old_age=(stamp(event['created'])-stamp(old_context['as_of'])).total_seconds()
                    except (KeyError,ValueError,TypeError,AttributeError):old_age=None
                    old_observed=exit_context_key(old_context,None) if old_age is not None and 0<=old_age<=300 else None;new_observed=exit_context_key(context,None)
                    if old_observed and new_observed and old_observed!=new_observed:return True
                valid=result.get('risk_level')=='normal' or result.get('risk_level')=='critical' and result.get('signal') in ('SELL','REDUCE')
                if valid and any(t<as_of for t in closed):return True
        except (KeyError,ValueError,TypeError,AttributeError):continue
    return False


def _exit_evidence(result,strategy_checksum):
    from decimal import Decimal
    risk=result['risk_parameters'];context=result['position_context'];price=result['supporting_metrics']['price']
    if context.get('position')!='held' or context.get('status')!='verified' or context.get('quantity') is None or price is None or not strategy_checksum:return None
    # Account valuation and FX fluctuate with every tick and are entry inputs;
    # they must not turn an unchanged exit into a new alert. Preserve changes
    # to position, execution context, stop/deadline and strategy.
    material={k:context.get(k) for k in ('status','position','quantity','cost_price','tradability','orders','instrument_type')}
    for key in ('quantity','cost_price'):
        if material[key] is not None:
            material[key]=Decimal(str(material[key]))
            if not material[key].is_finite():return None
    if isinstance(material['orders'],list):material['orders']=[{k:v for k,v in order.items() if k!='status_time'} if isinstance(order,dict) else order for order in material['orders']]
    limits={k:risk.get(k) for k in ('stop_price','exit_deadline','exit_allowed')}
    if limits['stop_price'] is not None:
        limits['stop_price']=Decimal(str(limits['stop_price']))
        if not limits['stop_price'].is_finite():return None
    return (strategy_checksum,limits,material,str(price))


def _repeated_critical(c,watch_id,device_id,event_key,reason):
    """Suppress only when both calculations prove the same risk situation."""
    current=c.execute('SELECT created FROM hw_events WHERE watch_row_id=? AND event_id=?',(watch_id,event_key)).fetchone()
    prior=c.execute("""SELECT e.event_id,e.created FROM push_jobs j JOIN hw_events e
        ON e.watch_row_id=j.watch_row_id AND e.event_id=j.event_key
        WHERE j.watch_row_id=? AND j.device_id=? AND j.status='sent'
          AND e.event_type='RISK_REJECTION' AND e.severity='critical'
          AND CASE WHEN json_valid(e.payload) THEN json_extract(e.payload,'$.reason') END=? ORDER BY j.id DESC LIMIT 1""",(watch_id,device_id,reason)).fetchone()
    if not current or not prior or _exit_rearmed(c,watch_id,prior['event_id'],current['created']):return False
    key='stop_price' if reason=='STOP_BREACHED' else 'exit_deadline'
    def evidence(created):
        row=c.execute('SELECT payload,strategy_checksum FROM hw_calculations WHERE watch_row_id=? AND calculated=? ORDER BY id DESC LIMIT 1',(watch_id,created)).fetchone()
        try:
            result=json.loads(row['payload'])
            if result['risk_parameters'].get(key) is None:return None
            return _exit_evidence(result,row['strategy_checksum'])
        except (TypeError,ValueError,KeyError,AttributeError,ArithmeticError):return None
    old,new=evidence(prior['created']),evidence(current['created'])
    return _same_exit_episode(c,watch_id,old,new)


def _same_exit_episode(c,watch_id,old,new):
    """Use the pinned strategy's trailing distance, never a generic cooldown."""
    if old is None or new is None or old[:3]!=new[:3]:return False
    from decimal import Decimal,InvalidOperation
    try:
        before,after=Decimal(old[3]),Decimal(new[3])
        if not before.is_finite() or not after.is_finite() or before<=0 or after<=0:return False
        if before==after:return True
        row=c.execute('SELECT strategy FROM hw_sessions WHERE id=?',(watch_id,)).fetchone()
        strategy=json.loads(row['strategy'])
        from hotwatch_contract import checksum
        if checksum(strategy)!=old[0]:return False
        threshold=Decimal(str(strategy['parameters']['trailing_pct']))
        if not threshold.is_finite() or not Decimal('0')<threshold<=Decimal('100'):return False
        from hotwatch_engine import trailing_notification_worsened
        return not trailing_notification_worsened(after,before,threshold)
    except (TypeError,ValueError,KeyError,AttributeError,InvalidOperation):return False


def _repeated_trailing(c,watch_id,device_id,event_key):
    """A duplicate trailing event is suppressed only with matching verified evidence."""
    current=c.execute('SELECT created FROM hw_events WHERE watch_row_id=? AND event_id=?',(watch_id,event_key)).fetchone()
    prior=c.execute("""SELECT e.event_id,e.created FROM push_jobs j JOIN hw_events e
        ON e.watch_row_id=j.watch_row_id AND e.event_id=j.event_key
        WHERE j.watch_row_id=? AND j.device_id=? AND j.status='sent'
        AND e.event_type='TRAILING_EXIT_WORSENED' ORDER BY j.id DESC LIMIT 1""",(watch_id,device_id)).fetchone()
    if not current or not prior or _exit_rearmed(c,watch_id,prior['event_id'],current['created']):return False
    def evidence(created):
        row=c.execute('SELECT payload,strategy_checksum FROM hw_calculations WHERE watch_row_id=? AND calculated=? ORDER BY id DESC LIMIT 1',(watch_id,created)).fetchone()
        try:
            return _exit_evidence(json.loads(row['payload']),row['strategy_checksum'])
        except (TypeError,ValueError,KeyError,AttributeError,ArithmeticError):return None
    old,new=evidence(prior['created']),evidence(current['created'])
    return _same_exit_episode(c,watch_id,old,new)


def _send(subscription,payload,topic):
    from pywebpush import webpush
    import requests
    class NoRedirectSession(requests.Session):
        def post(self,url,**kwargs):kwargs['allow_redirects']=False;return super().post(url,**kwargs)
    return webpush(subscription_info=subscription,data=json.dumps(payload,ensure_ascii=False),vapid_private_key=str(key_path()),vapid_claims={'sub':public_origin()},ttl=90,timeout=8,headers={'Topic':topic},requests_session=NoRedirectSession())


def notify_release_ready(connect, uid, sender=None):
    """Notify the owner's subscribed devices; the app fetches the candidate.

    The push contains no authorization, release details or external URL. A
    failed push does not affect the admin page or approve a release.
    """
    import release_approval
    with connect() as c:
        owner=c.execute("SELECT id FROM users WHERE id=? AND username='owner' AND role='admin' AND active=1",(uid,)).fetchone()
        devices=c.execute('SELECT payload FROM push_devices WHERE user_id=?',(uid,)).fetchall() if owner else []
    candidate=release_approval.pending(connect,uid) if owner else None
    if not candidate:return {'sent':0,'failed':0}
    sender=sender or _send;sent=failed=0
    for row in devices:
        try:
            sender(unseal(uid,row['payload']),{'title':'ESCAPE · Opdatering klar','body':'Åbn ESCAPE for at gennemgå opdateringen.','kind':'release_approval','tag':'escape-release'},'escape-release')
            sent+=1
        except Exception:
            failed+=1
    # Store aggregate counts only; never persist a subscription or exception.
    # Notification failure must never block the admin approval path.
    try:
        with connect() as c:
            c.execute('INSERT INTO admin_actions(admin_id,target_id,action,created) VALUES(?,?,?,?)',
                      (uid,uid,'release_push:'+candidate['id']+':'+str(sent)+':'+str(failed),str(time.time())))
    except Exception:
        pass
    return {'sent':sent,'failed':failed}


def release_notification_status(connect, uid, candidate_id):
    """Read only aggregate notification counts for the owner's candidate."""
    import re
    if not isinstance(candidate_id,str) or not re.fullmatch(r'[0-9a-f]{32}',candidate_id):
        return None
    try:
        with connect() as c:
            row=c.execute('SELECT action FROM admin_actions WHERE admin_id=? AND target_id=? AND action LIKE ? ORDER BY id DESC LIMIT 1',
                          (uid,uid,'release_push:'+candidate_id+':%')).fetchone()
        if not row:return None
        match=re.fullmatch(r'release_push:'+candidate_id+r':([0-9]{1,2}):([0-9]{1,2})',row[0])
        return {'sent':int(match[1]),'failed':int(match[2])} if match else None
    except Exception:
        return None


def dispatch_one(connect,now=None,sender=None):
    """Lease one event, verify current signal, and send without holding a DB lock."""
    from datetime import datetime,timezone
    import hotwatch_engine as engine
    now=now or datetime.now(timezone.utc);t=now.timestamp();owner=secrets.token_hex(16)
    # Idle polling should not reserve SQLite's only writer. Recheck the job
    # and expiry under the existing transaction before changing anything.
    with connect() as c:
        pending=c.execute("SELECT 1 FROM push_jobs WHERE status='pending' AND created<? UNION ALL SELECT 1 FROM push_jobs j JOIN push_devices d ON d.id=j.device_id JOIN users u ON u.id=d.user_id AND u.active=1 WHERE j.status='pending' AND j.next_attempt<=? AND j.lease_until<? LIMIT 1",(t-300,t,t)).fetchone()
    if not pending:return False
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE push_jobs SET status='expired' WHERE status='pending' AND created<?",(t-300,))
        job=c.execute("SELECT j.*,d.user_id,d.payload,d.buy,d.sell FROM push_jobs j JOIN push_devices d ON d.id=j.device_id JOIN users u ON u.id=d.user_id AND u.active=1 WHERE j.status='pending' AND j.next_attempt<=? AND j.lease_until<? AND NOT EXISTS (SELECT 1 FROM push_jobs active WHERE active.watch_row_id=j.watch_row_id AND active.device_id=j.device_id AND active.id<>j.id AND active.status='pending' AND active.lease_until>=?) ORDER BY j.id LIMIT 1",(t,t,t)).fetchone()
        if not job:return False
        c.execute('UPDATE push_jobs SET lease_owner=?,lease_until=?,attempts=attempts+1 WHERE id=?',(owner,t+30,job['id']))
    with connect() as c:
        watch=c.execute('SELECT * FROM hw_sessions WHERE id=? AND user_id=? AND is_test=0',(job['watch_row_id'],job['user_id'])).fetchone()
        previous=c.execute('SELECT * FROM push_last WHERE device_id=? AND watch_row_id=?',(job['device_id'],job['watch_row_id'])).fetchone()
        if not watch:
            c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
        try:current=_actionable(c,watch,now)
        except Exception:current=None
        e=c.execute('SELECT event_type,severity,payload,created FROM hw_events WHERE watch_row_id=? AND event_id=?',(watch['id'],job['event_key'])).fetchone()
        try:reason=json.loads(e['payload']).get('reason') if e else None
        except (ValueError,TypeError,AttributeError):reason=None
        critical=bool(e and e['event_type']=='RISK_REJECTION' and e['severity']=='critical' and reason in ('STOP_BREACHED','EXIT_DEADLINE'))
        urgent=bool(e and (e['event_type']=='TRAILING_EXIT_WORSENED' or critical))
        if critical and current not in ('SELL','REDUCE'):
            try:
                context=engine.view(c,watch,now).get('latest_context') or {}
                from hotwatch_contract import stamp
                if context.get('status')=='verified' and context.get('position')=='none' and context.get('as_of') and stamp(context['as_of'])>stamp(e['created']) and 0<=(now-stamp(context['as_of'])).total_seconds()<=300:
                    c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
            except (ValueError,TypeError,KeyError,AttributeError):pass
        if (critical and _repeated_critical(c,watch['id'],job['device_id'],job['event_key'],reason) or e and e['event_type']=='TRAILING_EXIT_WORSENED' and _repeated_trailing(c,watch['id'],job['device_id'],job['event_key'])):
            c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
        critical_only=critical and bool(job['sell']) and current not in ('SELL','REDUCE')
        if (current=='BUY' and not job['buy'] or current in ('SELL','REDUCE') and not job['sell']):
            if previous and previous['signal']==current:
                c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
            current=None
        is_action=current in ('BUY','SELL','REDUCE')
        previous_action=previous and previous['signal'] in ('BUY','SELL','REDUCE')
        # An unavailable calculation does not end a continuing exit episode.
        if not is_action and not critical_only and previous and previous['signal']=='SELL':
            c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
        if not is_action and not previous_action and not critical_only:
            c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
        if is_action and previous and previous['signal']==current and not (current=='SELL' and (urgent or e and _exit_rearmed(c,watch['id'],previous['event_key'],e['created']))):
            c.execute("UPDATE push_jobs SET status='skipped',lease_until=0 WHERE id=? AND lease_owner=?",(job['id'],owner));return True
        signal=current if is_action else 'CHANGED'
        title,body=_message(c,watch,current if is_action else None)
        if critical_only:
            title=title.replace('signal ændret','kritisk exitadvarsel')
            body=('Stopgrænsen er registreret brudt. ' if reason=='STOP_BREACHED' else 'Exitfristen er nået. ')+'Tryk for at kontrollere aktuel status.'
        elif urgent and e['event_type']=='TRAILING_EXIT_WORSENED':
            body='Trailing-exit er forværret. Tryk for at se aktuel status.'
        payload={'title':title,'body':body,'watch_id':watch['watch_id'],'tag':'escape-'+hashlib.sha256((str(job['user_id'])+'|'+watch['watch_id']).encode()).hexdigest()[:24]}
        data=bytes(job['payload']);job_id=job['id'];device_id=job['device_id'];watch_id=job['watch_row_id'];event_key=job['event_key'];uid=job['user_id'];attempts=job['attempts']+1
        if critical_only and previous and previous['signal']=='SELL':signal='SELL';event_key=previous['event_key']
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
