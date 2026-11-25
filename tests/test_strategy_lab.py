"""Read-only, causal comparison on isolated synthetic HOT WATCH observations."""
import copy,json,sqlite3,tempfile,unittest
from contextlib import closing
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
import app,report_ingest,hotwatch_engine as engine,strategy_lab
from hotwatch_contract import checksum
from hotwatch_strategy import EARLY_CATALYST_V1
from test_intel_workflows import merc_report
from test_hotwatch_engine import good_metrics,request,tick

def fixture_users():
 with app.connect() as c:
  c.execute("INSERT INTO users(id,username,role,active) VALUES(1,'owner','admin',1),(2,'member','member',1)")


class Lab(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=app.DB;app.DB=self.temp.name+'/db';app.init()
  fixture_users()
  self.now=datetime.now(timezone.utc).replace(microsecond=0);report_ingest.save(app.connect,1,merc_report(True));self.req=request();engine.create(app.connect,1,self.req,self.now)
  self.base=self.now-timedelta(hours=1)
  for i in range(38):
   at=self.base+timedelta(minutes=i);sample=tick(at,i,price=str(100+i/100));engine.ingest(app.connect,1,self.req['watch_id'],True,sample,at)
  self.data={'watch_id':self.req['watch_id'],'is_test':True,'strategies':[{'strategy_id':'escape_momentum','version':'1.0.0'},{'strategy_id':'escape_early_catalyst','version':'0.1.0'}]}
 def tearDown(self):app.DB=self.old;self.temp.cleanup()
 def snapshot(self):
  with app.connect() as c:return list(c.iterdump())
 def test_comparison_is_read_only_and_marks_missing_catalyst(self):
  before=self.snapshot();result=strategy_lab.compare(app.connect,1,self.data)
  self.assertEqual(before,self.snapshot());self.assertEqual(result['evaluated'],38);self.assertEqual(result['skipped'],0)
  self.assertEqual(sum(result['strategies'][0]['counts'].values()),38)
  self.assertIn('catalyst_verified',result['strategies'][1]['missing_indicators']);self.assertEqual(result['strategies'][1]['counts']['BUY'],0)
  self.assertEqual(strategy_lab.available(app.connect,1)['sessions'][0]['calculations'],38)
 def test_baseline_matches_simple_recorded_sequence(self):
  replay=strategy_lab.compare(app.connect,1,self.data)['strategies'][0]['timeline']
  with app.connect() as c:rows=c.execute('SELECT calculated,payload FROM hw_calculations ORDER BY id DESC LIMIT 12').fetchall()
  actual=[(r['calculated'],json.loads(r['payload'])['signal']) for r in reversed(rows)]
  self.assertEqual([(x['at'],x['signal']) for x in replay],actual)
 def test_no_lookahead_when_new_observation_arrives(self):
  first=strategy_lab.compare(app.connect,1,self.data)
  at=self.base+timedelta(minutes=38);engine.ingest(app.connect,1,self.req['watch_id'],True,tick(at,38,price='101.2'),at)
  second=strategy_lab.compare(app.connect,1,self.data)
  for a,b in zip(first['strategies'],second['strategies']):self.assertEqual(a['timeline'][1:],b['timeline'][:-1])
 def test_comparison_limits_and_discloses_truncation(self):
  from unittest.mock import patch
  with patch('strategy_lab.MAX_CALCULATIONS',2):result=strategy_lab.compare(app.connect,1,self.data)
  self.assertTrue(result['truncated']);self.assertEqual(result['limit'],2);self.assertEqual(result['evaluated'],2)
 def test_ownership_duplicates_and_context_gaps(self):
  with self.assertRaises(ValueError):strategy_lab.compare(app.connect,2,self.data)
  with self.assertRaises(ValueError):strategy_lab.compare(app.connect,1,{**self.data,'strategies':[self.data['strategies'][0]]*2})
  with app.connect() as c:
   row=c.execute('SELECT id,payload FROM hw_calculations ORDER BY id LIMIT 1').fetchone();x=json.loads(row['payload']);del x['risk_parameters'];c.execute('UPDATE hw_calculations SET payload=? WHERE id=?',(json.dumps(x),row['id']))
  result=strategy_lab.compare(app.connect,1,self.data);self.assertEqual(result['skipped'],1);self.assertEqual(result['evaluated'],37)
 def test_future_data_is_skipped_not_used(self):
  with app.connect() as c:
   row=c.execute('SELECT id,payload FROM hw_samples ORDER BY id LIMIT 1').fetchone();x=json.loads(row['payload']);x['event_time']=(self.now+timedelta(days=1)).isoformat();c.execute('UPDATE hw_samples SET payload=?,digest=? WHERE id=?',(json.dumps(x),checksum(x),row['id']))
  result=strategy_lab.compare(app.connect,1,self.data);self.assertEqual(result['skipped'],1);self.assertEqual(result['evaluated'],37)
class V2Replay(unittest.TestCase):
 def setUp(self):
  temp = tempfile.TemporaryDirectory()
  self.addCleanup(temp.cleanup)
  self.addCleanup(setattr, app, 'DB', app.DB)
  app.DB = temp.name + '/db'
  app.init()
  fixture_users()
  with app.connect() as c:
   portfolio = c.execute("INSERT INTO portfolios(user_id,name,source,updated) VALUES(1,'Fixture','pluto',0)").lastrowid
  self.at = datetime.now(timezone.utc).replace(microsecond=0)
  report_ingest.save(app.connect, 1, merc_report(True))
  self.req = dict(request(), portfolio_ids=[portfolio])
  engine.create(app.connect, 1, self.req, self.at)
  self.data = {
   'watch_id': self.req['watch_id'], 'is_test': True,
   'strategies': [
    {'strategy_id': 'escape_momentum', 'version': '1.0.0'},
    {'strategy_id': 'escape_early_catalyst', 'version': '1.0.0'},
   ],
  }

 def capture(self, index, **changes):
  at = self.at + timedelta(minutes=index)
  metrics = good_metrics() | {
   'return_window_pct': '.6', 'ordinary_share': True, 'pluto_tradable': True,
   'no_verified_news': True, 'reference_gain_pct': '2',
  } | changes
  with patch('hotwatch_engine.features', return_value=metrics):
   engine.ingest(app.connect, 1, self.req['watch_id'], True, tick(at, index), at + timedelta(seconds=2))

 def capture_windows(self, count=12):
  for window in (1, 5):
   spec = copy.deepcopy(EARLY_CATALYST_V1)
   spec.update(strategy_id=f'window_{window}')
   spec['parameters']['momentum_window_minutes'] = window
   spec['entry_rules'] = {'metric': 'return_window_pct', 'operator': '>=', 'value': '.4'}
   spec['watch_rules'] = {'metric': 'price', 'operator': '>', 'value': '0'}
   engine.upload_strategy(app.connect, 1, 'Fixture', spec)
   self.data['strategies'].append({'strategy_id': spec['strategy_id'], 'version': spec['version']})
  self.data['strategies'].pop(1)
  for index in range(count):
   self.capture_window_tick(index)

 def capture_window_tick(self, index):
  at = self.at + timedelta(minutes=index)
  engine.ingest(app.connect, 1, self.req['watch_id'], True,
                tick(at, index, price=f'{100 + index / 10:.1f}'), at + timedelta(seconds=2))

 def edit_calculation(self, c, index, change):
  row = c.execute('SELECT id,payload FROM hw_calculations ORDER BY id LIMIT 1 OFFSET ?',
                  (index,)).fetchone()
  calc = json.loads(row['payload'])
  change(calc)
  c.execute('UPDATE hw_calculations SET payload=? WHERE id=?', (json.dumps(calc), row['id']))

 def read_only(self, trace=None):
  c = sqlite3.connect(f'file:{app.DB}?mode=ro', uri=True)
  c.row_factory = sqlite3.Row
  if trace is not None:
   c.set_trace_callback(trace)
  return closing(c)

 def test_same_capture_records_original_and_distinct_v2_outcomes(self):
  self.capture(0, macd_histogram=None)
  with patch('hotwatch_adapters.PlutoAdapter', side_effect=AssertionError('Pluto access')), \
       patch('hotwatch_adapters.EODHDAdapter', side_effect=AssertionError('EODHD access')), \
       patch('trade_service.call', side_effect=AssertionError('Broker access')):
   first = strategy_lab.compare_v2(self.read_only, 1, self.data)
   self.assertEqual(first, strategy_lab.compare_v2(self.read_only, 1, self.data))
  self.assertEqual(first['coverage']['evaluated'], 1)
  point = first['timeline'][0]
  with self.read_only() as c:
   recorded = json.loads(c.execute('SELECT payload FROM hw_calculations').fetchone()[0])
  self.assertEqual(point['recorded']['signal'], recorded['signal'])
  self.assertEqual(first['recorded_counts'], {recorded['signal']: 1})
  self.assertEqual(point['recorded']['reason_codes'], recorded['reason_codes'])
  self.assertEqual(point['latency'], {'event_to_received_ms': 2000, 'received_to_calculated_ms': 0})
  momentum, early = point['simulated']
  self.assertEqual(momentum['reason_codes'], ['RULE_INPUT_UNAVAILABLE'])
  self.assertEqual(first['strategies'][0]['first_blocking_reason']['reason'], 'RULE_INPUT_UNAVAILABLE')
  self.assertEqual(early['action'], 'BUY')
  self.assertEqual(momentum['snapshot_checksum'], early['snapshot_checksum'])
  self.assertNotEqual(momentum['decision_digest'], early['decision_digest'])

  self.capture(1)
  second = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertEqual(second['timeline'][0], point)
  self.assertEqual(second['timeline'][1]['simulated'][0]['action'], 'BUY')
  self.assertEqual(second['strategies'][0]['counts'], {'decision': 1, 'observation': 0, 'blocked': 1})

 def test_missing_future_corrupt_and_unscoped_captures_are_skipped(self):
  for index in range(6):
   self.capture(index)
  with app.connect() as c:
   rows = c.execute("SELECT id,sample_row_id,payload FROM hw_calculations ORDER BY id").fetchall()
   future = (self.at + timedelta(days=1)).isoformat()
   c.execute("UPDATE hw_samples SET received=? WHERE id=?", (future, rows[0]['sample_row_id']))
   c.execute("UPDATE hw_samples SET digest='invalid' WHERE id=?", (rows[1]['sample_row_id'],))
   for index, change in (
    (2, lambda calc: calc.pop('supporting_metrics')),
    (3, lambda calc: calc['position_context'].update(position='held', quantity='1')),
    (4, lambda calc: calc['risk_parameters'].pop('_position_scope')),
   ):
    calc = json.loads(rows[index]['payload'])
    change(calc)
    c.execute('UPDATE hw_calculations SET payload=? WHERE id=?', (json.dumps(calc), rows[index]['id']))
  result = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertEqual(result['coverage'], {
   'considered': 6, 'evaluated': 1, 'skipped': 5,
   'skip_reasons': dict.fromkeys((
    'SAMPLE_CHRONOLOGY_UNVERIFIED', 'SAMPLE_CHECKSUM_MISMATCH', 'METRICS_CAPTURE_UNAVAILABLE',
    'POSITION_ID_UNAVAILABLE', 'HISTORICAL_SCOPE_UNVERIFIED',
   ), 1),
   'first_skip': {
    'calculation_id': rows[0]['id'], 'at': (self.at + timedelta(seconds=2)).isoformat(),
    'reason': 'SAMPLE_CHRONOLOGY_UNVERIFIED',
   },
  })
  self.assertEqual(result['timeline'][0]['snapshot_id'], f"hw_calculations:{rows[5]['id']}")
  with patch('strategy_lab.MAX_CALCULATIONS', 2):
   bounded = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertTrue(bounded['truncated'])
  self.assertEqual(bounded['coverage']['evaluated'], 0)
  self.assertEqual(bounded['coverage']['skipped'], 2)

 def test_mutable_trade_without_historical_revision_is_skipped(self):
  self.capture(0)
  with app.connect() as c:
   row = c.execute('SELECT id,payload FROM hw_samples').fetchone()
   sample = json.loads(row['payload'])
   sample.update(source='eodhd', price_time_kind='trade')
   c.execute('UPDATE hw_samples SET source=?,payload=?,digest=? WHERE id=?',
             ('eodhd', json.dumps(sample), checksum(sample), row['id']))
   c.execute("UPDATE hw_sessions SET request=json_set(request,'$.provider','eodhd')")
  result = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertEqual(result['coverage']['skip_reasons'], {'SAMPLE_REVISION_UNVERIFIED': 1})
  self.assertEqual(result['timeline'], [])

 def test_tenant_test_and_catalog_isolation(self):
  self.capture(0)
  with self.assertRaises(ValueError):
   strategy_lab.compare_v2(self.read_only, 2, self.data)
  with self.assertRaises(ValueError):
   strategy_lab.compare_v2(self.read_only, 1, dict(self.data, is_test=False))
  with app.connect() as c:
   c.execute("UPDATE hw_strategies SET checksum='wrong' WHERE strategy_id='escape_momentum'")
  with self.assertRaisesRegex(ValueError, 'verificeres'):
   strategy_lab.compare_v2(self.read_only, 1, self.data)

 def test_distinct_windows_use_real_recorded_inputs_in_one_bounded_read(self):
  self.capture_windows()
  reads = []

  with patch('hotwatch_adapters.PlutoAdapter', side_effect=AssertionError('Pluto access')), \
       patch('hotwatch_adapters.EODHDAdapter', side_effect=AssertionError('EODHD access')), \
       patch('trade_service.call', side_effect=AssertionError('Broker access')):
   result = strategy_lab.compare_v2(lambda: self.read_only(reads.append), 1, self.data)
   self.assertEqual(result, strategy_lab.compare_v2(self.read_only, 1, self.data))
  self.assertEqual(result['coverage']['considered'], 12)
  first = result['timeline'][0]['simulated']
  self.assertEqual(first[1]['reason_codes'], ['FEATURE_HISTORY_INSUFFICIENT'])
  _, short, long = result['timeline'][-1]['simulated']
  self.assertEqual(short['outcome'], 'observation')
  self.assertEqual(long['action'], 'BUY')
  self.assertNotEqual(short['snapshot_checksum'], long['snapshot_checksum'])
  journal_reads = [sql for sql in reads if 'hw_samples' in sql or 'hw_calculations' in sql]
  self.assertEqual(len(journal_reads), 1)
  self.assertIn('LIMIT 241', journal_reads[0])
  with patch('strategy_lab.MAX_CALCULATIONS', 3), \
       patch('strategy_lab.features', wraps=strategy_lab.features) as compute:
   bounded = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertTrue(bounded['truncated'])
  self.assertEqual(bounded['coverage']['considered'], 3)
  self.assertEqual([len(call.args[0]) for call in compute.call_args_list], [1, 1, 2, 2, 3, 3])

 def test_local_replay_reuses_periods_and_keeps_same_time_captures_distinct(self):
  self.capture_windows(count=11)
  with self.read_only() as c:
   spec = json.loads(c.execute("SELECT payload FROM hw_strategies WHERE strategy_id='window_5'").fetchone()[0])
  spec['strategy_id'] = 'window_5_other_rule'
  spec['entry_rules']['value'] = '99'
  engine.upload_strategy(app.connect, 1, 'Fixture', spec)
  choices = self.data['strategies'][1:] + [{'strategy_id': spec['strategy_id'], 'version': spec['version']}]
  data = dict(self.data, strategies=choices)
  # Give the older calculation the same cutoff that the next ingest will use.
  cutoff = (self.at + timedelta(minutes=11, seconds=2)).isoformat()
  with app.connect() as c:
   self.edit_calculation(c, 10, lambda calc: calc.update(calculation_timestamp=cutoff))
   c.execute('UPDATE hw_calculations SET calculated=? WHERE id=(SELECT max(id) FROM hw_calculations)',
             (cutoff,))
  older = strategy_lab.compare_v2(self.read_only, 1, data)['timeline'][-1]
  self.capture_window_tick(11)

  with patch('strategy_lab.features', wraps=strategy_lab.features) as compute:
   separate = [strategy_lab.compare_v2(self.read_only, 1, dict(data, strategies=[choice]))
               for choice in choices]
  self.assertEqual(compute.call_count, 36)
  with patch('strategy_lab.features', wraps=strategy_lab.features) as compute, \
       patch('strategy_lab.v2.shared_market_features_batch') as shared:
   together = strategy_lab.compare_v2(self.read_only, 1, data)
  self.assertEqual(compute.call_count, 24)
  shared.assert_not_called()
  for index, point in enumerate(together['timeline']):
   self.assertEqual(point['simulated'], [run['timeline'][index]['simulated'][0] for run in separate])
  old, new = together['timeline'][-2:]
  self.assertEqual(old, older)
  self.assertEqual(old['at'], new['at'])
  self.assertNotEqual(old['simulated'][1]['snapshot_checksum'], new['simulated'][1]['snapshot_checksum'])
  self.assertEqual(new['simulated'][1]['snapshot_checksum'], new['simulated'][2]['snapshot_checksum'])
  self.assertEqual([item['outcome'] for item in new['simulated']], ['observation', 'decision', 'observation'])

 def test_stale_price_history_is_not_recomputed(self):
  self.capture_windows()
  cutoff = (self.at + timedelta(minutes=14)).isoformat()
  with app.connect() as c:
   self.edit_calculation(c, 11, lambda calc: calc.update(calculation_timestamp=cutoff))
   c.execute('UPDATE hw_calculations SET calculated=? WHERE id=(SELECT max(id) FROM hw_calculations)',
             (cutoff,))
  with patch('strategy_lab.features', wraps=strategy_lab.features) as compute:
   point = strategy_lab.compare_v2(self.read_only, 1, self.data)['timeline'][-1]
  self.assertEqual(compute.call_count, 22)
  self.assertEqual(point['simulated'][2]['reason_codes'], ['FEATURE_HISTORY_STALE'])

 def test_history_rejects_marked_errors_and_unclosed_bars(self):
  self.capture_windows()
  with self.read_only() as c:
   row = c.execute('SELECT id,payload FROM hw_samples ORDER BY id LIMIT 1').fetchone()
  for change, reason in (
   ({'error_code': 'missing_provider_confirmation'}, 'SAMPLE_UNVERIFIED'),
   ({'price_time_kind': 'bar_open'}, 'SAMPLE_CHRONOLOGY_UNVERIFIED'),
  ):
   with self.subTest(change=change):
    sample = json.loads(row['payload']) | change
    with app.connect() as c:
     c.execute('UPDATE hw_samples SET payload=?,digest=? WHERE id=?',
               (json.dumps(sample), checksum(sample), row['id']))
    result = strategy_lab.compare_v2(self.read_only, 1, self.data)
    baseline, _, long = result['timeline'][-1]['simulated']
    self.assertIsNotNone(baseline['snapshot_checksum'])
    self.assertEqual(long['reason_codes'], [reason])

 def test_optional_and_unused_changed_feature_do_not_block_valid_alternative(self):
  self.capture(0)
  price = {'metric': 'price', 'operator': '>', 'value': '0'}
  rsi = {'metric': 'rsi', 'operator': '<=', 'value': '80'}
  choices = []
  for name, entry in (('alternative', {'any': [price, rsi]}),
                      ('unused', price), ('required', rsi)):
   spec = copy.deepcopy(EARLY_CATALYST_V1)
   spec.update(strategy_id='replay_' + name)
   spec['parameters']['rsi_period'] = 15
   spec['entry_rules'] = entry
   spec['watch_rules'] = price
   engine.upload_strategy(app.connect, 1, 'Fixture', spec)
   choices.append({'strategy_id': spec['strategy_id'], 'version': spec['version']})
  data = dict(self.data, strategies=choices)
  with app.connect() as c:
   self.edit_calculation(c, 0, lambda calc: calc['input_sample_ids'].insert(0, 'missing'))
  with patch('strategy_lab._feature_history', wraps=strategy_lab._feature_history) as history:
   result = strategy_lab.compare_v2(self.read_only, 1, data)
  alternative, unused, required = result['timeline'][0]['simulated']
  self.assertEqual(history.call_count, 1)
  self.assertEqual(alternative['action'], 'BUY')
  self.assertEqual(unused['action'], 'BUY')
  self.assertEqual(required['reason_codes'], ['FEATURE_HISTORY_MISSING'])
  self.assertIsNotNone(required['snapshot_checksum'])

 def test_later_future_and_mutable_history_only_block_incompatible_versions(self):
  self.capture_windows()
  baseline = strategy_lab.compare_v2(self.read_only, 1, self.data)['timeline'][-1]['simulated'][0]
  with app.connect() as c:
   self.edit_calculation(c, 10, lambda calc: calc['input_sample_ids'].insert(0, 'synthetic-tick-11'))
   c.execute("UPDATE hw_samples SET received=? WHERE sample_id='synthetic-tick-0'",
             ((self.at + timedelta(days=1)).isoformat(),))
  result = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertEqual(result['timeline'][-2]['simulated'][2]['reason_codes'], ['FEATURE_HISTORY_MISSING'])
  current, _, long = result['timeline'][-1]['simulated']
  self.assertEqual(current, baseline)
  self.assertEqual(long['reason_codes'], ['FEATURE_HISTORY_CHRONOLOGY_UNVERIFIED'])
  with app.connect() as c:
   rows = c.execute('SELECT id,payload FROM hw_samples ORDER BY id').fetchall()
   c.execute("UPDATE hw_sessions SET request=json_set(request,'$.provider','eodhd')")
   for index, row in enumerate(rows):
    sample = json.loads(row['payload'])
    sample['source'] = 'eodhd'
    if index == 0:
     sample['price_time_kind'] = 'trade'
    c.execute('UPDATE hw_samples SET source=?,received=?,payload=?,digest=? WHERE id=?',
              ('eodhd', (self.at + timedelta(minutes=index, seconds=2)).isoformat(),
               json.dumps(sample), checksum(sample), row['id']))
  result = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertEqual(result['timeline'][-1]['simulated'][2]['reason_codes'], ['SAMPLE_REVISION_UNVERIFIED'])

 def test_missing_original_checksum_and_foreign_catalog_cannot_supply_parameters(self):
  self.capture(0)
  with app.connect() as c:
   self.edit_calculation(c, 0, lambda calc: calc.pop('strategy_checksum'))
  result = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertEqual([item['reason_codes'] for item in result['timeline'][0]['simulated']],
                   [['ORIGINAL_STRATEGY_UNVERIFIED']] * 2)
  foreign = copy.deepcopy(EARLY_CATALYST_V1)
  foreign.update(strategy_id='foreign_window')
  engine.upload_strategy(app.connect, 2, 'Fixture', foreign)
  digest = checksum(foreign)
  with app.connect() as c:
   c.execute('UPDATE hw_calculations SET strategy_checksum=?', (digest,))
   self.edit_calculation(c, 0, lambda calc: calc.update(
       strategy_id=foreign['strategy_id'], strategy_version=foreign['version'], strategy_checksum=digest))
  result = strategy_lab.compare_v2(self.read_only, 1, self.data)
  self.assertEqual(result['strategies'][0]['first_blocking_reason']['reason'],
                   'ORIGINAL_STRATEGY_UNVERIFIED')

 def test_history_link_cannot_cross_owner_or_test_scope(self):
  self.capture_windows()
  with app.connect() as c:
   sample = c.execute('SELECT id,watch_row_id FROM hw_samples ORDER BY id LIMIT 1').fetchone()
   for owner, is_test in ((2, True), (1, False)):
    with self.subTest(owner=owner, is_test=is_test):
     other = c.execute('''INSERT INTO hw_sessions
         (user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,
          created,updated,next_due)
         SELECT ?,?, ?,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due
         FROM hw_sessions WHERE id=?''',
         (owner, f'other-{owner}', int(is_test), sample['watch_row_id'])).lastrowid
     c.execute('UPDATE hw_samples SET watch_row_id=? WHERE id=?', (other, sample['id']))
     c.commit()
     result = strategy_lab.compare_v2(self.read_only, 1, self.data)
     self.assertEqual(result['coverage']['skip_reasons'], {'SAMPLE_MISSING': 1})
     baseline, _, long = result['timeline'][-1]['simulated']
     self.assertIsNotNone(baseline['snapshot_checksum'])
     self.assertEqual(long['reason_codes'], ['FEATURE_HISTORY_MISSING'])

 def test_unpinned_bar_history_blocks_only_incompatible_windows(self):
  self.capture_windows()
  with app.connect() as c:
   self.edit_calculation(c, 11, lambda calc: calc['supporting_metrics'].update(bar_history_count=12))
  result = strategy_lab.compare_v2(self.read_only, 1, self.data)
  baseline, short, long = result['timeline'][-1]['simulated']
  self.assertIsNotNone(baseline['snapshot_checksum'])
  for alternative in (short, long):
   self.assertEqual(alternative['reason_codes'], ['FEATURE_BAR_REVISION_UNVERIFIED'])


if __name__=='__main__':unittest.main()
