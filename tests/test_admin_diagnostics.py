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
  first['metrics']['websocket'].append({'wait_ms':0,'batch_valid_count':'PRIVATE_FEED_PAYLOAD','batch_partial_count':251,'batch_limit_reached':'PRIVATE_FEED_PAYLOAD'})
  path.write_text('\n'.join(json.dumps(x) for x in [first,record(6,'deferred',9000),record(7,'processed',2000,2)]))
  Path(str(path)+'.1').write_text(json.dumps(record(400,'degraded',3000)))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  self.assertEqual(result['log_files_read'],2);self.assertEqual(result['windows']['5m']['completed'],1);self.assertEqual(result['windows']['5m']['deferred'],1)
  self.assertEqual(result['windows']['5m']['queue']['p50_ms'],1000);self.assertEqual(result['windows']['1h']['completed'],2)
  self.assertIn('worker_utilization',result);self.assertIn('readiness_by_market',result);self.assertIn('market_sleep',result);self.assertEqual(result['market_sleep']['estimated_avoided_scans'],0);self.assertEqual(result['recent'][0]['metrics']['websocket_ms'],500);self.assertEqual(result['recent'][0]['metrics']['market_conflict']['incoming']['price'],'143.95');self.assertNotIn('DO_NOT_EXPOSE',json.dumps(result));self.assertEqual(result['session_count'],1)
  self.assertEqual(result['recent'][0]['metrics']['scope_entry_wait_ms'],12);self.assertEqual(result['recent'][0]['metrics']['sqlite_begin_ms'],2)
  ws=result['recent'][0]['metrics']['websocket'][0];self.assertEqual(ws['batch_valid_count'],250);self.assertEqual(ws['batch_partial_count'],0);self.assertIs(ws['batch_limit_reached'],True)
  self.assertEqual(result['recent'][0]['metrics']['websocket'][1],{'wait_ms':0});self.assertNotIn('PRIVATE_FEED_PAYLOAD',json.dumps(result))
  diagnostic=result['recent'][0]['metrics']['market_conflict'];self.assertEqual(diagnostic['observations']['previous']['sample_ref'],'0123456789abcdef');self.assertNotIn('sample_ref',diagnostic['observations']['incoming']);self.assertNotIn('invalid-secret',json.dumps(result))
  with app.connect() as c:c.execute("UPDATE hw_sessions SET status='EXPIRED' WHERE watch_id=?",(self.f.req['watch_id'],))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now);self.assertEqual(result['session_count'],0);self.assertEqual(result['windows']['1h']['completed'],2)
 def test_sqlite_phases_use_only_recorded_timings_from_the_current_tenant(self):
  ref=hashlib.sha256(self.f.req['watch_id'].encode()).hexdigest()[:16]
  def scan(age,metrics,user=1):
   return {'service':'hotwatch','user_id':user,'is_test':False,'watch_ref':ref,'status':'processed',
           'utc':(self.now-timedelta(seconds=age)).isoformat(),'metrics':metrics}
  phases={'scope_entry_wait_ms':12,'sqlite_begin_ms':2,'begin_wait_ms':14,'work_before_commit_ms':3.125}
  records=[scan(1,phases),scan(2,{'begin_wait_ms':17}),scan(400,{'work_before_commit_ms':0}),
           scan(3,{'work_before_commit_ms':800},user=2)]
  invalid=[None,'4',True,-1,float('nan'),float('inf'),86400001,10**400]
  records.extend(scan(age,{'work_before_commit_ms':value,'queue_ms':7}) for age,value in enumerate(invalid,10))
  path=Path(app.DB).parent/'hotwatch-scans.jsonl'
  path.write_text('\n'.join(json.dumps(record) for record in records))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  metrics=[record['metrics'] for record in result['recent']]
  self.assertEqual({key:metrics[0].get(key) for key in phases},phases)
  self.assertNotIn('work_before_commit_ms',metrics[1])
  self.assertEqual(len(metrics),len(records)-1)
  for row in metrics[2:-1]:
   self.assertNotIn('work_before_commit_ms',row)
   self.assertEqual(row['queue_ms'],7)
  self.assertEqual(metrics[-1]['work_before_commit_ms'],0)
  factors=result['queue_factors']
  self.assertEqual(factors['5m']['database_begin_wait'],{'count':2,'p50_ms':14,'p90_ms':17,'max_ms':17})
  self.assertEqual(factors['5m']['sqlite_begin'],{'count':1,'p50_ms':2,'p90_ms':2,'max_ms':2})
  self.assertEqual(factors['5m']['database_work_before_commit'],{'count':1,'p50_ms':3.125,'p90_ms':3.125,'max_ms':3.125})
  for window in ('1h','24h'):
   self.assertEqual(factors[window]['database_work_before_commit'],{'count':2,'p50_ms':0,'p90_ms':3.125,'max_ms':3.125})
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
  resources=result['resources']
  self.assertEqual(resources['status'],'unavailable')
  self.assertIsNone(resources['sample'])
  self.assertEqual(resources['windows']['24h']['worker']['covered_s'],0)
  self.assertIsNone(resources['windows']['24h']['worker']['cpu_s'])
  with app.connect() as c:self.assertEqual(c.total_changes,before)
 def test_missing_websocket_observations_are_not_counted_as_zero_wait(self):
  ref=hashlib.sha256(self.f.req['watch_id'].encode()).hexdigest()[:16]
  def record(seconds,metrics):return {'service':'hotwatch','user_id':1,'is_test':False,'utc':(self.now-timedelta(seconds=seconds)).isoformat(),'watch_ref':ref,'source':'eodhd','status':'processed','metrics':metrics}
  path=Path(app.DB).parent/'hotwatch-scans.jsonl'
  path.write_text('\n'.join(json.dumps(x) for x in [record(1,{}),record(2,{'websocket':[]}),record(3,{'websocket':[{'wait_ms':500}]}),record(4,{'websocket':None}),record(5,{'websocket':'invalid'})]))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  self.assertNotIn('websocket_ms',result['recent'][0]['metrics'])
  self.assertEqual(result['recent'][1]['metrics']['websocket_ms'],0)
  self.assertNotIn('websocket_ms',result['recent'][3]['metrics'])
  self.assertNotIn('websocket_ms',result['recent'][4]['metrics'])
  self.assertEqual(result['windows']['5m']['websocket'],{'count':2,'p50_ms':0,'p90_ms':500,'max_ms':500})
  self.assertEqual(result['queue_factors']['5m']['websocket_wait']['count'],2)
 def test_incomplete_websocket_lists_do_not_understate_wait(self):
  ref=hashlib.sha256(self.f.req['watch_id'].encode()).hexdigest()[:16]
  def rec(seconds,ws):return {'service':'hotwatch','user_id':1,'is_test':False,'utc':(self.now-timedelta(seconds=seconds)).isoformat(),'watch_ref':ref,'source':'eodhd','status':'processed','metrics':{'websocket':ws}}
  values=[[{'status':'OK'}],[{'wait_ms':'invalid'}],[{'wait_ms':500},{'status':'OK'}],[{'wait_ms':True}],[{'wait_ms':float('nan')}],[],[{'wait_ms':200},{'wait_ms':300}]]
  path=Path(app.DB).parent/'hotwatch-scans.jsonl';path.write_text('\n'.join(json.dumps(rec(i+1,ws)) for i,ws in enumerate(values)))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  for rec in result['recent'][:5]:self.assertNotIn('websocket_ms',rec['metrics'])
  self.assertEqual([x['metrics']['websocket_ms'] for x in result['recent'][5:7]],[0,500])
  self.assertEqual(result['windows']['5m']['websocket']['count'],2)
  self.assertEqual(result['queue_factors']['5m']['websocket_wait']['count'],2)
 def test_push_and_cron_counts_do_not_include_device_details(self):
  with app.connect() as c:
   c.execute("INSERT INTO push_devices(user_id,endpoint_hash,payload,created,updated) VALUES(1,'synthetic-private-endpoint',?, ?, ?)",(b'private-device',self.now.timestamp(),self.now.timestamp()))
   device=c.execute('SELECT id FROM push_devices').fetchone()[0];watch=c.execute('SELECT id FROM hw_sessions').fetchone()[0]
   c.execute("INSERT INTO push_jobs(event_key,watch_row_id,device_id,created,status) VALUES('event',?,?,?,'pending')",(watch,device,self.now.timestamp()-10))
   c.execute('INSERT INTO worker_state VALUES(1,?)',(self.now.timestamp()-20,))
  result=hotwatch_service.admin_diagnostics(app.connect,1,self.now)
  self.assertEqual(result['push']['last_24h']['pending'],1);self.assertEqual(result['push']['oldest_pending_age_s'],10)
  self.assertIsNotNone(result['scheduled_jobs']['worker_last_seen']);self.assertNotIn('private-device',json.dumps(result));self.assertNotIn('synthetic-private-endpoint',json.dumps(result))
 def test_resource_snapshot_is_admin_only_read_only_and_sanitized(self):
  from unittest.mock import patch
  import hotwatch_supervisor

  epoch=self.now.timestamp()
  path=Path(app.DB).with_name('hotwatch-resources.json')
  payload=json.dumps([{'epoch':epoch,'elapsed_s':60,'worker_cpu_s':15,'worker_rss_bytes':4096,
                       'host_logical_cpus':32,'cgroup_cpu_ceiling_cores':.5,
                       'pid':98765,'raw_path':'DO_NOT_EXPOSE'}])
  path.write_text(payload)
  handler=object.__new__(app.Handler)
  handler.path='/api/admin/diagnostics'
  connect=app.connect
  def read_only_connect():
   connection=connect()
   connection.execute('PRAGMA query_only=ON')
   return connection

  with patch.object(handler,'session',return_value={'user_id':1,'role':'user'}) as session, \
       patch.object(handler,'send') as send, patch.object(app,'connect',read_only_connect), \
       patch.object(hotwatch_supervisor.ResourceSampler,'tick',side_effect=AssertionError('sampled from request')), \
       patch.object(hotwatch_service.engine,'utc',return_value=self.now):
   with patch.object(hotwatch_supervisor,'resource_snapshot',wraps=hotwatch_supervisor.resource_snapshot) as read:
    handler.do_GET()
    self.assertEqual(send.call_args.args[0],403)
    read.assert_not_called()
    session.return_value={'user_id':1,'role':'admin'}
    handler.do_GET()
    self.assertEqual(send.call_args.args[0],200)
    read.assert_called_once_with(path.resolve(),epoch)
   resources=send.call_args.args[1]['resources']
  self.assertEqual(resources['status'],'fresh')
  self.assertEqual(resources['sample']['worker_average_cores'],.25)
  self.assertEqual(resources['sample']['cgroup_cpu_ceiling_cores'],.5)
  self.assertEqual(resources['windows']['5m']['worker']['covered_s'],60)
  self.assertNotIn('DO_NOT_EXPOSE',json.dumps(resources))
  self.assertNotIn('98765',json.dumps(resources))
  self.assertEqual(path.read_text(),payload)
