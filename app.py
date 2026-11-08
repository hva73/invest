import os, sqlite3, json, secrets, hashlib, hmac, time, math
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,parse_qs
import oauth
from report_validation import ReportValidationError,unique_object
ROOT=Path(__file__).parent
DB=os.environ.get('ESCAPE_DB',str(ROOT/'var/escape.db'))
SESSIONS={}
def connect():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def init():
    # Migrate under a write lock so Passenger workers cannot race the upgrade.
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, salt TEXT, hash TEXT)")
        for name, definition in [('username','TEXT'),('role',"TEXT NOT NULL DEFAULT 'member'"),('active','INTEGER NOT NULL DEFAULT 1')]:
            if name not in {r['name'] for r in c.execute('PRAGMA table_info(users)')}:
                c.execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
        legacy=c.execute('SELECT id FROM users WHERE username IS NULL').fetchall()
        if legacy:
            if len(legacy)!=1 or c.execute('SELECT count(*) FROM users').fetchone()[0]!=1:
                raise RuntimeError('Ambiguous legacy ownership; migration requires manual review')
            c.execute("UPDATE users SET username='owner',role='admin' WHERE id=?",(legacy[0]['id'],))
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_username ON users(username COLLATE NOCASE)')
        schemas={
            'proposals': "id INTEGER PRIMARY KEY, portfolio TEXT, ticker TEXT, quantity REAL, price REAL, stop REAL, target REAL, costs REAL, fx REAL, status TEXT DEFAULT 'Forslag', created TEXT",
            'journal': 'id INTEGER PRIMARY KEY, proposal_id INTEGER, event TEXT, created TEXT',
            'opportunities': "id INTEGER PRIMARY KEY, company TEXT NOT NULL, ticker TEXT NOT NULL, market TEXT NOT NULL, asset TEXT NOT NULL, headline TEXT NOT NULL, source_url TEXT NOT NULL, published TEXT NOT NULL, classification TEXT NOT NULL, catalyst TEXT NOT NULL, risk TEXT NOT NULL, next_action TEXT NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OVERVÅG'"
        }
        for table, definition in schemas.items():
            c.execute(f'CREATE TABLE IF NOT EXISTS {table}({definition})')
            if 'user_id' not in {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}:
                c.execute(f'ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id)')
            if c.execute(f'SELECT 1 FROM {table} WHERE user_id IS NULL').fetchone():
                owners=c.execute('SELECT id FROM users').fetchall()
                if len(owners)!=1: raise RuntimeError('Cannot safely assign legacy data')
                c.execute(f'UPDATE {table} SET user_id=? WHERE user_id IS NULL',(owners[0]['id'],))
            c.execute(f'CREATE INDEX IF NOT EXISTS {table}_owner ON {table}(user_id)')
            c.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_require_owner BEFORE INSERT ON {table} WHEN NEW.user_id IS NULL BEGIN SELECT RAISE(ABORT, 'Owner required'); END")
        c.execute('CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS login_failures(address TEXT NOT NULL, created REAL NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS invitations(token_hash TEXT PRIMARY KEY, created_by INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0)')
        c.execute("CREATE TABLE IF NOT EXISTS connections(user_id INTEGER PRIMARY KEY REFERENCES users(id), provider TEXT NOT NULL DEFAULT 'pluto', status TEXT NOT NULL, requested TEXT NOT NULL)")
        c.execute('CREATE TABLE IF NOT EXISTS connection_checks(user_id INTEGER PRIMARY KEY REFERENCES users(id), checked REAL NOT NULL)')
        import user_profile
        user_profile.init(c)
        c.execute('CREATE TABLE IF NOT EXISTS admin_actions(id INTEGER PRIMARY KEY, admin_id INTEGER NOT NULL REFERENCES users(id), target_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, created TEXT NOT NULL)')
        import report_ingest
        report_ingest.init(c)
        import hotwatch_engine
        hotwatch_engine.init(c)
        import strategy_center
        strategy_center.init(c)
        import mcp_reports
        mcp_reports.init(c)
        import jobs
        jobs.init(c)
        oauth.init(c)
        import portfolios
        portfolios.init(c)
        import portfolio_data
        portfolio_data.init(c)
        import sector_intelligence
        sector_intelligence.init(c)
        import trade_service
        trade_service.init(c)
        import market_data
        market_data.init(c)
        c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def username(value):
    import re
    value=str(value).strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}',value):
        raise ValueError('Brugernavnet skal have 3–40 tegn: a–z, 0–9, punktum, bindestreg eller understregning')
    return value

