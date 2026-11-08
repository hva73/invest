import base64,os,secrets,tempfile,time,unittest
from datetime import datetime,timezone
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import app,oauth,web_push,hotwatch_engine as engine

def b64(b):return base64.urlsafe_b64encode(b).decode().rstrip('=')
class Push(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=app.DB;app.DB=self.temp.name+'/db';self.env=patch.dict(os.environ,{'ESCAPE_TOKEN_KEY_FILE':self.temp.name+'/token.key','ESCAPE_PUSH_KEY_FILE':self.temp.name+'/push.pem','ESCAPE_PUBLIC_URL':'https://escape.example'},clear=False);self.env.start();app.init();app.create_user('test-password-long-enough');oauth.setup_key();web_push.setup_key()
  pub=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
  self.sub={'endpoint':'https://fcm.googleapis.com/fcm/send/synthetic-device','keys':{'p256dh':b64(pub),'auth':b64(secrets.token_bytes(16))}}
  self.now=datetime.now(timezone.utc)
  with app.connect() as c:
   c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,'synthetic-watch',0,'synthetic','test','ACTIVE','{}','hash','{\"version\":\"1.0.0\"}','{}',?,?,0)",(self.now.isoformat(),self.now.isoformat()))
   self.watch=c.execute("SELECT * FROM hw_sessions WHERE watch_id='synthetic-watch'").fetchone()
 def tearDown(self):self.env.stop();app.DB=self.old;self.temp.cleanup()
 def subscribe(self):web_push.subscribe(app.connect,1,{'subscription':self.sub,'buy':True,'sell':True})
 def event(self,kind):
  with app.connect() as c:engine.event(c,self.watch,kind,self.now,'synthetic')
 def test_subscription_is_encrypted_and_owner_scoped(self):
  self.subscribe()
  with app.connect() as c:
   row=c.execute('SELECT * FROM push_devices').fetchone();self.assertNotIn(self.sub['endpoint'].encode(),bytes(row['payload']))
   self.assertEqual(c.execute('SELECT count(*) FROM push_devices WHERE user_id=2').fetchone()[0],0)
  self.assertTrue(web_push.device_preferences(app.connect,1,self.sub['endpoint'])['subscribed'])
  self.assertFalse(web_push.device_preferences(app.connect,2,self.sub['endpoint'])['subscribed'])
  web_push.unsubscribe(app.connect,2,self.sub['endpoint']);self.assertTrue(web_push.device_preferences(app.connect,1,self.sub['endpoint'])['subscribed'])
 def test_only_supported_https_push_hosts(self):
  for endpoint in ['http://fcm.googleapis.com/abc','https://fcm.googleapis.com.evil.invalid/','https://127.0.0.1/','https://fcm.googleapis.com:444/']:
   with self.assertRaises(ValueError):web_push.validate_subscription({**self.sub,'endpoint':endpoint})
 def test_action_change_and_deduplication(self):
  self.subscribe();sent=[]
  self.event('BUY_SIGNAL')
  with patch('web_push._actionable',return_value='BUY'):self.assertTrue(web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p)))
  self.assertEqual(sent[0]['title'],'ESCAPE · købssignal');self.assertNotIn('synthetic-device',str(sent))
  self.event('BUY_SIGNAL')
  with patch('web_push._actionable',return_value='BUY'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),1)
  self.event('WAIT_SIGNAL')
  with patch('web_push._actionable',return_value=None):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),2);self.assertEqual(sent[1]['title'],'ESCAPE · signal ændret');self.assertEqual(sent[0]['tag'],sent[1]['tag'])
 def test_old_signal_is_never_announced(self):
  self.subscribe();self.event('BUY_SIGNAL');sent=[]
  with patch('web_push._actionable',return_value=None):web_push.dispatch_one(app.connect,self.now,lambda *args:sent.append(args))
  self.assertEqual(sent,[])
 def test_stale_signal_gets_replacement_without_new_event(self):
  self.subscribe();self.event('BUY_SIGNAL');sent=[]
  with patch('web_push._actionable',return_value='BUY'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  with patch('web_push._actionable',return_value=None):
   web_push.reconcile_stale(app.connect,self.now);web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(sent[-1]['title'],'ESCAPE · signal ændret')
 def test_expired_device_is_removed_and_retry_is_bounded(self):
  self.subscribe();self.event('BUY_SIGNAL')
  class Gone(Exception):
   response=type('Response',(),{'status_code':410})()
  def reject(*args):raise Gone()
  with patch('web_push._actionable',return_value='BUY'):web_push.dispatch_one(app.connect,self.now,reject)
  self.assertFalse(web_push.device_preferences(app.connect,1,self.sub['endpoint'])['subscribed'])
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM push_jobs').fetchone()[0],0)
 def test_disabled_buy_and_test_events_do_not_notify(self):
  web_push.subscribe(app.connect,1,{'subscription':self.sub,'buy':False,'sell':True});self.event('BUY_SIGNAL');sent=[]
  with patch('web_push._actionable',return_value='BUY'):web_push.dispatch_one(app.connect,self.now,lambda *args:sent.append(args))
  self.assertEqual(sent,[])
  with app.connect() as c:
   row=dict(self.watch);row['is_test']=1;web_push.enqueue(c,row,'SELL_SIGNAL','synthetic-test',self.now)
   self.assertEqual(c.execute("SELECT count(*) FROM push_jobs WHERE event_key='synthetic-test'").fetchone()[0],0)
 def test_webpush_uses_encryption_and_never_redirects(self):
  import requests
  response=requests.Response();response.status_code=201;seen=[]
  def post(session,url,**kwargs):seen.append((url,kwargs));return response
  with patch('requests.Session.post',new=post):web_push._send(self.sub,{'title':'syntetisk'},'escape-test')
  self.assertEqual(len(seen),1);self.assertFalse(seen[0][1]['allow_redirects']);self.assertNotIn(b'syntetisk',seen[0][1]['data'])
if __name__=='__main__':unittest.main()
