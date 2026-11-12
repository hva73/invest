"""Anonymous demo resources are isolated from the real session and broker."""
import json
import threading
import unittest
import urllib.request
import app

class AnonymousDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()
    def get(self,path):
        with urllib.request.urlopen(self.url+path) as r:
            return r.read().decode(),r.headers
    def test_entry_and_isolation_policy(self):
        home,_=self.get('/')
        self.assertIn('href="/demo"',home)
        self.assertIn('id="login-form"',home)
        page,headers=self.get('/demo')
        for field in ("connect-src 'none'","form-action 'none'","worker-src 'none'"):
            self.assertIn(field,headers['Content-Security-Policy'])
        self.assertIn('DEMO · Fiktive data',page)
        self.assertIn('href="/"',page)
        self.assertIn('/demo-data.js',page)
        self.assertIn('/demo-app.js',page)
        self.assertNotIn('Set-Cookie',headers)
    def test_demo_uses_same_app_without_worker_or_real_push_read(self):
        script,_=self.get('/demo-app.js')
        self.assertNotIn("navigator.serviceWorker.register('/sw.js')",script)
        self.assertIn("const supported=false&&'serviceWorker'in navigator",script)
        self.assertIn('Simulér afsendelse',script)
        self.assertIn('Fiktiv kurs og graf',script)
        self.assertIn('Fiktiv kursserie',script)
        self.assertNotIn('Observeret Pluto-serie',script)
        self.assertIn('Ingen ordre er sendt.',script)
        self.assertNotIn('Forslaget er sendt til Pluto.',script)
        self.assertNotIn('Forslaget udfører ikke en handel. Endelig godkendelse sker hos Pluto.',script)
        self.assertNotIn('Sendt som forslag · afventer kontrol i Pluto',script)
        real,_=self.get('/app.js')
        self.assertIn("navigator.serviceWorker.register('/sw.js')",real)
    def test_fixture_and_mock_are_synthetic(self):
        data,_=self.get('/demo-data.js')
        prefix='window.ESCAPE_DEMO=true;window.ESCAPE_DEMO_DATA='
        self.assertTrue(data.startswith(prefix))
        fixture=json.loads(data[len(prefix):data.index(';\n')])
        self.assertEqual(fixture['state']['user'],{'username':'demo','role':'user'})
        self.assertFalse(fixture['state']['connection']['trade_access'])
        self.assertGreaterEqual(len(fixture['state']['dashboard']['positions']),3)
        self.assertTrue(all(p['asset_id'].startswith('synthetic-') for p in fixture['state']['dashboard']['positions']))
        self.assertIn('window.fetch=async',data)

if __name__=='__main__':unittest.main()
