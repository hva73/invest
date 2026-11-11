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
  first=record(5,'processed',1000);first['metrics'].update(scope_entry_wait_ms=12,sqlite_begin_ms=2);first['metrics']['market_conflict']={'fields':['price'],'previous':{'price':'143.7536','secret':'DO_NOT_EXPOSE'},'incoming':{'price':'143.95'},'observations':{'previous':{'source':'eodhd','price_time_kind':'trade','event_time':self.now.isoformat(),'sample_ref':'0123456789abcdef','secret':'DO_NOT_EXPOSE'},'incoming':{'source':'eodhd','event_time':self.now.isoformat(),'sample_ref':'invalid-secret'}},'ingest_attempt_at':self.now.isoformat()}
  first['metrics']['websocket'][0].update(batch_valid_count=250,batch_partial_count=0,batch_limit_reached=True)
  path.write_text('\n'.join(json.dumps(x) for x in [first,record(6,'deferred',9000),record(7,'processed',2000,2)]))
  Path(str(path)+'.1').write_text(json.dumps(record(400,'degraded',3000)))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  self.assertEqual(result['log_files_read'],2);self.assertEqual(result['windows']['5m']['completed'],1);self.assertEqual(result['windows']['5m']['deferred'],1)
  self.assertEqual(result['windows']['5m']['queue']['p50_ms'],1000);self.assertEqual(result['windows']['1h']['completed'],2)
  self.assertIn('worker_utilization',result);self.assertIn('readiness_by_market',result);self.assertIn('market_sleep',result);self.assertEqual(result['market_sleep']['estimated_avoided_scans'],0);self.assertEqual(result['recent'][0]['metrics']['websocket_ms'],500);self.assertEqual(result['recent'][0]['metrics']['market_conflict']['incoming']['price'],'143.95');self.assertNotIn('DO_NOT_EXPOSE',json.dumps(result));self.assertEqual(result['session_count'],1)
  self.assertEqual(result['recent'][0]['metrics']['scope_entry_wait_ms'],12);self.assertEqual(result['recent'][0]['metrics']['sqlite_begin_ms'],2)
  ws=result['recent'][0]['metrics']['websocket'][0];self.assertEqual(ws['batch_valid_count'],250);self.assertEqual(ws['batch_partial_count'],0);self.assertIs(ws['batch_limit_reached'],True)
  diagnostic=result['recent'][0]['metrics']['market_conflict'];self.assertEqual(diagnostic['observations']['previous']['sample_ref'],'0123456789abcdef');self.assertNotIn('sample_ref',diagnostic['observations']['incoming']);self.assertNotIn('invalid-secret',json.dumps(result))
  with app.connect() as c:c.execute("UPDATE hw_sessions SET status='EXPIRED' WHERE watch_id=?",(self.f.req['watch_id'],))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now);self.assertEqual(result['session_count'],0);self.assertEqual(result['windows']['1h']['completed'],2)
 def test_entry_funnel_counts_rules_and_historical_confirmation_moves(self):
  import hotwatch_engine as engine
  strategy=engine.BASELINE;now=self.now;req=dict(self.f.req,provider='eodhd',watch_mode='entry')
  def record(at,signal,codes,price,metrics=None,watch='w',candidate='one'):
   request=dict(req,candidate_id=candidate);sample=fixture.tick(at,price=price);sample.update(source='eodhd',market_status='REGULAR')
   calc={'signal':signal,'reason_codes':codes,'data_timestamp':at.isoformat(),'supporting_metrics':metrics or fixture.good_metrics()}
   return {'watch_id':watch,'request':json.dumps(request),'strategy':json.dumps(strategy),'calculated':at.isoformat(),'calculation':json.dumps(calc),'strategy_checksum':engine.checksum(strategy),'sample':json.dumps(sample)}
  values=[record(now-timedelta(minutes=7),'WAIT',['CONFIRMATION_PENDING'],'100'),record(now-timedelta(minutes=6),'BUY',['ENTRY_RULES'],'102'),record(now-timedelta(minutes=1),'WAIT',['NO_TRIGGER'],'103')]
  bad=fixture.good_metrics();bad['relative_volume']='1';values.append(record(now,'WAIT',['NO_TRIGGER'],'100',bad,watch='w2',candidate='two'))
  out=hotwatch_service.entry_funnel(list(reversed(values)),now);group=out['strategies']['escape_momentum v1.0.0'];volume=next(x for x in group['rules'] if x['rule']=='relative_volume')
  self.assertEqual(out['candidate_count'],2);self.assertEqual(volume['failed'],1);self.assertEqual(out['confirmation_movement']['confirmed_sequences'],1);self.assertEqual(out['confirmation_movement']['before_confirmation']['median_pct'],2);self.assertEqual(out['confirmation_movement']['five_to_ten_minutes_after']['count'],1)
  values.extend([record(now-timedelta(minutes=8),'WAIT',['CONFIRMATION_PENDING'],'100',watch='w4',candidate='four'),record(now-timedelta(minutes=7),'BUY',['ENTRY_RULES'],'104',watch='w4',candidate='four')]);out=hotwatch_service.entry_funnel(sorted(values,key=lambda x:x['calculated'],reverse=True),now);self.assertEqual(out['confirmation_movement']['before_confirmation']['median_pct'],3)
  no_data=record(now,'NO_DATA',['DATA_STALE'],'100',watch='w3',candidate='three');self.assertEqual(hotwatch_service.entry_funnel([no_data],now)['missing_or_unverified'],1)
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
