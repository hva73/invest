"""Read-only, bounded operational dashboard using synthetic scan records."""
import hashlib,json,unittest
from datetime import timedelta
from pathlib import Path
import app,hotwatch_service
import test_hotwatch_engine as fixture

class AdminDiagnostics(unittest.TestCase):
 def setUp(self):
  self.f=fixture.HotWatch();self.f.setUp();self.now=self.f.now
  with app.connect() as c:c.execute('UPDATE hw_sessions SET is_test=0 WHERE watch_id=?',(self.f.req['watch_id'],))
 def tearDown(self):self.f.tearDown()
 def test_windows_exclude_deferred_and_other_users_and_never_return_raw_payload(self):
  ref=hashlib.sha256(self.f.req['watch_id'].encode()).hexdigest()[:16]
  def record(sec,status,queue,user=1):return {'service':'hotwatch','user_id':user,'is_test':False,'utc':(self.now-timedelta(seconds=sec)).isoformat(),'watch_ref':ref,'source':'eodhd','status':status,'code':'DATA_STALE','metrics':{'queue_ms':queue,'worker_busy_ms':700,'warmup_ms':300,'secret':'DO_NOT_EXPOSE','websocket':[{'wait_ms':500,'secret':'DO_NOT_EXPOSE'}]}}
  path=Path(app.DB).parent/'hotwatch-scans.jsonl'
  first=record(5,'processed',1000);first['metrics']['market_conflict']={'fields':['price'],'previous':{'price':'143.7536','secret':'DO_NOT_EXPOSE'},'incoming':{'price':'143.95'}}
  path.write_text('\n'.join(json.dumps(x) for x in [first,record(6,'deferred',9000),record(7,'processed',2000,2)]))
  Path(str(path)+'.1').write_text(json.dumps(record(400,'degraded',3000)))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  self.assertEqual(result['log_files_read'],2);self.assertEqual(result['windows']['5m']['completed'],1);self.assertEqual(result['windows']['5m']['deferred'],1)
  self.assertEqual(result['windows']['5m']['queue']['p50_ms'],1000);self.assertEqual(result['windows']['1h']['completed'],2)
  self.assertIn('worker_utilization',result);self.assertIn('readiness_by_market',result);self.assertIn('market_sleep',result);self.assertEqual(result['market_sleep']['estimated_avoided_scans'],0);self.assertEqual(result['recent'][0]['metrics']['websocket_ms'],500);self.assertEqual(result['recent'][0]['metrics']['market_conflict']['incoming']['price'],'143.95');self.assertNotIn('DO_NOT_EXPOSE',json.dumps(result));self.assertEqual(result['session_count'],1)
  with app.connect() as c:c.execute("UPDATE hw_sessions SET status='EXPIRED' WHERE watch_id=?",(self.f.req['watch_id'],))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now);self.assertEqual(result['session_count'],0);self.assertEqual(result['windows']['1h']['completed'],2)
 def test_missing_log_is_explicit_and_read_only(self):
  with app.connect() as c:before=c.total_changes
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  self.assertEqual(result['log_files_read'],0);self.assertEqual(result['recent'],[]);self.assertIsNone(result['windows']['5m']['queue'])
  with app.connect() as c:self.assertEqual(c.total_changes,before)
 def test_push_and_cron_counts_do_not_include_device_details(self):
  with app.connect() as c:
   c.execute("INSERT INTO push_devices(user_id,endpoint_hash,payload,created,updated) VALUES(1,'synthetic-private-endpoint',?, ?, ?)",(b'private-device',self.now.timestamp(),self.now.timestamp()))
   device=c.execute('SELECT id FROM push_devices').fetchone()[0];watch=c.execute('SELECT id FROM hw_sessions').fetchone()[0]
   c.execute("INSERT INTO push_jobs(event_key,watch_row_id,device_id,created,status) VALUES('event',?,?,?,'pending')",(watch,device,self.now.timestamp()-10))
   c.execute('INSERT INTO worker_state VALUES(1,?)',(self.now.timestamp()-20,))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  self.assertEqual(result['push']['last_24h']['pending'],1);self.assertEqual(result['push']['oldest_pending_age_s'],10)
  self.assertIsNotNone(result['scheduled_jobs']['worker_last_seen']);self.assertNotIn('private-device',json.dumps(result));self.assertNotIn('synthetic-private-endpoint',json.dumps(result))
