"""Read-only, causal comparison on isolated synthetic HOT WATCH observations."""
import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
import app,report_ingest,hotwatch_engine as engine,strategy_lab
from hotwatch_contract import checksum
from test_intel_workflows import merc_report
from test_hotwatch_engine import request,tick

class Lab(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=app.DB;app.DB=self.temp.name+'/db';app.init();app.create_user('test-password-long-enough')
  with app.connect() as c:c.execute("INSERT INTO users(username,salt,hash,role,active) VALUES('member','00','00','member',1)")
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
 def test_legacy_inline_bar_replay_after_reopen(self):
  """Exercise the baseline's SQLite JSON readers independently of the candidate codec."""
  at=datetime(2026,11,4,15,15,tzinfo=timezone.utc)
  req=request(wid='inline-bar-watch')
  req.update(purpose='inline bar replay',provider='eodhd',provider_symbol='MERC.US')
  engine.create(app.connect,1,req,at)
  with app.connect() as c:
   c.execute('INSERT INTO hw_verified_feed_links VALUES(?,?,?,?,?,?,?,?)',
             (1,req['asset_id'],req['ticker'],req['quote_currency'],req['exchange'],req['provider_symbol'],'US1234567890',at.timestamp()))
  sample=tick(at,price='104')
  sample.update(source='eodhd',feed_type='fixture WS trade',price_time_kind='trade',
                bid_at=at.isoformat(),ask_at=at.isoformat(),status_at=at.isoformat(),
                quote_feed='us_quotes',status_feed='us_status')
  sample['bar_history']=[
   {'bar_open_at':(at-timedelta(minutes=35-i)).isoformat(),
    'open':'100','high':'105','low':'99','close':str(100+i/10),'volume':str(100+i)}
   for i in range(35)
  ]
  sample['bar_evidence']={
   'provider_symbol':'MERC.US','market':'us','exchange':'US','timezone':'America/New_York',
   'session_date':'2026-11-04','open':'09:30:00','close':'16:00:00',
   'working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[],
   'schedule_received_at':at.isoformat(),'exchange_open':True,'feed':'eodhd_realtime_history',
  }
  calculation=engine.ingest(app.connect,1,req['watch_id'],True,sample,at)['calculation']
  self.assertTrue(calculation['analysis_uses_bars'])
  self.assertEqual(calculation['supporting_metrics']['bar_history_count'],35)

  with app.connect() as c:
   sample_row=dict(c.execute(
    'SELECT s.* FROM hw_samples s JOIN hw_sessions w ON w.id=s.watch_row_id WHERE w.watch_id=?',
    (req['watch_id'],),
   ).fetchone())
   calc_row=dict(c.execute('SELECT * FROM hw_calculations WHERE sample_row_id=?',(sample_row['id'],)).fetchone())
  self.assertEqual(json.loads(sample_row['payload']),sample)
  self.assertEqual(sample_row['digest'],checksum(sample))
  self.assertEqual(json.loads(calc_row['payload']),calculation)
  self.assertEqual(calc_row['strategy_checksum'],calculation['strategy_checksum'])
  for kind,row in [('samples',sample_row),('metrics',calc_row)]:
   expected={key:value for key,value in row.items() if key!='payload'}
   expected['data']=json.loads(row['payload'])
   self.assertEqual(engine.history(app.connect,1,req['watch_id'],True,kind)['items'],[expected])

  data={**self.data,'watch_id':req['watch_id'],'strategies':self.data['strategies'][:1]}
  before=self.snapshot()
  replay=strategy_lab.compare(app.connect,1,data)
  self.assertEqual((replay['evaluated'],replay['skipped']),(1,0))
  self.assertEqual(replay['strategies'][0]['timeline'],[{
   'at':at.isoformat(),'signal':calculation['signal'],'reason_codes':calculation['reason_codes'],
   'missing':[],'early_watch':None,
  }])
  self.assertEqual(self.snapshot(),before)

  with app.connect() as c:
   c.execute('UPDATE hw_calculations SET sample_row_id=NULL WHERE id=?',(calc_row['id'],))
  replay=strategy_lab.compare(app.connect,1,data)
  self.assertEqual((replay['evaluated'],replay['skipped']),(0,1))
  self.assertEqual(replay['strategies'][0]['timeline'],[])
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
if __name__=='__main__':unittest.main()
