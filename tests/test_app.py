import unittest,tempfile,threading,json,http.client,sys,sqlite3
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
class Workflow(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/test.db';app.init();app.create_user('test-password-long-enough');
  import portfolios
  with app.connect() as c:portfolios.create(c,1,'Testkonto')
  app.SESSIONS.clear();app.LOGIN_FAILURES.clear();self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.cookie='';self.csrf=''
 def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
 def request(self,path,data=None,csrf=True):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);headers={'Content-Type':'application/json','Cookie':self.cookie}
  if csrf:headers['X-CSRF-Token']=self.csrf
  c.request('POST' if data is not None else 'GET','/api/'+path,json.dumps(data) if data is not None else None,headers);r=c.getresponse();body=json.loads(r.read());cookie=r.getheader('Set-Cookie')
  if cookie:self.cookie=cookie.split(';')[0]
  status=r.status;c.close();return status,body
 def login(self):
  self.assertEqual(self.request('login',{'password':'test-password-long-enough'})[0],200);self.csrf=self.request('session')[1]['csrf']
 def test_state_database_busy_returns_json_and_preserves_fallback_diagnosis(self):
  import hotwatch_supervisor
  self.login();original=app.connect
  def quick():
   c=original();c.execute('PRAGMA busy_timeout=25');return c
  holder=sqlite3.connect(app.DB)
  try:
   holder.execute('BEGIN EXCLUSIVE')
   with patch.object(app,'connect',side_effect=quick):
    status,body=self.request('state')
   self.assertEqual(status,503)
   self.assertIn('midlertidigt optaget',body['error'])
   log=hotwatch_supervisor.application_error_fallback()
   self.assertEqual(log['status'],'AVAILABLE')
   self.assertIn({'event':'site_state','code':1},[{k:r[k] for k in ('event','code')} for r in log['events']])
   self.assertTrue(any(r['event']=='site_sqlite_error' and r['code']==sqlite3.SQLITE_BUSY for r in log['events']))
  finally:holder.rollback();holder.close()
  self.assertEqual(self.request('state')[0],200)
 def test_state_projection_failure_is_logged_without_private_text(self):
  self.login()
  with patch('dashboard_projection.build',side_effect=ValueError('private account token')):
   status,body=self.request('state')
  self.assertEqual(status,500);self.assertNotIn('private',json.dumps(body))
  self.assertTrue(body['error_logged'])
  with app.connect() as c:
   rows=[dict(r) for r in c.execute('SELECT event,code FROM hw_supervisor_events')]
  self.assertIn({'event':'site_state','code':2},rows)
  self.assertNotIn('private',str(rows))
  with patch('dashboard_projection.build',side_effect=ValueError('private')),patch('hotwatch_supervisor.application_error',return_value=False):
   status,body=self.request('state')
  self.assertEqual(status,500);self.assertFalse(body['error_logged'])
  self.assertIn('Fejlloggen kunne heller ikke gemmes',body['error'])
 def test_protected_workflow(self):
  self.assertEqual(self.request('state')[0],401);self.login()
  p={'portfolio_id':1,'ticker':'TEST','quantity':2,'price':100,'stop':90,'target':120,'costs':5,'fx':7}
  self.assertEqual(self.request('proposals',p,False)[0],403)
  self.assertEqual(self.request('proposals',p)[0],201)
  state=self.request('state')[1];self.assertEqual(len(state['proposals']),1);self.assertEqual(state['proposals'][0]['status'],'Forslag')
  self.assertEqual(self.request('approve',{'id':1})[0],200);self.assertEqual(self.request('approve',{'id':1})[0],400)
  state=self.request('state')[1];self.assertEqual(len(state['journal']),2);self.assertEqual(state['proposals'][0]['status'],'Godkendt lokalt');self.assertTrue(all(v=='Ikke tilsluttet' for v in state['integrations'].values()))
  self.assertEqual(self.request('logout',{})[0],200);self.assertEqual(self.request('state')[0],401)
 def test_release_approval_requires_owner_session_csrf_and_exact_version(self):
  import release_approval
  self.assertEqual(self.request('admin/release-approval')[0],401)
  self.login()
  candidate=release_approval.prepare(app.connect,'a'*40,'Test version',1)
  self.assertEqual(self.request('admin/release-approval')[1]['candidate']['id'],candidate['id'])
  with app.connect() as c:
   c.execute("INSERT INTO users(username,salt,hash,role,active) VALUES('otheradmin',?,?,'admin',1)",('11'*16,app.password_hash('other-password-long-enough','11'*16)))
  owner_cookie,owner_csrf=self.cookie,self.csrf
  self.cookie='';self.assertEqual(self.request('login',{'username':'otheradmin','password':'other-password-long-enough'})[0],200);self.csrf=self.request('session')[1]['csrf']
  self.assertEqual(self.request('admin/release-approval')[0],403)
  self.assertEqual(self.request('admin/release-approval',{'id':candidate['id'],'sha':candidate['sha']})[0],403)
  self.cookie,self.csrf=owner_cookie,owner_csrf
  self.assertEqual(self.request('admin/release-approval',{'id':candidate['id'],'sha':candidate['sha']},False)[0],403)
  self.assertEqual(self.request('admin/release-approval',{'id':candidate['id'],'sha':'b'*40})[0],409)
  status,result=self.request('admin/release-approval',{'id':candidate['id'],'sha':candidate['sha']})
  self.assertEqual(status,200);self.assertEqual(result['status'],'approved');self.assertFalse(result['deployment_started'])
  self.assertEqual(self.request('admin/release-approval',{'id':candidate['id'],'sha':candidate['sha']})[0],409)
  self.assertEqual(release_approval.claim(app.connect,candidate['id'],candidate['sha'])['status'],'claimed')
  with self.assertRaisesRegex(ValueError,'approval_unavailable'):
   release_approval.claim(app.connect,candidate['id'],candidate['sha'])
 def test_release_notification_follows_displayed_candidate_when_candidate_changes(self):
  self.login()
  old={'id':'old','sha':'a'*40,'summary':'Old','status':'pending'}
  new={'id':'new','sha':'b'*40,'summary':'New'}
  with patch('release_approval.current',return_value=old),patch('release_approval.pending',return_value=new),patch('web_push.release_notification_status',return_value={'sent':2,'failed':0}) as status:
   code,body=self.request('admin/release-approval')
  self.assertEqual(code,200)
  self.assertEqual(body['candidate']['id'],'new')
  self.assertEqual(body['notification']['sent'],2)
  self.assertEqual(status.call_args.args[2],'new')
 def test_invalid_values_and_persistence(self):
  self.login();p={'portfolio_id':1,'ticker':'TEST','quantity':1,'price':100,'stop':110,'target':120,'costs':0,'fx':1}
  self.assertEqual(self.request('proposals',p)[0],400);p['stop']=90;p['price']=float('nan');self.assertEqual(self.request('proposals',p)[0],400)
  p['price']=100;self.assertEqual(self.request('proposals',p)[0],201);app.init();self.assertEqual(app.connect().execute('SELECT count(*) FROM proposals').fetchone()[0],1)
 def test_opportunities(self):
  data={'company':'Testfirma','ticker':'TEST','market':'Danmark','asset':'Aktier','headline':'Test af kildehenvisning','source_url':'https://example.com/source','published':'2020-01-01T12:00:00+00:00','classification':'Spekulation','catalyst':'Afventer dokumentation','risk':'Ukendt','next_action':'Læs originalkilden'}
  self.assertEqual(self.request('opportunities',data)[0],401);self.login()
  self.assertEqual(self.request('opportunities',data,False)[0],403)
  self.assertEqual(self.request('opportunities',data)[0],201)
  items=self.request('state')[1]['opportunities'];self.assertEqual(len(items),1);self.assertEqual(items[0]['headline'],data['headline'])
  for invalid in ['javascript:alert(1)','http://example.com','https://user:password@example.com']:
   data['source_url']=invalid;self.assertEqual(self.request('opportunities',data)[0],400)
  data['source_url']='https://example.com';data['published']='2020-01-01T12:00:00';self.assertEqual(self.request('opportunities',data)[0],400)
  app.init();self.assertEqual(len(self.request('state')[1]['opportunities']),1)
 def test_login_rate_limit(self):
  for _ in range(5):self.assertEqual(self.request('login',{'password':'wrong'})[0],401)
  self.assertEqual(self.request('login',{'password':'wrong'})[0],429)
if __name__=='__main__':unittest.main()