def register(data):
    if any(not isinstance(data.get(key),str) for key in ['username','password','invitation']):raise ValueError('Udfyld invitationskode, brugernavn og adgangskode')
    name=username(data['username']);password=data['password']
    invitation=''.join(data['invitation'].split())
    if not 20<=len(invitation)<=200:raise ValueError('Invitationskoden er ugyldig. Kopiér hele koden fra invitationen.')
    if not 14<=len(password)<=1024: raise ValueError('Adgangskoden skal have 14–1024 tegn')
    salt=secrets.token_hex(16);digest=password_hash(password,salt)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        invite=c.execute('SELECT * FROM invitations WHERE token_hash=? AND used=0 AND expires>?',(token_hash(invitation),time.time())).fetchone()
        if not invite: raise ValueError('Invitationen er ugyldig, udløbet eller allerede brugt. Bed om en ny invitation.')
        if c.execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE',(name,)).fetchone():
            raise ValueError('Brugernavnet er allerede i brug')
        c.execute("INSERT INTO users(username,salt,hash,role) VALUES(?,?,?,'member')",(name,salt,digest))
        c.execute('UPDATE invitations SET used=1 WHERE token_hash=?',(invite['token_hash'],))
    return name

def connection_state(user_id):
    with connect() as c:
        row=c.execute('SELECT status,requested FROM connections WHERE user_id=?',(user_id,)).fetchone()
        token=c.execute('SELECT expires,payload FROM oauth_tokens WHERE user_id=?',(user_id,)).fetchone()
    connected=bool(token and token['expires']>time.time());renewable=False;refresh_error=None;trade_access=False
    if token:
        try:
            stored=oauth.unseal(user_id,token['payload'])
            trade_access='mcp:trade' in stored.get('scopes',[])
            renewable=bool(stored['token'].get('refresh_token') and stored.get('server',{}).get('verified'))
            refresh_error=stored.get('refresh_error')
        except Exception:pass
    reason='Ingen Pluto-login er gennemført.'
    can_connect=True
    try:oauth.settings();oauth.cipher()
    except oauth.SetupRequired as error:reason=str(error);can_connect=False
    if connected:reason='Pluto-adgangen er gyldig.'+(' Fornyes automatisk ved dataopslag, når Pluto tillader det.' if renewable else ' Pluto har ikke givet en anvendelig fornyelsesnøgle; nyt login kræves ved udløb.')
    elif token:reason='Pluto-adgangen er udløbet. Log ind hos Pluto igen.'
    if not connected and renewable:reason='Pluto-adgangen skal fornyes. Vi forsøger automatisk ved næste dataopslag.'
    if refresh_error=='temporary':reason='Seneste fornyelse fejlede midlertidigt. Prøv et dataopslag igen om et minut.'
    elif refresh_error=='reconnect':reason='Pluto kræver et nyt login.'
    return {'provider':'Pluto Markets','connected':connected,'expires_at':token['expires'] if token else None,'can_renew':renewable,'status':'Login godkendt' if connected else ('Fornyelse afventer' if renewable else ('Login udløbet' if token else (row['status'] if row else 'Ikke tilsluttet'))),'requested':row['requested'] if row else None,'can_connect':can_connect,'reason':reason,'requested_access':'Handelsforslag og læsning' if trade_access else 'Kun læsning','trade_access':trade_access,'has_tokens':bool(token)}

def save_opportunity(data,user_id):
    fields=['company','ticker','market','asset','headline','source_url','published','classification','catalyst','risk','next_action']
    values={k:str(data[k]).strip() for k in fields}
    if len(values['ticker'])>24: raise ValueError('Symbol og børs må højst fylde 24 tegn')
    if any(not v or len(v)>2000 for v in values.values()): raise ValueError('Udfyld alle felter')
    url=urlsplit(values['source_url'])
    if url.scheme!='https' or not url.hostname or url.username or url.password: raise ValueError('Kilden skal være en HTTPS-adresse uden credentials')
    published=datetime.fromisoformat(values['published'])
    if published.tzinfo is None or published>datetime.now(published.tzinfo): raise ValueError('Ugyldigt kildetidspunkt')
    if values['classification'] not in ['Bekræftet information','Troværdigt rygte','Spekulation']: raise ValueError('Ukendt klassifikation')
    if values['market'] not in ['USA','Canada','Danmark','Norden','Europa','Asien']: raise ValueError('Ukendt marked')
    if values['asset'] not in ['Aktier','ETF','Krypto','Metaller','Råvarer','Mineselskaber']: raise ValueError('Ukendt aktivklasse')
    with connect() as c:
        c.execute('INSERT INTO opportunities('+','.join(fields)+',created,user_id) VALUES('+','.join('?' for _ in range(len(fields)+2))+')',(*[values[k] for k in fields],now(),user_id))

def password_hash(password,salt): return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
def create_user(password):
    if not 14<=len(password)<=1024: raise ValueError('Adgangskoden skal have 14–1024 tegn')
    salt=secrets.token_hex(16)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT id FROM users').fetchone(): raise ValueError('Bruger findes allerede')
        c.execute("INSERT INTO users(username,salt,hash,role) VALUES('owner',?,?,'admin')",(salt,password_hash(password,salt)))
