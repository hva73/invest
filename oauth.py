"""OAuth authorization-code + PKCE. Fixed provider trust; no trading operations."""
import base64,hashlib,json,os,secrets,time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode,urlsplit
import urllib.request
from pluto import MCP_URL,NoRedirect,discover

class SetupRequired(ValueError):pass

def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS oauth_flows(state_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),session_hash TEXT NOT NULL,expires REAL NOT NULL,payload BLOB NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS oauth_tokens(user_id INTEGER PRIMARY KEY REFERENCES users(id),payload BLOB NOT NULL,expires REAL NOT NULL,connected REAL NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS oauth_clients(issuer TEXT PRIMARY KEY,client_id TEXT NOT NULL,redirect_uri TEXT NOT NULL)')

def cipher():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:raise SetupRequired('Installér requirements.txt med Run Pip Install først')
    from app import DB
    path=Path(os.environ.get('ESCAPE_TOKEN_KEY_FILE',str(Path(DB).parent/'keys/token.key')))
    try:
        if path.stat().st_mode & 0o077:raise SetupRequired('Token-nøglen skal være privat (0600)')
        key=path.read_bytes()
        if len(key)!=32:raise SetupRequired('Token-nøglen er ugyldig')
    except FileNotFoundError:raise SetupRequired('Kør setup_runtime.py for at klargøre privat tokenkryptering')
    return AESGCM(key)

def seal(user_id,data):
    nonce=secrets.token_bytes(12)
    return nonce+cipher().encrypt(nonce,json.dumps(data).encode(),f'pluto:{user_id}'.encode())

def unseal(user_id,payload):
    return json.loads(cipher().decrypt(payload[:12],payload[12:],f'pluto:{user_id}'.encode()))

def setup_key():
    from app import DB
    path=Path(os.environ.get('ESCAPE_TOKEN_KEY_FILE',str(Path(DB).parent/'keys/token.key')))
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.exists():
        cipher();return
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as file:file.write(secrets.token_bytes(32))
    cipher()

def settings():
    public=os.environ.get('ESCAPE_PUBLIC_URL','').rstrip('/')
    url=urlsplit(public)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
        raise SetupRequired('ESCAPE_PUBLIC_URL skal være appens præcise HTTPS-adresse uden sti')
    scopes=os.environ.get('PLUTO_READ_SCOPES','').split()
    if not scopes:raise SetupRequired('Plutos dokumenterede læsescopes skal først konfigureres som PLUTO_READ_SCOPES')
    if any(any(word in scope.lower() for word in ['trade','write','order','execute']) for scope in scopes):
        raise SetupRequired('Handels- eller skrivescopes accepteres ikke')
    return public+'/api/pluto/callback',scopes

def post_json(url,data,form=False):
    encoded=urlencode(data).encode() if form else json.dumps(data).encode()
    request=urllib.request.Request(url,data=encoded,headers={'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json','Accept':'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=10) as response:
        raw=response.read(65537)
        if len(raw)>65536:raise ValueError('oversized response')
        parsed=json.loads(raw)
        if not isinstance(parsed,dict):raise ValueError('invalid response')
        return parsed

def start(connect,session,metadata=None,post=None,trade=False):
    callback,scopes=settings();cipher()
    if trade is True:scopes=list(dict.fromkeys([*scopes,'mcp:trade']))
    metadata=metadata or discover();server=metadata.get('oauth',{})
    if not metadata.get('discovery_valid') or not server.get('verified'):
        raise SetupRequired('Plutos autorisationsmetadata skal verificeres først')
    if 'S256' not in server.get('code_challenge_methods_supported',[]):
        raise SetupRequired('Pluto skal understøtte PKCE S256')
    if not set(scopes).issubset(server.get('scopes_supported',[])):
        raise SetupRequired('Den ønskede adgang findes ikke i Plutos verificerede metadata')
    if not all(server.get(k) for k in ['authorization_endpoint','token_endpoint']):
        raise SetupRequired('Plutos login- eller token-endpoint mangler')
    if 'none' not in server.get('token_endpoint_auth_methods_supported',['client_secret_basic']):
        raise SetupRequired('Denne version kræver en offentlig PKCE-klient uden client-secret; Pluto tilbyder ikke dette i metadata')
    client_id=os.environ.get('PLUTO_CLIENT_ID','')
    if not client_id:
        # Registration can involve a slow provider request. Serialize it across
        # app processes without holding SQLite's global writer lock over HTTP.
        with token_lock(0):
            with connect() as c:
                client=c.execute('SELECT * FROM oauth_clients WHERE issuer=?',(server['issuer'],)).fetchone()
            if client:
                if client['redirect_uri']!=callback:raise SetupRequired('Appadressen er ændret; klientregistreringen skal gennemgås')
                client_id=client['client_id']
            else:
                if not server.get('registration_endpoint'):raise SetupRequired('Pluto kræver registreret klient; PLUTO_CLIENT_ID mangler')
                # Register only when the provider explicitly advertises dynamic registration.
                registration=(post or post_json)(server['registration_endpoint'],{'client_name':'ESCAPE Trading Command Center','redirect_uris':[callback],'grant_types':['authorization_code']+(['refresh_token'] if 'refresh_token' in server.get('grant_types_supported',[]) else []),'response_types':['code'],'token_endpoint_auth_method':'none'})
                client_id=registration.get('client_id')
                if not isinstance(client_id,str) or not client_id or registration.get('client_secret') or registration.get('token_endpoint_auth_method','none')!='none':
                    raise SetupRequired('Registreringen kræver en anden klienttype; ingen login er startet')
                with connect() as c:
                    c.execute('INSERT INTO oauth_clients VALUES(?,?,?)',(server['issuer'],client_id,callback))
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    payload={'verifier':verifier,'client_id':client_id,'callback':callback,'scopes':scopes,'server':server}
    with connect() as c:
        c.execute('DELETE FROM oauth_flows WHERE expires<?',(time.time(),))
        c.execute('INSERT INTO oauth_flows VALUES(?,?,?,?,?)',(hashlib.sha256(state.encode()).hexdigest(),session['user_id'],session['token_hash'],time.time()+600,seal(session['user_id'],payload)))
    return {'authorization_url':server['authorization_endpoint']+'?'+urlencode({'response_type':'code','client_id':client_id,'redirect_uri':callback,'scope':' '.join(scopes),'state':state,'code_challenge':challenge,'code_challenge_method':'S256','resource':MCP_URL})}

def finish(connect,session,state,code,error=None,post=None):
    if not state or len(state)>200 or (code and len(code)>8192):raise ValueError('invalid callback')
    hashed=hashlib.sha256(state.encode()).hexdigest()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM oauth_flows WHERE state_hash=? AND user_id=? AND session_hash=? AND expires>?',(hashed,session['user_id'],session['token_hash'],time.time())).fetchone()
        if not row:raise ValueError('expired or mismatched callback')
        c.execute('DELETE FROM oauth_flows WHERE state_hash=?',(hashed,))
    payload=unseal(session['user_id'],row['payload'])
    if error or not code:raise ValueError('authorization declined')
    token=(post or post_json)(payload['server']['token_endpoint'],{'grant_type':'authorization_code','code':code,'redirect_uri':payload['callback'],'client_id':payload['client_id'],'code_verifier':payload['verifier'],'resource':MCP_URL},form=True)
    if not isinstance(token.get('access_token'),str) or not token['access_token'] or token.get('token_type','').lower()!='bearer':raise ValueError('invalid token')
    granted=token.get('scope',' '.join(payload['scopes'])).split()
    if set(granted)!=set(payload['scopes']):raise ValueError('scope mismatch')
    expires=float(token.get('expires_in',0))
    if not 0<expires<=31536000:raise ValueError('expiry required')
    # Tokens never go to the browser or a generic MCP command endpoint.
    stored={'token':token,'server':payload['server'],'client_id':payload['client_id'],'scopes':payload['scopes']}
    with token_lock(session['user_id']),connect() as c:
        c.execute('INSERT INTO oauth_tokens VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload,expires=excluded.expires,connected=excluded.connected',(session['user_id'],seal(session['user_id'],stored),time.time()+expires,time.time()))

@contextmanager
def token_lock(user_id):
    """Per-account process lock; provider requests never hold a database write lock."""
    import fcntl
    from app import DB
    folder=Path(DB).parent/'oauth-locks';folder.mkdir(mode=0o700,exist_ok=True)
    fd=os.open(folder/('pluto-'+str(int(user_id))+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    deadline=time.monotonic()+25
    try:
        while True:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise SetupRequired('Pluto-forbindelsen opdateres allerede. Prøv igen om et øjeblik.')
                time.sleep(.05)
        yield
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)

def access_token(connect,user_id,post=None):
    """Renew on a read, serializing refresh-token rotation across Passenger workers."""
    with connect() as c:row=c.execute('SELECT * FROM oauth_tokens WHERE user_id=?',(user_id,)).fetchone()
    if not row:raise SetupRequired('Log ind hos Pluto før dataopslag')
    if row['expires']>time.time()+60:return unseal(user_id,row['payload'])['token']['access_token']
    result=None;message=None
    with token_lock(user_id):
        with connect() as c:row=c.execute('SELECT * FROM oauth_tokens WHERE user_id=?',(user_id,)).fetchone()
        if not row:raise SetupRequired('Log ind hos Pluto før dataopslag')
        stored=unseal(user_id,row['payload']);token=stored['token'];now=time.time()
        result=token['access_token'] if row['expires']>now else None
        if row['expires']>now+60:return result
        refresh=token.get('refresh_token');server=stored.get('server',{})
        if not refresh or not server.get('verified') or not server.get('token_endpoint'):
            if result:return result
            raise SetupRequired('Pluto-adgangen er udløbet. Log ind hos Pluto igen.')
        if stored.get('refresh_retry_after',0)>now:
            if result:return result
            raise SetupRequired('Pluto-adgangen kunne ikke fornyes. Prøv igen om et minut eller log ind igen.')
        try:
            renewed=(post or post_json)(server['token_endpoint'],{'grant_type':'refresh_token','refresh_token':refresh,'client_id':stored['client_id'],'resource':MCP_URL},form=True)
            if not isinstance(renewed.get('access_token'),str) or not renewed['access_token'] or renewed.get('token_type','').lower()!='bearer':raise ValueError('invalid token')
            expiry=float(renewed.get('expires_in',0))
            if not 0<expiry<=31536000:raise ValueError('invalid expiry')
            if set(renewed.get('scope',' '.join(stored['scopes'])).split())!=set(stored['scopes']):raise ValueError('scope mismatch')
            if 'refresh_token' in renewed and (not isinstance(renewed['refresh_token'],str) or not renewed['refresh_token']):raise ValueError('invalid refresh')
            stored['token']={**renewed,'refresh_token':renewed.get('refresh_token',refresh)}
            stored.pop('refresh_retry_after',None);stored.pop('refresh_error',None)
            with connect() as c:c.execute('UPDATE oauth_tokens SET payload=?,expires=? WHERE user_id=?',(seal(user_id,stored),time.time()+expiry,user_id))
            result=renewed['access_token']
        except Exception as error:
            import urllib.error
            revoked=False
            if isinstance(error,urllib.error.HTTPError) and error.code in (400,401):
                try:revoked=json.loads(error.read(65536)).get('error') in ('invalid_grant','invalid_client')
                except (ValueError,AttributeError):pass
            stored['refresh_error']='reconnect' if revoked else 'temporary'
            stored['refresh_retry_after']=time.time()+60
            if revoked:
                stored['token'].pop('refresh_token',None);result=None
            with connect() as c:
                if revoked:c.execute('UPDATE oauth_tokens SET expires=0 WHERE user_id=?',(user_id,))
                c.execute('UPDATE oauth_tokens SET payload=? WHERE user_id=?',(seal(user_id,stored),user_id))
            message='Pluto kræver nyt login. Log ind hos Pluto igen.' if revoked else 'Pluto-adgangen kunne ikke fornyes. Prøv igen om et minut eller log ind igen.'
    if result:return result
    raise SetupRequired(message)

def revoke(connect,user_id,post=None):
    # Share the rotation lock: disconnect cannot revoke an already rotated token
    # and then leave its replacement active at the provider.
    with token_lock(user_id):
        with connect() as c:row=c.execute('SELECT payload FROM oauth_tokens WHERE user_id=?',(user_id,)).fetchone()
        if not row:return
        payload=unseal(user_id,row['payload']);endpoint=payload['server'].get('revocation_endpoint')
        if not endpoint:raise SetupRequired('Pluto annoncerer ikke automatisk tilbagekaldelse. Tilbagekald adgangen hos Pluto før lokal sletning.')
        send=post or revoke_http
        for key in ['refresh_token','access_token']:
            if payload['token'].get(key):send(endpoint,{'token':payload['token'][key],'token_type_hint':key,'client_id':payload['client_id']})
        with connect() as c:c.execute('DELETE FROM oauth_tokens WHERE user_id=?',(user_id,))

def revoke_http(url,data):
    request=urllib.request.Request(url,data=urlencode(data).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=10) as response:response.read(1)
