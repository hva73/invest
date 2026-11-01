import io,json,os,tempfile,unittest
import app
class WSGITest(unittest.TestCase):
 def test_wsgi_health_and_login(self):
  with tempfile.TemporaryDirectory() as d:
   app.DB=d+'/wsgi.db'
   import passenger_wsgi as w
   app.init();app.create_user('a-private-test-password')
   def request(path,data=None,cookie=''):
    body=json.dumps(data).encode() if data else b'';headers=[]
    result=b''.join(w.application({'PATH_INFO':path,'REQUEST_METHOD':'POST' if data else 'GET','REMOTE_ADDR':'test','CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),'HTTP_COOKIE':cookie},lambda status,h:headers.extend([status,h])))
    return headers,json.loads(result)
   self.assertEqual(request('/api/health')[1]['status'],'ok')
   self.assertTrue(request('/api/state')[0][0].startswith('401'))
   h,b=request('/api/login',{'password':'a-private-test-password'})
   self.assertTrue(h[0].startswith('200'))
   cookie=next(v for k,v in h[1] if k=='Set-Cookie');self.assertIn('Secure',cookie)
   self.assertTrue(request('/api/session',cookie=cookie.split(';')[0])[1]['authenticated'])

 def test_report_content_type_from_wsgi_environment(self):
  from unittest.mock import patch
  from pathlib import Path
  import passenger_wsgi as w
  previous=app.DB
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ESCAPE_REPORT_INGEST_KEY':'test-secret-'+'x'*40,'ESCAPE_REPORT_INGEST_USER':'owner'}):
   try:
    app.DB=d+'/reports.db';app.init();app.create_user('a-private-test-password')
    data=(Path(__file__).resolve().parents[1]/'examples/report-ingest-test.json').read_bytes()
    def send(content_type):
     response=[]
     env={'PATH_INFO':'/api/reports/ingest','REQUEST_METHOD':'POST','REMOTE_ADDR':'test','CONTENT_LENGTH':str(len(data)),'wsgi.input':io.BytesIO(data),'HTTP_AUTHORIZATION':'Bearer '+os.environ['ESCAPE_REPORT_INGEST_KEY']}
     if content_type:env['CONTENT_TYPE']=content_type
     body=b''.join(w.application(env,lambda status,headers:response.append(status)))
     return response[0],json.loads(body)
    self.assertTrue(send(None)[0].startswith('415'))
    status,result=send('application/json; charset=utf-8')
    self.assertTrue(status.startswith('201'),(status,result))
    self.assertTrue(send('application/json')[1]['duplicate'])
   finally:app.DB=previous
