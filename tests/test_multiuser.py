import io,json,sqlite3,tempfile,unittest
import app
import passenger_wsgi as wsgi
class Accounts(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.previous_db=app.DB;app.DB=self.tmp.name+'/db.sqlite';app.init();app.create_user('owner-password-at-least-14');self.cookie='';self.csrf=''
 def tearDown(self):app.DB=self.previous_db;self.tmp.cleanup()
 def request(self,path,data=None,csrf=True):
  payload=json.dumps(data).encode() if data is not None else b'';result={}
  def start(status,headers):result.update(status=int(status.split()[0]),headers=dict(headers))
  body=b''.join(wsgi.application({'PATH_INFO':'/api/'+path,'REQUEST_METHOD':'POST' if data is not None else 'GET','REMOTE_ADDR':'test','CONTENT_LENGTH':str(len(payload)),'wsgi.input':io.BytesIO(payload),'HTTP_COOKIE':self.cookie,'HTTP_X_CSRF_TOKEN':self.csrf if csrf else ''},start))
  if 'Set-Cookie' in result['headers']:self.cookie=result['headers']['Set-Cookie'].split(';')[0]
  return result['status'],json.loads(body)
 def login(self,name='owner',password='owner-password-at-least-14'):
  self.assertEqual(self.request('login',{'username':name,'password':password})[0],200);self.csrf=self.request('session')[1]['csrf']
 def invite(self):return self.request('invitations',{})[1]['invitation']
 def test_isolation_and_connection_requests(self):
  self.login();token=self.invite();owner_cookie,owner_csrf=self.cookie,self.csrf
  self.assertEqual(self.request('register',{'username':'other','password':'other-password-at-least-14','invitation':token,'role':'admin'})[0],201)
  p={'portfolio':'ESCAPE AI Trader','ticker':'TEST','quantity':1,'price':100,'stop':90,'target':120,'costs':0,'fx':1,'user_id':2}
  self.assertEqual(self.request('proposals',p)[0],201)
  opportunity={'company':'Test','ticker':'TEST','market':'USA','asset':'Aktier','headline':'Test only','source_url':'https://example.com','published':'2020-01-01T00:00:00Z','classification':'Spekulation','catalyst':'Unknown','risk':'Unknown','next_action':'Read','user_id':2}
  self.assertEqual(self.request('opportunities',opportunity)[0],201)
  self.assertEqual(self.request('pluto/request',{})[0],200)
  self.login('other','other-password-at-least-14');state=self.request('state')[1]
  self.assertEqual(state['user']['role'],'member')
  for key in ['proposals','journal','opportunities']:self.assertEqual(state[key],[])
  self.assertIsNone(state['connection']['requested'])
  self.assertEqual(self.request('approve',{'id':1})[0],400)
  self.assertEqual(self.request('invitations',{})[0],403)
  self.assertEqual(self.request('jobs/ecb',{})[0],403)
  self.assertEqual(self.request('pluto/start',{},False)[0],403)
  from unittest.mock import patch
  with patch('pluto.discover',return_value={'connected':False,'discovery_valid':True}):
   self.assertEqual(self.request('pluto/connect',{})[0],200)
   self.assertEqual(self.request('pluto/connect',{})[0],429)
  self.assertEqual(self.request('pluto/request',{},False)[0],403)
  self.request('pluto/request',{});self.request('pluto/disconnect',{})
  self.cookie,self.csrf=owner_cookie,owner_csrf
  self.assertIsNotNone(self.request('connections')[1]['requested'])
  self.assertEqual(self.request('jobs/ecb',{})[0],202)
  self.assertEqual(len(self.request('automation')[1]['jobs']),2)
  self.assertEqual(len(self.request('state')[1]['proposals']),1)
  self.assertEqual(len(self.request('state')[1]['opportunities']),1)
 def test_invitation_reuse_expiry_and_privacy(self):
  self.login();token=self.invite()
  with app.connect() as c:
   stored=c.execute('SELECT token_hash FROM invitations').fetchone()[0]
   self.assertNotEqual(stored,token)
  data={'username':'member','password':'a-valid-long-password','invitation':token}
  self.assertEqual(self.request('register',data)[0],201)
  data['username']='another';self.assertEqual(self.request('register',data)[0],400)
  token=self.invite()
  with app.connect() as c:c.execute('UPDATE invitations SET expires=0 WHERE token_hash=?',(app.token_hash(token),))
  data['invitation']=token;self.assertEqual(self.request('register',data)[0],400)
 def test_shared_sessions_expiry_logout(self):
  self.login();cookie=self.cookie
  app.SESSIONS.clear();app.init()
  self.assertTrue(self.request('session')[1]['authenticated'])
  with app.connect() as c:self.assertNotIn(cookie.split('=')[1],[r[0] for r in c.execute('SELECT token_hash FROM sessions')])
  self.request('logout',{});self.cookie=cookie
  self.assertEqual(self.request('state')[0],401)
  self.login()
  with app.connect() as c:c.execute('UPDATE sessions SET expires=0')
  self.assertEqual(self.request('state')[0],401)
 def test_legacy_migration(self):
  app.DB=self.tmp.name+'/legacy.sqlite'
  c=sqlite3.connect(app.DB);salt='12'*16;digest=app.password_hash('legacy-password-long',salt)
  c.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,salt TEXT,hash TEXT); CREATE TABLE proposals(id INTEGER PRIMARY KEY,portfolio TEXT,ticker TEXT,quantity REAL,price REAL,stop REAL,target REAL,costs REAL,fx REAL,status TEXT,created TEXT); CREATE TABLE journal(id INTEGER PRIMARY KEY,proposal_id INTEGER,event TEXT,created TEXT);")
  c.execute('INSERT INTO users VALUES(7,?,?)',(salt,digest));c.execute("INSERT INTO proposals VALUES(1,'Hovedportefølje','LEGACY',1,10,9,12,0,1,'Forslag','2020')");c.execute("INSERT INTO journal VALUES(1,1,'legacy event','2020')");c.commit();c.close()
  app.init();app.init();self.login('owner','legacy-password-long');state=self.request('state')[1]
  self.assertEqual(state['user']['role'],'admin');self.assertEqual(state['proposals'][0]['ticker'],'LEGACY');self.assertEqual(state['journal'][0]['user_id'],7)
  with app.connect() as c:self.assertEqual(c.execute('SELECT hash FROM users').fetchone()[0],digest)
 def test_ambiguous_migration_rolls_back(self):
  app.DB=self.tmp.name+'/ambiguous.sqlite'
  with sqlite3.connect(app.DB) as c:
   c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,salt TEXT,hash TEXT)');c.executemany('INSERT INTO users VALUES(?,?,?)',[(1,'salt','hash'),(2,'salt','hash')])
  with self.assertRaises(RuntimeError):app.init()
  with sqlite3.connect(app.DB) as c:self.assertEqual(len(c.execute('SELECT * FROM users').fetchall()),2)
