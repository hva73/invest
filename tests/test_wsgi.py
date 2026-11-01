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
