"""Read-only, causal comparison on isolated synthetic HOT WATCH observations."""
import json,sqlite3,tempfile,unittest
from contextlib import closing
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
import app,report_ingest,hotwatch_engine as engine,strategy_lab
from hotwatch_contract import checksum
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

 def read_only(self):
  c = sqlite3.connect(f'file:{app.DB}?mode=ro', uri=True)
  c.row_factory = sqlite3.Row
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


if __name__=='__main__':unittest.main()
