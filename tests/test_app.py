import unittest,tempfile,threading,json,http.client,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
class Workflow(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DB=self.tmp.name+'/test.db';app.init();app.create_user('test-password-long-enough');app.SESSIONS.clear();app.LOGIN_FAILURES.clear();self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.cookie='';self.csrf=''
 def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
 def request(self,path,data=None,csrf=True):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);headers={'Content-Type':'application/json','Cookie':self.cookie}
  if csrf:headers['X-CSRF-Token']=self.csrf
  c.request('POST' if data is not None else 'GET','/api/'+path,json.dumps(data) if data is not None else None,headers);r=c.getresponse();body=json.loads(r.read());cookie=r.getheader('Set-Cookie')
  if cookie:self.cookie=cookie.split(';')[0]
  status=r.status;c.close();return status,body
 def login(self):
  self.assertEqual(self.request('login',{'password':'test-password-long-enough'})[0],200);self.csrf=self.request('session')[1]['csrf']
 def test_protected_workflow(self):
  self.assertEqual(self.request('state')[0],401);self.login()
  p={'portfolio':'ESCAPE AI Trader','ticker':'TEST','quantity':2,'price':100,'stop':90,'target':120,'costs':5,'fx':7}
  self.assertEqual(self.request('proposals',p,False)[0],403)
  self.assertEqual(self.request('proposals',p)[0],201)
  state=self.request('state')[1];self.assertEqual(len(state['proposals']),1);self.assertEqual(state['proposals'][0]['status'],'Forslag')
  self.assertEqual(self.request('approve',{'id':1})[0],200);self.assertEqual(self.request('approve',{'id':1})[0],400)
  state=self.request('state')[1];self.assertEqual(len(state['journal']),2);self.assertEqual(state['proposals'][0]['status'],'Godkendt lokalt');self.assertTrue(all(v=='Ikke tilsluttet' for v in state['integrations'].values()))
  self.assertEqual(self.request('logout',{})[0],200);self.assertEqual(self.request('state')[0],401)
 def test_invalid_values_and_persistence(self):
  self.login();p={'portfolio':'Hovedportefølje','ticker':'TEST','quantity':1,'price':100,'stop':110,'target':120,'costs':0,'fx':1}
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
