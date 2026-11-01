"""Synthetic OAuth/MCP integration; no external service or broker calls."""
import base64,hashlib,http.client,json,os,secrets,tempfile,threading,time,unittest
from urllib.parse import urlencode,urlsplit,parse_qs
from unittest.mock import patch
from pathlib import Path
import app,mcp_reports,report_ingest

BASE='https://escape.example'
REDIRECT='https://client.example/oauth/callback'
class McpReports(unittest.TestCase):
 def setUp(self):
  self.previous=app.DB;self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/db'
  self.env=patch.dict(os.environ,{'ESCAPE_MCP_ENABLED':'1','ESCAPE_PUBLIC_URL':BASE,'ESCAPE_MCP_REDIRECT_URIS':REDIRECT});self.env.start()
  app.init();app.create_user('test-password-long-enough')
  self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start()
  self.sample=json.loads((Path(__file__).resolve().parents[1]/'examples/report-ingest-test.json').read_text())
 def tearDown(self):self.server.shutdown();self.server.server_close();self.env.stop();app.DB=self.previous;self.tmp.cleanup()
 def request(self,path,data=None,headers=None,method=None,form=False):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
  body=(urlencode(data) if form else json.dumps(data)).encode() if data is not None else None
  h={'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json',**(headers or {})}
  c.request(method or ('POST' if data is not None else 'GET'),path,body,h);r=c.getresponse();raw=r.read();status=r.status;out=dict(r.getheaders());c.close()
  return status,json.loads(raw) if raw else None,out
 def login(self):
  status,_,headers=self.request('/api/login',{'username':'owner','password':'test-password-long-enough'});self.assertEqual(status,200)
  cookie=headers['Set-Cookie'].split(';')[0]
  _,s,_=self.request('/api/session',headers={'Cookie':cookie})
  return {'Cookie':cookie,'X-CSRF-Token':s['csrf']}
 def registered(self):
  status,client,_=self.request('/oauth/register',{'redirect_uris':[REDIRECT],'token_endpoint_auth_method':'none'})
  self.assertEqual(status,201);return client['client_id']
 def pending(self,client,scope='reports:read reports:write'):
  verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
  p={'client_id':client,'redirect_uri':REDIRECT,'response_type':'code','state':'test-state','scope':scope,'resource':BASE+'/mcp','code_challenge_method':'S256','code_challenge':challenge}
  status,_,headers=self.request('/oauth/authorize?'+urlencode(p));self.assertEqual(status,303)
  rid=parse_qs(urlsplit(headers['Location']).query)['mcp_request'][0]
  return rid,verifier
 def granted(self,scope='reports:read reports:write'):
  client=self.registered();rid,verifier=self.pending(client,scope);headers=self.login()
  status,_,_=self.request('/api/mcp/consent?request_id='+rid,headers=headers);self.assertEqual(status,200)
  status,result,_=self.request('/api/mcp/consent',{'request_id':rid,'approve':True},headers);self.assertEqual(status,200)
  code=parse_qs(urlsplit(result['redirect_url']).query)['code'][0]
  params={'grant_type':'authorization_code','client_id':client,'redirect_uri':REDIRECT,'resource':BASE+'/mcp','code':code,'code_verifier':verifier}
  status,tokens,_=self.request('/oauth/token',params,form=True);self.assertEqual(status,200,(status,tokens))
  return client,tokens,params
 def call(self,token,name,args):return self.request('/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}},{'Authorization':'Bearer '+token})
 def test_metadata_requires_config_and_exact_redirect(self):
  status,meta,_=self.request('/.well-known/oauth-protected-resource/mcp');self.assertEqual(status,200);self.assertEqual(meta['resource'],BASE+'/mcp')
  self.assertEqual(self.request('/oauth/register',{'redirect_uris':['https://evil.example/callback']})[0],400)
  with patch.dict(os.environ,{'ESCAPE_MCP_ENABLED':'0'}):self.assertEqual(self.request('/mcp')[0],503)
 def test_http_report_flow_and_modes(self):
  _,tokens,_=self.granted();auth={'Authorization':'Bearer '+tokens['access_token']}
  status,result,_=self.request('/mcp',{'jsonrpc':'2.0','id':0,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'Test','version':'1'}}},auth)
  self.assertEqual(result['result']['protocolVersion'],'2025-06-18')
  self.assertEqual(self.request('/mcp',{'jsonrpc':'2.0','method':'notifications/initialized'},auth)[0],202)
  status,result,_=self.request('/mcp',{'jsonrpc':'2.0','id':2,'method':'tools/list'},auth)
  self.assertEqual({x['name'] for x in result['result']['tools']},{'send_report','get_latest_report'})
  status,result,_=self.call(tokens['access_token'],'send_report',self.sample);self.assertFalse(result['result']['isError'])
  self.assertTrue(self.call(tokens['access_token'],'send_report',self.sample)[1]['result']['structuredContent']['duplicate'])
  self.assertIsNone(self.call(tokens['access_token'],'get_latest_report',{})[1]['result']['structuredContent']['report'])
  saved=self.call(tokens['access_token'],'get_latest_report',{'is_test':True})[1]['result']['structuredContent']['report']
  self.assertEqual(saved['data'],self.sample)
  self.assertIsNone(report_ingest.latest(app.connect,999,True)['report'])
  real=dict(self.sample,report_id='production-test-fixture',is_test=False)
  self.assertEqual(report_ingest.save(app.connect,1,real)[0],201)
  self.assertEqual(report_ingest.latest(app.connect,1)['report']['data']['report_id'],'production-test-fixture')
  self.assertEqual(report_ingest.latest(app.connect,1,True)['report']['data']['report_id'],self.sample['report_id'])
  conflict=dict(self.sample,source='changed');self.assertTrue(self.call(tokens['access_token'],'send_report',conflict)[1]['result']['isError'])
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0],0)
   hashes=[r['hash'] for r in c.execute('SELECT hash FROM mcp_tokens')]
   self.assertNotIn(tokens['access_token'],hashes);self.assertNotIn(tokens['refresh_token'],hashes)
 def test_pkce_replay_and_refresh_rotation_revokes_reuse(self):
  client,tokens,params=self.granted()
  self.assertEqual(self.request('/oauth/token',params,form=True)[0],400)
  refresh={'grant_type':'refresh_token','client_id':client,'resource':BASE+'/mcp','refresh_token':tokens['refresh_token']}
  status,new,_=self.request('/oauth/token',refresh,form=True);self.assertEqual(status,200)
  self.assertNotEqual(tokens['access_token'],new['access_token'])
  self.assertEqual(self.request('/oauth/token',refresh,form=True)[0],400)
  self.assertEqual(self.call(new['access_token'],'get_latest_report',{})[0],401)
 def test_pkce_client_and_resource_binding(self):
  client=self.registered();rid,verifier=self.pending(client);headers=self.login()
  status,result,_=self.request('/api/mcp/consent',{'request_id':rid,'approve':True},headers)
  code=parse_qs(urlsplit(result['redirect_url']).query)['code'][0]
  p={'grant_type':'authorization_code','client_id':client,'redirect_uri':REDIRECT,'resource':BASE+'/mcp','code':code,'code_verifier':'x'*64}
  self.assertEqual(self.request('/oauth/token',p,form=True)[0],400)
  p['code_verifier']=verifier;p['resource']='https://foreign.example/mcp';self.assertEqual(self.request('/oauth/token',p,form=True)[0],400)
  p['resource']=BASE+'/mcp';p['client_id']='foreign';self.assertEqual(self.request('/oauth/token',p,form=True)[0],400)
  p['client_id']=client;self.assertEqual(self.request('/oauth/token',p,form=True)[0],200)
 def test_scope_csrf_and_revocation(self):
  _,tokens,_=self.granted('reports:read')
  self.assertIn('error',self.call(tokens['access_token'],'send_report',self.sample)[1])
  headers=self.login();self.assertEqual(self.request('/api/mcp/connections',{'revoke_all':True},{'Cookie':headers['Cookie']})[0],403)
  self.assertEqual(self.request('/api/mcp/connections',{'revoke_all':True},headers)[0],200)
  self.assertEqual(self.call(tokens['access_token'],'get_latest_report',{})[0],401)
 def test_auth_origin_and_expiry(self):
  status,_,headers=self.request('/mcp');self.assertEqual(status,401);self.assertIn('resource_metadata',headers['WWW-Authenticate'])
  _,tokens,_=self.granted()
  self.assertEqual(self.request('/mcp',{'jsonrpc':'2.0','id':1,'method':'ping'},{'Authorization':'Bearer '+tokens['access_token'],'Origin':'https://evil.example'})[0],403)
  with app.connect() as c:c.execute("UPDATE mcp_tokens SET expires=0 WHERE kind='access'")
  self.assertEqual(self.call(tokens['access_token'],'get_latest_report',{})[0],401)
 def test_deny_consent_and_expired_request(self):
  client=self.registered();rid,_=self.pending(client);headers=self.login()
  _,result,_=self.request('/api/mcp/consent',{'request_id':rid,'approve':False},headers)
  self.assertEqual(parse_qs(urlsplit(result['redirect_url']).query)['error'],['access_denied'])
  self.assertEqual(self.request('/api/mcp/consent',{'request_id':rid,'approve':True},headers)[0],400)
  rid,_=self.pending(client)
  with app.connect() as c:c.execute('UPDATE mcp_requests SET expires=0')
  self.assertEqual(self.request('/api/mcp/consent?request_id='+rid,headers=headers)[0],400)
 def test_real_users_cannot_read_or_claim_each_others_reports(self):
  import sqlite3
  with app.connect() as c:
   owner=c.execute('SELECT * FROM users WHERE id=1').fetchone()
   c.execute("INSERT INTO users(username,salt,hash,role,active) VALUES(?,?,?,'member',1)",('member',owner['salt'],owner['hash']))
  client=self.registered();rid,_=self.pending(client);headers=self.login()
  self.assertEqual(self.request('/api/mcp/consent?request_id='+rid,headers=headers)[0],200)
  status,_,result=self.request('/api/login',{'username':'member','password':'test-password-long-enough'})
  self.assertEqual(status,200)
  cookie=result['Set-Cookie'].split(';')[0];_,session,_=self.request('/api/session',headers={'Cookie':cookie})
  member={'Cookie':cookie,'X-CSRF-Token':session['csrf']}
  self.assertEqual(self.request('/api/mcp/consent',{'request_id':rid,'approve':True},member)[0],400)
  report_ingest.save(app.connect,1,self.sample)
  self.assertIsNone(self.request('/api/reports/latest?is_test=true',headers=member)[1]['report'])
  with app.connect() as c:grant_count=c.execute('SELECT COUNT(*) FROM mcp_grants').fetchone()[0]
  self.assertEqual(grant_count,0)
 def test_report_migration_preserves_existing_test_and_real_data(self):
  import sqlite3
  path=self.tmp.name+'/legacy'
  def connection():
   c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
  with connection() as c:
   c.execute('CREATE TABLE ingested_reports(id INTEGER PRIMARY KEY,user_id INTEGER,report_id TEXT,received TEXT,payload TEXT,digest TEXT,UNIQUE(user_id,report_id))')
   for index,flag in enumerate([True,False],1):
    data=dict(self.sample,is_test=flag,report_id='legacy-'+str(index))
    c.execute('INSERT INTO ingested_reports VALUES(?,?,?,?,?,?)',(index,1,data['report_id'],'test-time',json.dumps(data),'unused'))
   report_ingest.init(c)
  self.assertTrue(report_ingest.latest(connection,1,True)['report']['data']['is_test'])
  self.assertFalse(report_ingest.latest(connection,1)['report']['data']['is_test'])
 def test_registration_diagnostic_is_admin_only_and_never_authorizes(self):
  callback='https://chatgpt.com/observed-callback'
  self.assertEqual(self.request('/oauth/register',{'redirect_uris':[callback,'https://attacker.example/secret-path?token=private','https://chatgpt.com/callback?code=private'],'client_secret':'private'})[0],400)
  headers=self.login();status,result,_=self.request('/api/mcp/connections',headers=headers)
  self.assertEqual(status,200)
  diagnostic=result['registration_diagnostic']
  self.assertEqual(diagnostic['redirect_uris'],[callback])
  self.assertIn('attacker.example',diagnostic['other_hosts'])
  self.assertNotIn('private',json.dumps(diagnostic))
  self.assertFalse(mcp_reports.redirect_allowed(callback))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT COUNT(*) FROM mcp_clients').fetchone()[0],0)
   owner=c.execute('SELECT * FROM users WHERE id=1').fetchone()
   c.execute("INSERT INTO users(username,salt,hash,role,active) VALUES(?,?,?,'member',1)",('member',owner['salt'],owner['hash']))
  _,_,login=self.request('/api/login',{'username':'member','password':'test-password-long-enough'})
  status,result,_=self.request('/api/mcp/connections',headers={'Cookie':login['Set-Cookie'].split(';')[0]})
  self.assertEqual(status,200);self.assertNotIn('registration_diagnostic',result)
