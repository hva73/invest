import base64,hashlib,os,tempfile,time,unittest
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch
import app,oauth
from pluto import MCP_URL
class OAuth(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.previous=app.DB;app.DB=self.tmp.name+'/oauth.db';app.init();app.create_user('test-password-long')
  self.env=patch.dict(os.environ,{'ESCAPE_PUBLIC_URL':'https://escape.example.org','PLUTO_READ_SCOPES':'portfolio:read','ESCAPE_TOKEN_KEY_FILE':self.tmp.name+'/keys/token.key','PLUTO_CLIENT_ID':'test-client'});self.env.start();oauth.setup_key()
  self.session={'user_id':1,'token_hash':'test-session'}
  self.metadata={'discovery_valid':True,'oauth':{'verified':True,'issuer':'https://mcp.prod.pluto.markets','authorization_endpoint':'https://mcp.prod.pluto.markets/authorize','token_endpoint':'https://mcp.prod.pluto.markets/token','revocation_endpoint':'https://mcp.prod.pluto.markets/revoke','scopes_supported':['portfolio:read'],'code_challenge_methods_supported':['S256'],'token_endpoint_auth_methods_supported':['none']}}
 def tearDown(self):self.env.stop();app.DB=self.previous;self.tmp.cleanup()
 def begin(self):return parse_qs(urlsplit(oauth.start(app.connect,self.session,self.metadata)['authorization_url']).query)
 def test_pkce_encryption_and_callback(self):
  query=self.begin();captured={}
  def post(url,data,form=False):captured.update(data);return {'access_token':'test-access-token','refresh_token':'test-refresh-token','token_type':'Bearer','expires_in':300,'scope':'portfolio:read'}
  oauth.finish(app.connect,self.session,query['state'][0],'test-code',post=post)
  self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(captured['code_verifier'].encode()).digest()).rstrip(b'=').decode(),query['code_challenge'][0])
  with app.connect() as c:row=c.execute('SELECT payload FROM oauth_tokens').fetchone()
  self.assertNotIn(b'test-access-token',row['payload']);self.assertEqual(oauth.unseal(1,row['payload'])['token']['access_token'],'test-access-token')
  with self.assertRaises(Exception):oauth.unseal(2,row['payload'])
  with self.assertRaises(ValueError):oauth.finish(app.connect,self.session,query['state'][0],'test-code',post=post)
 def test_state_is_session_bound_and_expires(self):
  query=self.begin();state=query['state'][0]
  for wrong in [{'user_id':2,'token_hash':'test-session'},{'user_id':1,'token_hash':'other'}]:
   with self.assertRaises(ValueError):oauth.finish(app.connect,wrong,state,'code')
  with app.connect() as c:c.execute('UPDATE oauth_flows SET expires=0')
  with self.assertRaises(ValueError):oauth.finish(app.connect,self.session,state,'code')
 def test_scope_escalation_and_denial(self):
  query=self.begin()
  with self.assertRaises(ValueError):oauth.finish(app.connect,self.session,query['state'][0],'code',post=lambda *a,**k:{'access_token':'test','token_type':'bearer','expires_in':100,'scope':'portfolio:read trading:write'})
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM oauth_tokens').fetchone()[0],0)
  query=self.begin()
  with self.assertRaises(ValueError):oauth.finish(app.connect,self.session,query['state'][0],'',error='access_denied')
 def test_dynamic_registration_is_explicit_and_reused(self):
  os.environ['PLUTO_CLIENT_ID']='';self.metadata['oauth']['registration_endpoint']='https://mcp.prod.pluto.markets/register';calls=[]
  def post(url,data):calls.append(data);return {'client_id':'dynamic-test','token_endpoint_auth_method':'none'}
  oauth.start(app.connect,self.session,self.metadata,post);oauth.start(app.connect,self.session,self.metadata,post)
  self.assertEqual(len(calls),1);self.assertEqual(calls[0]['redirect_uris'],['https://escape.example.org/api/pluto/callback'])
 def test_config_guards_and_tamper(self):
  os.environ['PLUTO_READ_SCOPES']='trading:write'
  with self.assertRaises(oauth.SetupRequired):oauth.start(app.connect,self.session,self.metadata)
  token=oauth.seal(1,{'secret':'test'});damaged=token[:-1]+bytes([token[-1]^1])
  with self.assertRaises(Exception):oauth.unseal(1,damaged)
 def test_revoke_preserves_on_failure(self):
  query=self.begin();oauth.finish(app.connect,self.session,query['state'][0],'code',post=lambda *a,**k:{'access_token':'test','token_type':'bearer','expires_in':100})
  def failed(*a):raise OSError('provider failed')
  with self.assertRaises(OSError):oauth.revoke(app.connect,1,failed)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM oauth_tokens').fetchone()[0],1)
  oauth.revoke(app.connect,1,lambda *a:None)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM oauth_tokens').fetchone()[0],0)

 def test_wsgi_callback_receives_query_and_session(self):
  import io
  import passenger_wsgi
  query=self.begin();state=query['state'][0]
  # A real database session is required, not a caller-supplied user id.
  cookie='test-session-cookie'
  with app.connect() as c:
   c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(app.token_hash(cookie),1,'csrf',time.time()+100))
   c.execute('UPDATE oauth_flows SET session_hash=?',(app.token_hash(cookie),))
  response={}
  def start(status,headers):response.update(status=status,headers=dict(headers))
  fake={'access_token':'test-access','token_type':'bearer','expires_in':300}
  with patch('oauth.post_json',return_value=fake):
   passenger_wsgi.application({'PATH_INFO':'/api/pluto/callback','QUERY_STRING':'state='+state+'&code=test-code','REQUEST_METHOD':'GET','HTTP_COOKIE':'escape='+cookie,'wsgi.input':io.BytesIO()},start)
  self.assertTrue(response['status'].startswith('303'));self.assertEqual(response['headers']['Location'],'/?pluto=connected')
