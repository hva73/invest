import os, sqlite3, json, secrets, hashlib, hmac, time, math
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
ROOT=Path(__file__).parent
DB=os.environ.get('ESCAPE_DB',str(ROOT/'var/escape.db'))
SESSIONS={}
def connect():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def init():
    init_content()
    with connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, salt TEXT, hash TEXT); CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY, portfolio TEXT, ticker TEXT, quantity REAL, price REAL, stop REAL, target REAL, costs REAL, fx REAL, status TEXT DEFAULT 'Forslag', created TEXT); CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, proposal_id INTEGER, event TEXT, created TEXT);''')
def init_content():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS opportunities(id INTEGER PRIMARY KEY, company TEXT NOT NULL, ticker TEXT NOT NULL, market TEXT NOT NULL, asset TEXT NOT NULL, headline TEXT NOT NULL, source_url TEXT NOT NULL, published TEXT NOT NULL, classification TEXT NOT NULL, catalyst TEXT NOT NULL, risk TEXT NOT NULL, next_action TEXT NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OVERVÅG')""")

def save_opportunity(data):
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
        c.execute('INSERT INTO opportunities('+','.join(fields)+',created) VALUES('+','.join('?' for _ in range(len(fields)+1))+')',(*[values[k] for k in fields],now()))

def password_hash(password,salt): return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
def create_user(password):
    if len(password)<14: raise ValueError('Adgangskoden skal have mindst 14 tegn')
    salt=secrets.token_hex(16)
    with connect() as c:
        if c.execute('SELECT id FROM users').fetchone(): raise ValueError('Bruger findes allerede')
        c.execute('INSERT INTO users(salt,hash) VALUES(?,?)',(salt,password_hash(password,salt)))
def now(): return datetime.now(ZoneInfo('Europe/Copenhagen')).isoformat()
def proposal(data):
    nums={k:float(data[k]) for k in ['quantity','price','stop','target','costs','fx']}
    if not all(math.isfinite(v) for v in nums.values()): raise ValueError('Ugyldige tal')
    if not (nums['quantity']>0 and nums['price']>nums['stop']>0 and nums['target']>nums['price'] and nums['costs']>=0 and nums['fx']>0): raise ValueError('Kontrollér pris, stop, mål og omkostninger')
    ticker=str(data['ticker']).strip().upper()
    if not ticker or len(ticker)>24: raise ValueError('Ugyldigt symbol')
    if data['portfolio'] not in ['Hovedportefølje','ESCAPE AI Trader']: raise ValueError('Ukendt portefølje')
    with connect() as c:
        cur=c.execute('INSERT INTO proposals(portfolio,ticker,quantity,price,stop,target,costs,fx,created) VALUES(?,?,?,?,?,?,?,?,?)',(data['portfolio'],ticker,*[nums[k] for k in ['quantity','price','stop','target','costs','fx']],now()))
        c.execute('INSERT INTO journal(proposal_id,event,created) VALUES(?,?,?)',(cur.lastrowid,'Handelsforslag oprettet • hypotetisk beregning',now()))
    return nums
class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): pass
    def send(self,status,data,kind='application/json'):
        body=json.dumps(data,ensure_ascii=False).encode() if kind=='application/json' else data
        self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store' if self.path.startswith('/api') else 'no-cache'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY'); self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'");
        if hasattr(self,'cookie'): self.send_header('Set-Cookie',self.cookie)
        self.end_headers(); self.wfile.write(body)
    def session(self):
        cookie=SimpleCookie(); cookie.load(self.headers.get('Cookie','')); token=cookie.get('escape'); s=SESSIONS.get(token.value) if token else None
        return s if s and s['expires']>time.time() else None
    def do_GET(self):
        if self.path=='/api/health': return self.send(200,{'status':'ok','database':bool(connect().execute('SELECT 1').fetchone())})
        if self.path=='/api/session':
            s=self.session(); return self.send(200,{'authenticated':bool(s),'csrf':s['csrf'] if s else None})
        if self.path.startswith('/api/'):
            if not self.session(): return self.send(401,{'error':'Log ind først'})
            if self.path=='/api/state':
                with connect() as c: p=[dict(r) for r in c.execute('SELECT * FROM proposals ORDER BY id DESC')]; j=[dict(r) for r in c.execute('SELECT * FROM journal ORDER BY id DESC')]
                with connect() as c: opportunities=[dict(r) for r in c.execute('SELECT * FROM opportunities ORDER BY id DESC')]
                return self.send(200,{'opportunities':opportunities,'proposals':p,'journal':j,'time':now(),'integrations':{'Pluto Markets':'Ikke tilsluttet','Markedsdata':'Ikke tilsluttet','Nyheder og AI':'Ikke tilsluttet'},'reports':{'timezone':'Europe/Copenhagen','schedule':['08:00','14:00','22:00'],'status':'Afventer datakilder og scheduler'}})
            return self.send(404,{'error':'Ukendt endpoint'})
        path={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/manifest.json':'manifest.json','/sw.js':'sw.js','/icon.svg':'icon.svg'}.get(self.path)
        if not path:return self.send(404,{'error':'Ikke fundet'})
        kind={'.html':'text/html; charset=utf-8','.js':'application/javascript','.css':'text/css','.json':'application/manifest+json','.svg':'image/svg+xml'}[Path(path).suffix]
        self.send(200,(ROOT/'static'/path).read_bytes(),kind)
    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>16384: return self.send(413,{'error':'For stor forespørgsel'})
            data=json.loads(self.rfile.read(length))
            if self.path=='/api/login':
                address=self.client_address[0]; failures=LOGIN_FAILURES.get(address,[]); failures=[t for t in failures if t>time.time()-300]
                if len(failures)>=5:return self.send(429,{'error':'Prøv igen om fem minutter'})
                with connect() as c: u=c.execute('SELECT * FROM users').fetchone()
                if not u or not hmac.compare_digest(password_hash(str(data.get('password','')),u['salt']),u['hash']):
                    LOGIN_FAILURES[address]=failures+[time.time()]; return self.send(401,{'error':'Forkert adgangskode eller bruger ikke oprettet'})
                token=secrets.token_urlsafe(32); SESSIONS[token]={'csrf':secrets.token_urlsafe(32),'expires':time.time()+28800}
                self.cookie=f"escape={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"+('; Secure' if os.environ.get('ESCAPE_SECURE_COOKIE')=='1' else '')
                return self.send(200,{'ok':True})
            s=self.session()
            if not s:return self.send(401,{'error':'Log ind først'})
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),s['csrf']):return self.send(403,{'error':'Ugyldigt sikkerhedstoken'})
            if self.path=='/api/logout':
                for key,value in list(SESSIONS.items()):
                    if value is s:del SESSIONS[key]
                self.cookie='escape=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'; return self.send(200,{'ok':True})
            if self.path=='/api/opportunities': save_opportunity(data); return self.send(201,{'ok':True})
            if self.path=='/api/proposals': proposal(data); return self.send(201,{'ok':True})
            if self.path=='/api/approve':
                with connect() as c:
                    r=c.execute("UPDATE proposals SET status='Godkendt lokalt' WHERE id=? AND status='Forslag'",(int(data['id']),))
                    if r.rowcount!=1:raise ValueError('Forslaget findes ikke eller er allerede behandlet')
                    c.execute('INSERT INTO journal(proposal_id,event,created) VALUES(?,?,?)',(data['id'],'Godkendt lokalt • ingen ordre sendt til mægler',now()))
                return self.send(200,{'ok':True})
            return self.send(404,{'error':'Ukendt endpoint'})
        except (ValueError,KeyError,TypeError):self.send(400,{'error':'Ugyldige oplysninger eller handling'})
        except Exception:self.send(500,{'error':'Intern fejl. Kontrollér server og database.'})
LOGIN_FAILURES={}
if __name__=='__main__':
    import argparse,getpass
    parser=argparse.ArgumentParser();parser.add_argument('--create-user',action='store_true');parser.add_argument('--port',type=int,default=8000);args=parser.parse_args();init()
    if args.create_user:create_user(getpass.getpass('Ny adgangskode (mindst 14 tegn): '))
    else:ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
