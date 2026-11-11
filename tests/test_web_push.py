import base64,json,os,secrets,tempfile,time,unittest
from datetime import datetime,timezone,timedelta
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
 def test_empty_push_queue_does_not_request_writer_lock(self):
  import sqlite3
  holder=app.connect()
  def quick_connect():
   c=sqlite3.connect(app.DB,timeout=0);c.row_factory=sqlite3.Row;return c
  try:
   holder.execute('BEGIN IMMEDIATE')
   self.assertFalse(web_push.dispatch_one(quick_connect,self.now))
  finally:holder.rollback();holder.close()
 def test_idle_preflight_still_expires_old_pending_jobs(self):
  self.subscribe();self.event('BUY_SIGNAL')
  with app.connect() as c:c.execute('UPDATE push_jobs SET created=?',(self.now.timestamp()-301,))
  self.assertFalse(web_push.dispatch_one(app.connect,self.now,lambda *args:self.fail('expired job sent')))
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM push_jobs').fetchone()['status'],'expired')
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
 def test_parallel_workers_serialize_same_device_and_watch(self):
  import threading
  self.subscribe();self.event('SELL_SIGNAL');self.event('SELL_SIGNAL')
  entered=threading.Event();release=threading.Event();sent=[];failures=[]
  def blocking_sender(sub,payload,tag):
   sent.append(payload);entered.set()
   if not release.wait(5):raise RuntimeError('test sender timed out')
  def worker():
   try:web_push.dispatch_one(app.connect,self.now,blocking_sender)
   except Exception as exc:failures.append(exc)
  with patch('web_push._actionable',return_value='SELL'):
   thread=threading.Thread(target=worker);thread.start()
   try:
    self.assertTrue(entered.wait(5));self.assertFalse(web_push.dispatch_one(app.connect,self.now,lambda *args:self.fail('parallel duplicate sent')))
   finally:release.set();thread.join(5)
   self.assertFalse(thread.is_alive());self.assertEqual(failures,[])
   self.assertTrue(web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p)))
  self.assertEqual(len(sent),1)
  with app.connect() as c:self.assertEqual([r['status'] for r in c.execute('SELECT status FROM push_jobs ORDER BY id')],['sent','skipped'])
 def test_failed_send_retries_and_later_duplicate_is_suppressed(self):
  self.subscribe();self.event('SELL_SIGNAL');sent=[];attempts=[]
  def fail_once(*args):attempts.append(1);raise RuntimeError('temporary network error')
  with patch('web_push._actionable',return_value='SELL'):
   self.assertTrue(web_push.dispatch_one(app.connect,self.now,fail_once))
   self.assertTrue(web_push.dispatch_one(app.connect,self.now+timedelta(seconds=4),lambda s,p,t:sent.append(p)))
   self.event('SELL_SIGNAL')
   self.assertTrue(web_push.dispatch_one(app.connect,self.now+timedelta(seconds=5),lambda s,p,t:sent.append(p)))
  self.assertEqual(len(attempts),1);self.assertEqual(len(sent),1)
  with app.connect() as c:self.assertEqual([r['status'] for r in c.execute('SELECT status FROM push_jobs ORDER BY id')],['sent','skipped'])
 def test_separate_watches_are_not_suppressed_on_same_device(self):
  self.subscribe();self.event('SELL_SIGNAL');sent=[]
  with app.connect() as c:
   c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,'second-watch',0,'other','other-depot','ACTIVE','{}','hash','{\"version\":\"1.0.0\"}','{}',?,?,0)",(self.now.isoformat(),self.now.isoformat()))
   other=c.execute("SELECT * FROM hw_sessions WHERE watch_id='second-watch'").fetchone();engine.event(c,other,'SELL_SIGNAL',self.now,'synthetic')
  with patch('web_push._actionable',return_value='SELL'):
   web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
   web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual({p['watch_id'] for p in sent},{'synthetic-watch','second-watch'})
 def test_old_signal_is_never_announced(self):
  self.subscribe();self.event('BUY_SIGNAL');sent=[]
  with patch('web_push._actionable',return_value=None):web_push.dispatch_one(app.connect,self.now,lambda *args:sent.append(args))
  self.assertEqual(sent,[])
 def test_sell_message_names_ticker_and_reason(self):
  self.subscribe();sent=[]
  with app.connect() as c:
   c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps({'ticker':'JDZG'}),self.watch['id']))
   c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],self.now.isoformat(),json.dumps({'reason_codes':['TRAILING_EXIT']}),'x'))
  self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(sent[0]['title'],'JDZG · salgssignal')
  self.assertIn('Trailing-exit',sent[0]['body'])
  self.assertEqual(sent[0]['watch_id'],'synthetic-watch')
 def test_sell_wait_nodata_sell_does_not_repeat(self):
  self.subscribe();sent=[]
  self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  for kind in ('WAIT_SIGNAL','NO_DATA'):
   self.event(kind)
   with patch('web_push._actionable',return_value=None):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),1)
 def test_new_verified_exit_after_recovery_notifies_again(self):
  self.subscribe();sent=[];self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  recovery={'signal':'WAIT','reason_codes':['NO_TRIGGER'],'new_market_observation':True,'position_context':{'position':'held'},'risk_level':'normal'}
  with app.connect() as c:c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],(self.now+timedelta(seconds=1)).isoformat(),json.dumps(recovery),'x'))
  at=self.now+timedelta(seconds=2)
  with app.connect() as c:engine.event(c,self.watch,'SELL_SIGNAL',at,'new exit after recovery')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,at,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),2)
 def test_critical_stop_and_worsening_notify_even_during_sell(self):
  self.subscribe();sent=[];self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):
   web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
   with app.connect() as c:engine.event(c,self.watch,'RISK_REJECTION',self.now,'STOP_BREACHED',severity='critical')
   web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
   with app.connect() as c:engine.event(c,self.watch,'TRAILING_EXIT_WORSENED',self.now,'worsened',severity='warning')
   web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),3)
 def test_repeated_stop_episode_is_suppressed_but_changed_stop_is_not(self):
  self.subscribe();sent=[]
  def critical(offset,stop):
   at=self.now+timedelta(seconds=offset)
   with app.connect() as c:
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps({'risk_parameters':{'stop_price':stop},'position_context':{'position':'held','status':'verified','quantity':'10'},'supporting_metrics':{'price':'9'},'reason_codes':['STOP_BREACHED']}),'x'))
    engine.event(c,self.watch,'RISK_REJECTION',at,'STOP_BREACHED',severity='critical')
   with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,at,lambda s,p,t:sent.append(p))
  critical(0,'10');critical(1,'10');critical(2,'11')
  self.assertEqual(len(sent),2)
  with app.connect() as c:self.assertEqual([r['status'] for r in c.execute('SELECT status FROM push_jobs ORDER BY id')],['sent','skipped','sent'])
 def test_changed_position_and_price_notify_each_device(self):
  self.subscribe();web_push.subscribe(app.connect,1,{'subscription':{**self.sub,'endpoint':self.sub['endpoint']+'-second'},'buy':True,'sell':True});sent=[]
  def critical(offset,quantity,price):
   at=self.now+timedelta(seconds=offset)
   payload={'risk_parameters':{'stop_price':'10'},'position_context':{'position':'held','status':'verified','quantity':quantity},'supporting_metrics':{'price':price}}
   with app.connect() as c:
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),'x'))
    engine.event(c,self.watch,'RISK_REJECTION',at,'STOP_BREACHED',severity='critical')
   with patch('web_push._actionable',return_value='SELL'):
    for _ in range(2):web_push.dispatch_one(app.connect,at,lambda s,p,t:sent.append(s['endpoint']))
  critical(0,'10','9');critical(1,'10','9');critical(2,'20','9');critical(3,'20','8')
  self.assertEqual(len(sent),6)
  self.assertEqual(sent.count(self.sub['endpoint']),3)
  self.assertEqual(sent.count(self.sub['endpoint']+'-second'),3)
 def test_queued_duplicate_critical_jobs_are_deduplicated_per_device(self):
  self.subscribe();web_push.subscribe(app.connect,1,{'subscription':{**self.sub,'endpoint':self.sub['endpoint']+'-second'},'buy':True,'sell':True});sent=[]
  for offset in range(2):
   at=self.now+timedelta(seconds=offset)
   payload={'risk_parameters':{'stop_price':'10'},'position_context':{'position':'held','status':'verified','quantity':'10'},'supporting_metrics':{'price':'9'}}
   with app.connect() as c:
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),'x'))
    engine.event(c,self.watch,'RISK_REJECTION',at,'STOP_BREACHED',severity='critical')
  with patch('web_push._actionable',return_value='SELL'):
   for _ in range(4):self.assertTrue(web_push.dispatch_one(app.connect,self.now+timedelta(seconds=2),lambda sub,p,t:sent.append(sub['endpoint'])))
  self.assertEqual(sorted(sent),sorted([self.sub['endpoint'],self.sub['endpoint']+'-second']))
  with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM push_jobs WHERE status='skipped'").fetchone()[0],2)
 def test_small_ticks_do_not_repeat_critical_or_trailing_push(self):
  self.subscribe();sent=[];strategy={'version':'1.0.0','parameters':{'trailing_pct':'2'}};digest=engine.checksum(strategy)
  with app.connect() as c:c.execute('UPDATE hw_sessions SET strategy=? WHERE id=?',(json.dumps(strategy),self.watch['id']))
  def event(offset,kind,price):
   at=self.now+timedelta(seconds=offset)
   payload={'risk_parameters':{'stop_price':'10.0' if offset%2 else '10'},'position_context':{'position':'held','status':'verified','quantity':'10.00' if offset%2 else '10','portfolio_equity_dkk':str(10000+offset),'exposure_dkk':str(1000+offset)},'supporting_metrics':{'price':price}}
   with app.connect() as c:
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),digest))
    row=c.execute('SELECT * FROM hw_sessions WHERE id=?',(self.watch['id'],)).fetchone()
    engine.event(c,row,kind,at,'STOP_BREACHED' if kind=='RISK_REJECTION' else 'worsened',severity='critical' if kind=='RISK_REJECTION' else 'warning')
   with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,at,lambda s,p,t:sent.append(p))
  for i,price in enumerate(('9.000','8.999','8.998','8.990','8.820')):event(i,'RISK_REJECTION',price)
  self.assertEqual(len(sent),2,'Only the first stop and a 2% worsening notify')
  for i,price in enumerate(('9.000','8.999','8.990','8.820'),10):event(i,'TRAILING_EXIT_WORSENED',price)
  self.assertEqual(len(sent),4,'Trailing notifications also require a configured-distance worsening')
 def test_deadline_change_in_position_is_not_suppressed(self):
  self.subscribe();sent=[]
  for offset,quantity in enumerate(('10','10','20')):
   at=self.now+timedelta(seconds=offset)
   payload={'risk_parameters':{'exit_deadline':'2026-11-10T20:00:00Z'},'position_context':{'position':'held','status':'verified','quantity':quantity},'supporting_metrics':{'price':'9'}}
   with app.connect() as c:
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),'x'))
    engine.event(c,self.watch,'RISK_REJECTION',at,'EXIT_DEADLINE',severity='critical')
   with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,at,lambda sub,p,t:sent.append(p))
  self.assertEqual(len(sent),2)
 def test_duplicate_trailing_only_suppressed_when_evidence_unchanged(self):
  self.subscribe();sent=[]
  def event(offset,price,quantity='10',complete=True):
   at=self.now+timedelta(seconds=offset)
   payload={'risk_parameters':{'trailing_pct':'2'},'position_context':{'position':'held','status':'verified','quantity':quantity},'supporting_metrics':{'price':price}}
   if not complete:payload.pop('position_context')
   with app.connect() as c:
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),'x'))
    engine.event(c,self.watch,'TRAILING_EXIT_WORSENED',at,'worsened',severity='warning')
   with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,at,lambda s,p,t:sent.append(p))
  event(0,'10');event(1,'10');event(2,'9');event(3,'9','20');event(4,'9','20',False)
  self.assertEqual(len(sent),4)
  with app.connect() as c:self.assertEqual([r['status'] for r in c.execute('SELECT status FROM push_jobs ORDER BY id')],['sent','skipped','sent','sent','sent'])
 def test_unknown_stop_level_does_not_hide_critical_alert(self):
  self.subscribe();sent=[]
  with patch('web_push._actionable',return_value='SELL'):
   for offset in range(2):
    at=self.now+timedelta(seconds=offset)
    with app.connect() as c:engine.event(c,self.watch,'RISK_REJECTION',at,'STOP_BREACHED',severity='critical')
    web_push.dispatch_one(app.connect,at,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),2)
 def test_new_stop_after_verified_recovery_is_not_suppressed(self):
  self.subscribe();sent=[]
  def critical(offset):
   at=self.now+timedelta(seconds=offset)
   with app.connect() as c:
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps({'risk_parameters':{'stop_price':'10'},'position_context':{'position':'held','status':'verified','quantity':'10'},'supporting_metrics':{'price':'9'}}),'x'))
    engine.event(c,self.watch,'RISK_REJECTION',at,'STOP_BREACHED',severity='critical')
   with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,at,lambda s,p,t:sent.append(p))
  critical(0)
  recovery={'signal':'WAIT','reason_codes':['NO_TRIGGER'],'new_market_observation':True,'position_context':{'position':'held'},'risk_level':'normal','risk_parameters':{'stop_price':'10'}}
  with app.connect() as c:c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],(self.now+timedelta(seconds=1)).isoformat(),json.dumps(recovery),'x'))
  critical(2);self.assertEqual(len(sent),2)
 def test_new_verified_position_basis_rearms_exit_without_duplicate_pushes(self):
  with app.connect() as c:
   engine.event(c,self.watch,'SELL_SIGNAL',self.now,'first cycle')
   event=c.execute("SELECT event_id FROM hw_events WHERE watch_row_id=? AND event_type='SELL_SIGNAL' ORDER BY id DESC LIMIT 1",(self.watch['id'],)).fetchone()['event_id']
   def calc(at,basis):
    result={'signal':'WAIT','reason_codes':['CONFIRMATION_PENDING'],'new_market_observation':True,'position_trailing':{'status':'VERIFIED','basis':basis},'position_context':{'position':'held','status':'verified','as_of':at.isoformat()}}
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(result),'x'))
   calc(self.now,'cycle-one');calc(self.now+timedelta(seconds=1),'cycle-one')
   self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   calc(self.now+timedelta(seconds=2),'cycle-two')
   self.assertTrue(web_push._exit_rearmed(c,self.watch['id'],event))
 def test_new_evidence_alone_does_not_prove_a_new_exit_episode(self):
  with app.connect() as c:
   engine.event(c,self.watch,'SELL_SIGNAL',self.now,'first exit with no verified cycle')
   event=c.execute("SELECT event_id FROM hw_events WHERE watch_row_id=? AND event_type='SELL_SIGNAL' ORDER BY id DESC LIMIT 1",(self.watch['id'],)).fetchone()['event_id']
   original={'signal':'SELL','reason_codes':['STOP_BREACHED'],'position_trailing':None}
   current={'signal':'WAIT','reason_codes':['CONFIRMATION_PENDING'],'new_market_observation':True,'position_trailing':{'status':'VERIFIED','basis':'same-position-possibly'}}
   for at,payload in ((self.now,original),(self.now+timedelta(seconds=1),current)):
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),'x'))
   self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
 def test_changed_verified_exposure_rearms_exit_without_complete_fill_history(self):
  with app.connect() as c:
   engine.event(c,self.watch,'SELL_SIGNAL',self.now,'previous exposure')
   event=c.execute("SELECT event_id FROM hw_events WHERE watch_row_id=? AND event_type='SELL_SIGNAL' ORDER BY id DESC LIMIT 1",(self.watch['id'],)).fetchone()['event_id']
   def calc(offset,key,status='verified'):
    payload={'signal':'WAIT','reason_codes':['CONFIRMATION_PENDING'],'new_market_observation':True,'exit_context_key':key,'position_context':{'position':'held','status':status,'as_of':(self.now+timedelta(seconds=offset)).isoformat()},'risk_level':'normal'}
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],(self.now+timedelta(seconds=offset)).isoformat(),json.dumps(payload),'x'))
   calc(0,'exposure-one');calc(1,'exposure-one');self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   calc(2,'exposure-two','unknown');self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   calc(3,'exposure-two');self.assertTrue(web_push._exit_rearmed(c,self.watch['id'],event))
 def test_critical_stop_is_reported_when_data_is_temporarily_unavailable(self):
  self.subscribe();sent=[];self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  with app.connect() as c:engine.event(c,self.watch,'RISK_REJECTION',self.now,'STOP_BREACHED',severity='critical')
  with patch('web_push._actionable',return_value=None):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),2)
  self.assertIn('kritisk exitadvarsel',sent[1]['title'])
 def test_critical_push_skips_fresh_closed_position_not_stale_data(self):
  for stale in (False,True):
   with self.subTest(stale=stale):
    self.subscribe();at=self.now+timedelta(seconds=10 if stale else 0);sent=[]
    with app.connect() as c:engine.event(c,self.watch,'RISK_REJECTION',at,'STOP_BREACHED',severity='critical')
    after=at+timedelta(seconds=1);snapshot={'latest_context':{'status':'verified','position':'none','as_of':(at-timedelta(seconds=301) if stale else after).isoformat()}}
    with patch('web_push._actionable',return_value=None),patch('hotwatch_engine.view',return_value=snapshot):web_push.dispatch_one(app.connect,after,lambda s,p,t:sent.append(p))
    self.assertEqual(len(sent),1 if stale else 0)
 def test_closed_snapshot_before_critical_event_does_not_hide_new_warning(self):
  self.subscribe();sent=[]
  with app.connect() as c:engine.event(c,self.watch,'RISK_REJECTION',self.now,'STOP_BREACHED',severity='critical')
  snapshot={'latest_context':{'status':'verified','position':'none','as_of':(self.now-timedelta(seconds=1)).isoformat()}}
  with patch('web_push._actionable',return_value=None),patch('hotwatch_engine.view',return_value=snapshot):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),1)
 def test_closed_snapshot_at_same_time_does_not_prove_order(self):
  self.subscribe();sent=[]
  with app.connect() as c:engine.event(c,self.watch,'RISK_REJECTION',self.now,'STOP_BREACHED',severity='critical')
  snapshot={'latest_context':{'status':'verified','position':'none','as_of':self.now.isoformat()}}
  with patch('web_push._actionable',return_value=None),patch('hotwatch_engine.view',return_value=snapshot):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),1)
 def test_changed_exposure_rearms_only_with_two_verified_keys(self):
  with app.connect() as c:
   engine.event(c,self.watch,'SELL_SIGNAL',self.now,'prior exit');event=c.execute("SELECT event_id FROM hw_events WHERE event_type='SELL_SIGNAL' ORDER BY id DESC LIMIT 1").fetchone()['event_id']
   def calc(offset,key,status='verified',age=0):
    at=self.now+timedelta(seconds=offset);payload={'signal':'WAIT','reason_codes':['CONFIRMATION_PENDING'],'new_market_observation':True,'exit_context_key':key,'position_context':{'position':'held','status':status,'as_of':(at-timedelta(seconds=age)).isoformat()},'risk_level':'normal'}
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),'x'))
   calc(0,'first');calc(1,'first');self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   calc(2,'second','unknown');self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   calc(3,'second',age=301);self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   calc(4,'second');self.assertTrue(web_push._exit_rearmed(c,self.watch['id'],event))
 def test_first_exposure_evidence_is_not_itself_a_new_trade(self):
  with app.connect() as c:
   engine.event(c,self.watch,'SELL_SIGNAL',self.now,'prior exit without exposure evidence');event=c.execute("SELECT event_id FROM hw_events WHERE event_type='SELL_SIGNAL' ORDER BY id DESC LIMIT 1").fetchone()['event_id']
   at=self.now+timedelta(seconds=10);payload={'signal':'WAIT','reason_codes':['CONFIRMATION_PENDING'],'new_market_observation':True,'exit_context_key':'newly-known','position_context':{'position':'held','status':'verified','as_of':at.isoformat()},'risk_level':'normal'}
   c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),'x'))
   self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
 def test_legacy_snapshot_rearms_only_for_observed_exposure_change(self):
  with app.connect() as c:
   engine.event(c,self.watch,'SELL_SIGNAL',self.now,'legacy exit');event=c.execute("SELECT event_id FROM hw_events WHERE event_type='SELL_SIGNAL' ORDER BY id DESC LIMIT 1").fetchone()['event_id']
   previous={'position_context':{'position':'held','status':'verified','quantity':'10','cost_price':'98','as_of':self.now.isoformat()}}
   c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],self.now.isoformat(),json.dumps(previous),'x'))
   def calc(offset,quantity):
    at=self.now+timedelta(seconds=offset);payload={'signal':'WAIT','reason_codes':['CONFIRMATION_PENDING'],'new_market_observation':True,'position_context':{'position':'held','status':'verified','quantity':quantity,'cost_price':'98.00','as_of':at.isoformat()},'risk_level':'normal'}
    c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],at.isoformat(),json.dumps(payload),'x'))
   calc(1,'10.0');self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   calc(2,'9');self.assertTrue(web_push._exit_rearmed(c,self.watch['id'],event))
   previous['position_context']['as_of']=(self.now-timedelta(seconds=301)).isoformat();c.execute('UPDATE hw_calculations SET payload=? WHERE watch_row_id=? AND calculated=?',(json.dumps(previous),self.watch['id'],self.now.isoformat()))
   self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
 def test_observed_close_then_same_quantity_reentry_rearms(self):
  with app.connect() as c:
   engine.event(c,self.watch,'SELL_SIGNAL',self.now,'prior exit');event=c.execute("SELECT event_id FROM hw_events WHERE event_type='SELL_SIGNAL' ORDER BY id DESC LIMIT 1").fetchone()['event_id']
   entry=self.now+timedelta(seconds=20);payload={'signal':'WAIT','reason_codes':['CONFIRMATION_PENDING'],'new_market_observation':True,'exit_context_key':'same-quantity','position_context':{'position':'held','status':'verified','as_of':entry.isoformat()},'risk_level':'normal'}
   c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],entry.isoformat(),json.dumps(payload),'x'))
   self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   stale={'position':'none','status':'verified','as_of':(self.now-timedelta(seconds=301)).isoformat()}
   c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(self.watch['id'],(self.now+timedelta(seconds=1)).isoformat(),json.dumps(stale)))
   self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   earlier={'position':'none','status':'verified','as_of':(self.now-timedelta(seconds=1)).isoformat()}
   c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(self.watch['id'],(self.now+timedelta(seconds=2)).isoformat(),json.dumps(earlier)))
   unknown={'position':'none','status':'unknown','as_of':(self.now+timedelta(seconds=5)).isoformat()}
   c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(self.watch['id'],(self.now+timedelta(seconds=5)).isoformat(),json.dumps(unknown)))
   self.assertFalse(web_push._exit_rearmed(c,self.watch['id'],event))
   closed=self.now+timedelta(seconds=10);context={'position':'none','status':'verified','as_of':closed.isoformat()}
   c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(self.watch['id'],closed.isoformat(),json.dumps(context)))
   self.assertTrue(web_push._exit_rearmed(c,self.watch['id'],event))
   payload.update(signal='SELL',risk_level='critical');c.execute('UPDATE hw_calculations SET payload=? WHERE watch_row_id=? AND calculated=?',(json.dumps(payload),self.watch['id'],entry.isoformat()))
   self.assertTrue(web_push._exit_rearmed(c,self.watch['id'],event))
 def test_push_once_again_after_observed_close_and_same_quantity_reentry(self):
  self.subscribe();sent=[];self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  closed=self.now+timedelta(seconds=10);entry=self.now+timedelta(seconds=20)
  with app.connect() as c:
   context={'position':'none','status':'verified','as_of':closed.isoformat()};c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(self.watch['id'],closed.isoformat(),json.dumps(context)))
   payload={'signal':'SELL','reason_codes':['EXIT_RULES'],'new_market_observation':True,'exit_context_key':'same-quantity','position_context':{'position':'held','status':'verified','as_of':entry.isoformat()},'risk_level':'normal'}
   c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],entry.isoformat(),json.dumps(payload),'x'))
   engine.event(c,self.watch,'SELL_SIGNAL',entry,'new position')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,entry,lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),2)
 def test_old_queued_exit_is_not_rearmed_by_a_future_reentry(self):
  self.subscribe();sent=[];self.event('SELL_SIGNAL')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,self.now,lambda s,p,t:sent.append(p))
  closed=self.now+timedelta(seconds=10);old=self.now+timedelta(seconds=12);entry=self.now+timedelta(seconds=20)
  with app.connect() as c:
   context={'position':'none','status':'verified','as_of':closed.isoformat()};c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(self.watch['id'],closed.isoformat(),json.dumps(context)))
   engine.event(c,self.watch,'SELL_SIGNAL',old,'old queued signal')
   payload={'signal':'SELL','reason_codes':['EXIT_RULES'],'new_market_observation':True,'exit_context_key':'same-quantity','position_context':{'position':'held','status':'verified','as_of':entry.isoformat()},'risk_level':'normal'}
   c.execute('INSERT INTO hw_calculations(watch_row_id,calculated,payload,strategy_checksum) VALUES(?,?,?,?)',(self.watch['id'],entry.isoformat(),json.dumps(payload),'x'))
   engine.event(c,self.watch,'SELL_SIGNAL',entry,'new position')
  with patch('web_push._actionable',return_value='SELL'):
   web_push.dispatch_one(app.connect,entry,lambda s,p,t:sent.append(p));self.assertEqual(len(sent),1)
   web_push.dispatch_one(app.connect,entry,lambda s,p,t:sent.append(p));self.assertEqual(len(sent),2)
  with app.connect() as c:
   rows=c.execute('SELECT j.status,e.created FROM push_jobs j JOIN hw_events e ON e.event_id=j.event_key WHERE j.watch_row_id=? ORDER BY j.id',(self.watch['id'],)).fetchall()
  self.assertEqual([(row['status'],row['created']) for row in rows],[('sent',self.now.isoformat()),('skipped',old.isoformat()),('sent',entry.isoformat())])
  with app.connect() as c:engine.event(c,self.watch,'SELL_SIGNAL',entry+timedelta(seconds=1),'duplicate')
  with patch('web_push._actionable',return_value='SELL'):web_push.dispatch_one(app.connect,entry+timedelta(seconds=1),lambda s,p,t:sent.append(p))
  self.assertEqual(len(sent),2)
 def test_worsening_uses_configured_trailing_distance(self):
  self.assertFalse(engine.trailing_notification_worsened('0.394','0.4','2'))
  self.assertTrue(engine.trailing_notification_worsened('0.392','0.4','2'))
  self.assertFalse(engine.trailing_notification_worsened('0.393','0.4','2'))
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