def now(): return datetime.now(ZoneInfo('Europe/Copenhagen')).isoformat()
def proposal(data,user_id):
    nums={k:float(data[k]) for k in ['quantity','price','stop','target','costs','fx']}
    if not all(math.isfinite(v) for v in nums.values()): raise ValueError('Ugyldige tal')
    if not (nums['quantity']>0 and nums['price']>nums['stop']>0 and nums['target']>nums['price'] and nums['costs']>=0 and nums['fx']>0): raise ValueError('Kontrollér pris, stop, mål og omkostninger')
    ticker=str(data['ticker']).strip().upper()
    if not ticker or len(ticker)>24: raise ValueError('Ugyldigt symbol')
    with connect() as c:
        portfolio=c.execute('SELECT id,name FROM portfolios WHERE id=? AND user_id=? AND active=1',(int(data['portfolio_id']),user_id)).fetchone()
    if not portfolio:raise ValueError('Vælg en af dine aktive porteføljer')
    with connect() as c:
        cur=c.execute('INSERT INTO proposals(portfolio,ticker,quantity,price,stop,target,costs,fx,created,user_id,portfolio_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(portfolio['name'],ticker,*[nums[k] for k in ['quantity','price','stop','target','costs','fx']],now(),user_id,portfolio['id']))
        c.execute('INSERT INTO journal(proposal_id,event,created,user_id) VALUES(?,?,?,?)',(cur.lastrowid,'Handelsforslag oprettet • hypotetisk beregning',now(),user_id))
    return nums
class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): pass
    def send(self,status,data,kind='application/json'):
        body=json.dumps(data,ensure_ascii=False).encode() if kind=='application/json' else data
        self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store' if self.path.startswith('/api') else 'no-cache'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY'); self.send_header('Referrer-Policy','no-referrer'); self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'");
        if hasattr(self,'cookie'): self.send_header('Set-Cookie',self.cookie)
        self.end_headers(); self.wfile.write(body)
    def session(self):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: return None
        token=cookie.get('escape')
        if not token: return None
        with connect() as c:
            row=c.execute('SELECT sessions.*,users.username,users.role FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>? AND users.active=1',(token_hash(token.value),time.time())).fetchone()
        return dict(row) if row else None
    def throttled(self):
        with connect() as c:
            c.execute('DELETE FROM login_failures WHERE created<?',(time.time()-300,))
            count=c.execute('SELECT count(*) FROM login_failures WHERE address=?',(self.client_address[0],)).fetchone()[0]
        return count>=5
    def failure(self):
        with connect() as c:c.execute('INSERT INTO login_failures VALUES(?,?)',(self.client_address[0],time.time()))
    def do_DELETE(self):
        import mcp_reports
        if not mcp_reports.handle(self,connect,'DELETE'):self.send(405,{'error':'Metoden understøttes ikke'})
    def do_GET(self):
        import hotwatch_api
        if hotwatch_api.handle(self,connect,'GET'):return
        import mcp_reports
        if mcp_reports.handle(self,connect,'GET'):return
        request=urlsplit(self.path)
        self.path=request.path
        if self.path=='/api/pluto/callback':
            result='failed';s=self.session()
            try:
                query=parse_qs(request.query)
                if not s:raise ValueError('session required')
                if any(len(values)!=1 for values in query.values()):raise ValueError('duplicate callback values')
                oauth.finish(connect,s,query.get('state',[''])[0],query.get('code',[''])[0],query.get('error',[None])[0])
                with connect() as c:c.execute('DELETE FROM pluto_refresh_checks WHERE user_id=?',(s['user_id'],))
                result='connected'
            except Exception:pass
            self.send_response(303);self.send_header('Location','/?pluto='+result);self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Length','0');self.end_headers();return
        if self.path=='/api/health': return self.send(200,{'status':'ok','database':bool(connect().execute('SELECT 1').fetchone())})
        if self.path=='/api/session':
            s=self.session(); return self.send(200,{'authenticated':bool(s),'csrf':s['csrf'] if s else None,'user':{'username':s['username'],'role':s['role']} if s else None})
        if self.path.startswith('/api/'):
            s=self.session()
            if not s: return self.send(401,{'error':'Log ind først'})
            user_id=s['user_id']
            if self.path=='/api/push/config':
                import web_push
                return self.send(200,web_push.config(connect,user_id))
            if self.path=='/api/strategy-center':
                import strategy_center
                return self.send(200,strategy_center.preferences(connect,user_id))
            if self.path=='/api/admin/users':
                if s['role']!='admin':return self.send(403,{'error':'Kun administratoren kan se brugere'})
                import user_profile
                with connect() as c:
                    rows=c.execute('SELECT id,username,role,active FROM users ORDER BY username COLLATE NOCASE').fetchall()
                    users=[{**dict(row),'profile':user_profile.read(c,row['id'])} for row in rows]
                return self.send(200,{'users':users})
            if self.path=='/api/profile/postcode':
                import re
                q=parse_qs(request.query);code=q.get('code',[])
                if set(q)!={'code'} or len(code)!=1 or not re.fullmatch(r'[0-9]{4}',code[0]):return self.send(400,{'error':'Indtast et dansk postnummer med fire cifre.'})
                import user_profile
                try:city=user_profile.postcode_city(code[0])
                except (OSError,ValueError,KeyError):return self.send(503,{'error':'Postnummerlisten er ikke tilgængelig. Skriv byen selv.'})
                if not city:return self.send(404,{'error':'Postnummeret findes ikke i den lokale liste. Skriv byen selv.'})
                return self.send(200,{'city':city,'source':'GeoNames'})
            if self.path=='/api/reports/candidate-lifecycle':
                import candidate_lifecycle
                q=parse_qs(request.query);mode=q.get('is_test',['false'])
                if len(mode)!=1 or mode[0] not in ['true','false'] or any(len(v)!=1 for v in q.values()):return self.send(400,{'error':'Ugyldig statusforespørgsel'})
                try:result=candidate_lifecycle.history(connect,user_id,q.get('candidate_id',[''])[0],mode[0]=='true',q.get('before',[None])[0],int(q.get('limit',['100'])[0]))
                except ValueError:return self.send(400,{'error':'Ugyldig historikmarkør eller sidestørrelse'})
                return self.send(200,result)
            if self.path=='/api/reports/candidate-registry':
                import intel_workflows
                q=parse_qs(request.query);mode=q.get('is_test',['false'])
                if len(mode)!=1 or mode[0] not in ['true','false']:return self.send(400,{'error':'Ugyldig rapporttype'})
                with connect() as c:rows=intel_workflows.candidates(c,user_id,mode[0]=='true',include_history_market=False)
                return self.send(200,{'candidates':rows,'is_test':mode[0]=='true'})
            if self.path=='/api/sector-intelligence/holdings':
                import sector_intelligence
                try:result=sector_intelligence.request_benchmark_holdings(connect,user_id,data.get('symbol'),data.get('limit',20))
                except ValueError as error:return self.send(400,{'error':str(error)})
                return self.send(200,result)
            if self.path=='/api/reports/hot-watch':
                import intel_workflows
                q=parse_qs(request.query);mode=q.get('is_test',['false'])
                if len(mode)!=1 or mode[0] not in ['true','false']:return self.send(400,{'error':'Ugyldig rapporttype'})
                return self.send(200,intel_workflows.watch(connect,user_id,mode[0]=='true',q.get('candidate_id',[None])[0]))
            if self.path=='/api/reports/desk':
                import report_ingest
                return self.send(200,report_ingest.desk(connect,user_id))
            if self.path=='/api/reports/schema':
                import report_v2
                return self.send(200,report_v2.SCHEMA)
            if self.path in ['/api/reports/history','/api/reports/item','/api/reports/candidate-history','/api/reports/position-history']:
                import report_ingest
                q=parse_qs(request.query);mode=q.get('is_test',['false'])
                if len(mode)!=1 or mode[0] not in ['true','false']:return self.send(400,{'error':'Ugyldig rapporttype'})
                test=mode[0]=='true'
                if self.path.endswith('/history'):return self.send(200,report_ingest.history(connect,user_id,test))
                if self.path.endswith('/item'):return self.send(200,report_ingest.item(connect,user_id,q.get('report_id',[''])[0],test,record_readback=True))
                if self.path.endswith('/position-history'):
                    import position_reports
                    return self.send(200,position_reports.history(connect,user_id,q.get('portfolio_id',[''])[0],q.get('position_id',[''])[0],test))
                return self.send(200,report_ingest.candidate_history(connect,user_id,q.get('candidate_id',[''])[0],test))
            if self.path=='/api/reports/latest':
                import report_ingest
                mode=parse_qs(request.query).get('is_test',['false'])
                if len(mode)!=1 or mode[0] not in ['true','false']:return self.send(400,{'error':'Ugyldig rapporttype'})
                return self.send(200,report_ingest.latest(connect,user_id,mode[0]=='true'))
            if self.path=='/api/automation':
                import jobs
                return self.send(200,jobs.status(connect,user_id))
            if self.path=='/api/connections': return self.send(200,connection_state(user_id))
            if self.path=='/api/dashboard/journal':
                import journal_projection
                q=parse_qs(request.query)
                if any(len(v)!=1 for v in q.values()) or set(q)-{'days','source','kind','before','limit'}:return self.send(400,{'error':'Ugyldigt journalfilter'})
                try:result=journal_projection.read(connect,user_id,days=int(q.get('days',['7'])[0]),source=q.get('source',['all'])[0],kind=q.get('kind',['all'])[0],before=q.get('before',[None])[0],limit=int(q.get('limit',['100'])[0]))
                except (ValueError,OverflowError):return self.send(400,{'error':'Ugyldigt journalfilter'})
                return self.send(200,result)
            if self.path=='/api/sector-intelligence':
                import sector_intelligence
                return self.send(200,sector_intelligence.read(connect,user_id))
            if self.path=='/api/state':
                import portfolios
                with connect() as c:
                    owned=portfolios.list_owned(c,user_id)
                    import portfolio_data
                    snapshots=portfolio_data.snapshots(c,user_id)
                summary=portfolio_data.summaries(owned,snapshots)
                import dashboard_projection
                dashboard=dashboard_projection.build(connect,user_id,owned,snapshots)
                with connect() as c: p=[dict(r) for r in c.execute('SELECT * FROM proposals WHERE user_id=? ORDER BY id DESC',(user_id,))]; j=[dict(r) for r in c.execute('SELECT * FROM journal WHERE user_id=? ORDER BY id DESC',(user_id,))]
                with connect() as c: opportunities=[dict(r) for r in c.execute('SELECT * FROM opportunities WHERE user_id=? ORDER BY id DESC',(user_id,))]
                import trade_service,hotwatch_adapters
                provider_status=hotwatch_adapters.providers(connect,user_id,False)
                with connect() as c:test_trade_signal=trade_service.active_test_signal(c,user_id)
                import user_profile
                with connect() as c: profile=user_profile.read(c,user_id)
                return self.send(200,{'profile':profile,'provider_status':provider_status,'dashboard':dashboard,'test_trade_signal':test_trade_signal,'broker_proposals':trade_service.summaries(connect,user_id),'portfolio_snapshots':snapshots,'portfolio_summary':summary,'portfolios':owned,'user':{'username':s['username'],'role':s['role']},'connection':connection_state(user_id),'opportunities':opportunities,'proposals':p,'journal':j,'time':now(),'integrations':{'Pluto Markets':'Ikke tilsluttet','Markedsdata':'Ikke tilsluttet','Nyheder og AI':'Ikke tilsluttet'},'reports':{'timezone':'Europe/Copenhagen','schedule':['08:00','14:00','22:00'],'status':'Afventer datakilder og scheduler'}})
            return self.send(404,{'error':'Ukendt endpoint'})
        path={'/':'index.html','/app.js':'app.js','/report-ui.js':'report-ui.js','/style.css':'style.css','/manifest.json':'manifest.json','/sw.js':'sw.js','/icon.svg':'icon.svg'}.get(self.path)
        if not path:return self.send(404,{'error':'Ikke fundet'})
        kind={'.html':'text/html; charset=utf-8','.js':'application/javascript','.css':'text/css','.json':'application/manifest+json','.svg':'image/svg+xml'}[Path(path).suffix]
        body=(ROOT/'static'/path).read_bytes()
        if path=='app.js':body=(ROOT/'static/sector-ui.js').read_bytes()+b'\n'+(ROOT/'static/journal-ui.js').read_bytes()+b'\n'+(ROOT/'static/dashboard-ui.js').read_bytes()+b'\n'+(ROOT/'static/candidate-ui.js').read_bytes()+b'\n'+(ROOT/'static/engine-ui.js').read_bytes()+b'\n'+(ROOT/'static/intel-ui.js').read_bytes()+b'\n'+(ROOT/'static/position-ui.js').read_bytes()+b'\n'+(ROOT/'static/overview-ui.js').read_bytes()+b'\n'+(ROOT/'static/market-ui.js').read_bytes()+b'\n'+(ROOT/'static/report-ui.js').read_bytes()+b'\n'+(ROOT/'static/trade-ui.js').read_bytes()+b'\n'+body
        self.send(200,body,kind)
    def do_POST(self):
        import hotwatch_api
        if hotwatch_api.handle(self,connect,'POST'):return
        import mcp_reports
        if mcp_reports.handle(self,connect,'POST'):return
        try:
            if self.path=='/api/reports/ingest':
                import report_ingest
                recipient,status=report_ingest.recipient(connect,self.headers.get('Authorization'))
                if status!=200:return self.send(status,{'error':'Rapportmodtagelse er ikke konfigureret' if status==503 else 'Ugyldig rapportnøgle'})
                if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':return self.send(415,{'error':'Brug application/json'})
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=262144:return self.send(413,{'error':'Rapporten er for stor'})
                raw=self.rfile.read(length)
                def unique(pairs):
                    obj={}
                    for key,value in pairs:
                        if key in obj:raise ValueError('duplicate key')
                        obj[key]=value
                    return obj
                try:data=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('invalid number')))
                except ValueError:return self.send(413 if length>16384 else 400,{'error':'Ugyldig eller for stor rapport'})
                if length>16384 and (not isinstance(data,dict) or data.get('schema_version')!=2):return self.send(413,{'error':'v1 må højst fylde 16384 bytes'})
                status,result=report_ingest.save(connect,recipient,data)
                return self.send(status,result)
            length=int(self.headers.get('Content-Length','0'))
            if length>(262144 if self.path in ['/api/reports/import','/api/reports/hot-watch'] else 16384): return self.send(413,{'error':'For stor forespørgsel'})
            data=json.loads(self.rfile.read(length),object_pairs_hook=unique_object) if self.path in ['/api/reports/import','/api/reports/hot-watch'] else json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError('Ugyldig forespørgsel')
            if self.path in ['/api/login','/api/register']:
                if self.throttled():return self.send(429,{'error':'Prøv igen om fem minutter'})
                if self.path=='/api/register':
                    try:name=register(data)
                    except ValueError as error:
                        self.failure();return self.send(400,{'error':str(error)})
                    return self.send(201,{'ok':True,'username':name})
                name=str(data.get('username','owner')).strip().lower()
                password=str(data.get('password',''))
                with connect() as c: u=c.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE AND active=1',(name,)).fetchone()
                salt=u['salt'] if u else '00'*16
                digest=password_hash(password[:1024],salt)
                if not u or len(password)>1024 or not hmac.compare_digest(digest,u['hash']):
                    self.failure(); return self.send(401,{'error':'Forkert brugernavn eller adgangskode'})
                token=secrets.token_urlsafe(32)
                with connect() as c:
                    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(token_hash(token),u['id'],secrets.token_urlsafe(32),time.time()+28800))
                self.cookie=f"escape={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800"+('; Secure' if os.environ.get('ESCAPE_SECURE_COOKIE')=='1' else '')
                return self.send(200,{'ok':True})
            s=self.session()
            if not s:return self.send(401,{'error':'Log ind først'})
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),s['csrf']):return self.send(403,{'error':'Ugyldigt sikkerhedstoken'})
            user_id=s['user_id']
            if self.path=='/api/admin/reset-password':
                if s['role']!='admin':return self.send(403,{'error':'Kun administratoren kan ændre brugerens adgangskode'})
                if self.throttled():return self.send(429,{'error':'Prøv igen om fem minutter'})
                target=data.get('user_id');password=data.get('new_password');current=data.get('admin_password')
                if type(target) is not int or not isinstance(password,str) or not 14<=len(password)<=1024 or not isinstance(current,str) or len(current)>1024:
                    return self.send(400,{'error':'Udfyld din adgangskode og en ny adgangskode på 14–1024 tegn.'})
                with connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    actor=c.execute("SELECT salt,hash FROM users WHERE id=? AND role='admin' AND active=1",(user_id,)).fetchone()
                    if not actor or not hmac.compare_digest(password_hash(current,actor['salt']),actor['hash']):
                        c.execute('INSERT INTO login_failures VALUES(?,?)',(self.client_address[0],time.time()));return self.send(403,{'error':'Din administratoradgangskode er forkert.'})
                    row=c.execute("SELECT id FROM users WHERE id=? AND role='member' AND active=1",(target,)).fetchone()
                    if not row:return self.send(404,{'error':'Aktiv bruger blev ikke fundet.'})
                    salt=secrets.token_hex(16);digest=password_hash(password,salt)
                    c.execute('UPDATE users SET salt=?,hash=? WHERE id=?',(salt,digest,target))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(target,))
                    c.execute("INSERT INTO admin_actions(admin_id,target_id,action,created) VALUES(?,?,'password_reset',?)",(user_id,target,now()))
                return self.send(200,{'ok':True})
            if self.path in ('/api/push/subscribe','/api/push/unsubscribe','/api/push/device','/api/push/test'):
                import web_push
                try:
                    if self.path.endswith('/subscribe'):result=web_push.subscribe(connect,user_id,data)
                    elif self.path.endswith('/unsubscribe'):result=web_push.unsubscribe(connect,user_id,data.get('endpoint'))
                    elif self.path.endswith('/device'):result=web_push.device_preferences(connect,user_id,data.get('endpoint'))
                    else:result=web_push.send_test(connect,user_id,data.get('endpoint'))
                except ValueError as error:return self.send(400,{'error':str(error)})
                except Exception:return self.send(503,{'error':'Notifikationen kunne ikke gennemføres. Kontrollér enhed og serveropsætning.'})
                return self.send(200,result)
            if self.path=='/api/strategy-center':
                import strategy_center
                try:result=strategy_center.save(connect,user_id,data,now())
                except ValueError as error:return self.send(400,{'error':str(error)})
                return self.send(200,result)
            if self.path in ('/api/profile/start','/api/profile/save'):
                import user_profile
                try:
                    with connect() as c:
                        profile=user_profile.start(c,user_id) if self.path.endswith('/start') else user_profile.save(c,user_id,data,now())
                except ValueError as error:return self.send(400,{'error':str(error)})
                return self.send(200,{'profile':profile})
            if self.path=='/api/reports/reset-radar':
                if data.get('confirm') is not True:return self.send(400,{'error':'Bekræft nulstillingen først.'})
                import report_ingest
                return self.send(200,report_ingest.reset_radar(connect,user_id))
            if self.path=='/api/sector-intelligence/holdings':
                import sector_intelligence
                try:result=sector_intelligence.request_benchmark_holdings(connect,user_id,data.get('symbol'),data.get('limit',20))
                except ValueError as error:return self.send(400,{'error':str(error)})
                return self.send(200,result)
            if self.path=='/api/reports/hot-watch':
                import intel_workflows
                status,result=intel_workflows.record(connect,user_id,data)
                return self.send(status,result)
            if self.path in ['/api/reports/import','/api/reports/analysis-package']:
                import report_ingest
                if self.path.endswith('/analysis-package'):return self.send(200,report_ingest.analysis_package(connect,user_id,data))
                status,result=report_ingest.save(connect,user_id,data)
                return self.send(status,result)
            if self.path=='/api/logout':
                with connect() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(s['token_hash'],))
                self.cookie='escape=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'; return self.send(200,{'ok':True})
            if self.path=='/api/invitations':
                if s['role']!='admin':return self.send(403,{'error':'Kun administratoren kan invitere'})
                token=secrets.token_urlsafe(32)
                with connect() as c:
                    c.execute('INSERT INTO invitations VALUES(?,?,?,0)',(token_hash(token),user_id,time.time()+86400))
                return self.send(201,{'invitation':token,'expires_in_hours':24})
            if self.path=='/api/news/refresh':
                import news
                result=news.refresh(connect)
                return self.send(200 if result['ok'] else 502,result)
            if self.path=='/api/jobs/ecb':
                if s['role']!='admin':return self.send(403,{'error':'Kun administratoren kan starte datakørsel'})
                import jobs
                with connect() as c:
                    jobs.enqueue(c,'ecb',user_id,'ecb:manual:'+str(int(time.time()//60)))
                    jobs.enqueue(c,'news',user_id,'news:manual:'+str(int(time.time()//60)))
                return self.send(202,{'ok':True,'message':'Jobbet er sat i kø. Det køres ved næste worker-kørsel.'})
            if self.path=='/api/pluto/request':
                with connect() as c:
                    c.execute("INSERT INTO connections(user_id,status,requested) VALUES(?,'Adgang ønsket',?) ON CONFLICT(user_id) DO NOTHING",(user_id,now()))
                return self.send(200,connection_state(user_id))
            if self.path=='/api/pluto/disconnect':
                oauth.revoke(connect,user_id)
                with connect() as c:c.execute('DELETE FROM connections WHERE user_id=?',(user_id,))
                return self.send(200,connection_state(user_id))
            if self.path=='/api/portfolios':
                import portfolios
                with connect() as c:pid=portfolios.create(c,user_id,data['name'])
                return self.send(201,{'id':pid})
            if self.path=='/api/portfolios/rename':
                import portfolios
                with connect() as c:portfolios.rename(c,user_id,int(data['id']),data['name'])
                return self.send(200,{'ok':True})
            if self.path=='/api/portfolios/data':
                import portfolio_data
                pid=int(data['id'])
                with connect() as c:
                    if not c.execute("SELECT 1 FROM portfolios WHERE id=? AND user_id=? AND source='pluto' AND active=1",(pid,user_id)).fetchone():return self.send(400,{'error':'Porteføljen findes ikke på din aktive Pluto-liste'})
                if not portfolio_data.claim_refresh(connect,user_id,'data:'+str(pid),data.get('automatic') is True):return self.send(200,{'cached':True,'complete':None,'errors':[],'message':'Seneste læseforsøg er under fem minutter gammelt. Gemte data bevares.'})
                try:payload=portfolio_data.read(connect,user_id,pid)
                except oauth.SetupRequired:
                    with connect() as c:portfolio_data.mark_failed(c,user_id,pid,'Seneste læsning fejlede; gemte data kan være forældede')
                    raise
                except Exception:
                    with connect() as c:portfolio_data.mark_failed(c,user_id,pid,'Seneste Pluto-opslag fejlede; gemte data kan være forældede')
                    return self.send(502,{'error':'Pluto-opslaget fejlede. Tidligere data er bevaret og markeret.'})
                with connect() as c:portfolio_data.save(c,user_id,pid,payload)
                issues=payload['errors']+payload.get('order_errors',[])
                return self.send(200,{'ok':True,'complete':payload['complete'] and payload.get('orders_complete',False),'errors':issues,'message':'Pluto-data hentet'+(' med delvise fejl' if issues else '')})
            if self.path=='/api/portfolios/sync':
                import mcp_client,portfolios,portfolio_data
                if not portfolio_data.claim_refresh(connect,user_id,'list',data.get('automatic') is True):return self.send(200,{'cached':True,'message':'Pluto-listen er allerede forsøgt opdateret inden for fem minutter.'})
                items=mcp_client.read_portfolios(connect,user_id)
                with connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    portfolios.replace_pluto(c,user_id,items)
                return self.send(200,{'ok':True,'count':len(items),'message':'Porteføljer og Collections hentet fra Pluto. Beholdninger og kurser er endnu ikke hentet.'})
            if self.path=='/api/pluto/catalog':
                import mcp_client
                return self.send(200,mcp_client.catalog(connect,user_id))
            if self.path=='/api/pluto/start':
                return self.send(200,oauth.start(connect,s,trade=data.get('trade') is True))
            if self.path=='/api/pluto/connect':
                with connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    previous=c.execute('SELECT checked FROM connection_checks WHERE user_id=?',(user_id,)).fetchone()
                    if previous and previous['checked']>time.time()-60:
                        return self.send(429,{'error':'Vent et minut mellem forbindelsestests'})
                    c.execute('INSERT INTO connection_checks VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET checked=excluded.checked',(user_id,time.time()))
                from pluto import discover
                return self.send(200,discover())
            if self.path=='/api/market/eodhd-symbols':
                import hotwatch_adapters,market_data
                try:return self.send(200,hotwatch_adapters.search_eodhd_symbols(connect,user_id,data))
                except hotwatch_adapters.DataUnavailable as error:return self.send(error.status,{'error':error.code})
                except market_data.MarketError:return self.send(409,{'error':'EODHD_SYMBOL_SEARCH_FAILED'})
                except Exception:return self.send(502,{'error':'EODHD_SYMBOL_SEARCH_FAILED'})
            if self.path=='/api/market/quote':
                import market_data
                try:return self.send(200,market_data.quote(connect,user_id,data))
                except (market_data.MarketError,market_data.trade_service.TradeError) as error:return self.send(409,{'error':str(error)})
                except oauth.SetupRequired:raise
                except Exception:return self.send(502,{'error':'Pluto-kursopslaget kunne ikke gennemføres. Prøv igen om lidt.'})
            if self.path.startswith('/api/trade/'):
                import trade_service
                try:
                    action=self.path.rsplit('/',1)[1]
                    if action=='history':result={'proposals':trade_service.history(connect,user_id)}
                    elif action=='search':result=trade_service.search(connect,user_id,data.get('query'))
                    elif action=='preview':result=trade_service.preview(connect,user_id,data)
                    elif action=='estimate':result=trade_service.estimate(connect,user_id,data)
                    elif action=='send':result=trade_service.send(connect,user_id,data)
                    elif action=='status':result=trade_service.check(connect,user_id,data.get('id'))
                    elif action=='cancel':result=trade_service.cancel_intent(connect,user_id,data.get('id'))
                    else:return self.send(404,{'error':'Ukendt handelsfunktion'})
                    return self.send(200,result)
                except trade_service.InsufficientBuyingPower as error:return self.send(409,{'error':str(error),'code':'insufficient_buying_power','available':error.available,'currency':error.currency,**({'provider_error':error.provider_message} if error.provider_message else {})})
                except trade_service.TradeError as error:return self.send(400,{'error':str(error)})
                except oauth.SetupRequired:raise
                except Exception:return self.send(502,{'error':'Pluto-opslaget kunne ikke gennemføres. Kontrollér forbindelsen, instrumentets begrænsninger og Plutos adgangskrav. Intet forslag er automatisk genafsendt.'})
            if self.path=='/api/opportunities': save_opportunity(data,user_id); return self.send(201,{'ok':True})
            if self.path=='/api/proposals': proposal(data,user_id); return self.send(201,{'ok':True})
            if self.path=='/api/approve':
                with connect() as c:
                    r=c.execute("UPDATE proposals SET status='Godkendt lokalt' WHERE id=? AND user_id=? AND status='Forslag'",(int(data['id']),user_id))
                    if r.rowcount!=1:raise ValueError('Forslaget findes ikke eller er allerede behandlet')
                    c.execute('INSERT INTO journal(proposal_id,event,created,user_id) VALUES(?,?,?,?)',(data['id'],'Godkendt lokalt • ingen ordre sendt til mægler',now(),user_id))
                return self.send(200,{'ok':True})
            return self.send(404,{'error':'Ukendt endpoint'})
        except ReportValidationError as error:self.send(400,{'error':'Rapportvalidering fejlede',**error.result})
        except oauth.SetupRequired as error:self.send(409,{'error':str(error)})
        except (ValueError,KeyError,TypeError,RecursionError,OverflowError,sqlite3.IntegrityError):self.send(400,{'error':'Ugyldige oplysninger eller handling'})
        except Exception:self.send(500,{'error':'Intern fejl. Kontrollér server og database.'})
LOGIN_FAILURES={}
if __name__=='__main__':
    import argparse,getpass
    parser=argparse.ArgumentParser();parser.add_argument('--create-user',action='store_true');parser.add_argument('--port',type=int,default=8000);args=parser.parse_args();init()
    if args.create_user:create_user(getpass.getpass('Ny adgangskode (mindst 14 tegn): '))
    else:ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
