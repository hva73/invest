"""Read-only, causal comparison on isolated synthetic HOT WATCH observations."""
import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
import app,report_ingest,hotwatch_engine as engine,strategy_lab
from hotwatch_contract import checksum
from hotwatch_strategy import EARLY_CATALYST_V1
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
 def test_watch_truth_tables_and_signals_on_the_same_replay(self):
  leaves=[{'metric':key,'operator':'==','value':True} for key in ('ordinary_share','pluto_tradable')]
  strategies=[]
  for operator in ('all','any'):
   spec={**EARLY_CATALYST_V1,'strategy_id':'test_'+operator,'watch_rules':{operator:leaves},
         'entry_rules':{'metric':'price','operator':'>','value':'0'}}
   engine.upload_strategy(app.connect,1,'test',spec)
   strategies.append({'strategy_id':spec['strategy_id'],'version':spec['version']})

  # The first 29 observations have no captured catalyst evidence.
  cases=[
   # share, tradable, all status and signal, any status and signal
   (None,None,'unknown','NO_DATA','unknown','NO_DATA'),
   (None,False,'not_met','WAIT','unknown','NO_DATA'),
   (None,True,'unknown','NO_DATA','met','WAIT'),
   (False,None,'not_met','WAIT','unknown','NO_DATA'),
   (False,False,'not_met','WAIT','not_met','WAIT'),
   (False,True,'not_met','WAIT','met','WAIT'),
   (True,None,'unknown','NO_DATA','met','BUY'),
   (True,False,'not_met','WAIT','met','BUY'),
   (True,True,'met','WAIT','met','BUY'),
  ]
  with app.connect() as c:
   rows=list(reversed(c.execute('SELECT id,calculated,payload FROM hw_calculations ORDER BY id DESC LIMIT 9').fetchall()))
   for row,(share,tradable,*_) in zip(rows,cases):
    calc=json.loads(row['payload'])
    calc['early_catalyst']={}
    calc['supporting_metrics'].update(ordinary_share=share,pluto_tradable=tradable)
    c.execute('UPDATE hw_calculations SET payload=? WHERE id=?',(json.dumps(calc),row['id']))

  result=strategy_lab.compare(app.connect,1,{**self.data,'strategies':strategies})
  self.assertEqual((result['evaluated'],result['skipped']),(38,0))
  for outcome,column in zip(result['strategies'],(2,4)):
   statuses=[case[column] for case in cases]
   signals=[case[column+1] for case in cases]
   times=[row['calculated'] for row in rows]
   with self.subTest(strategy=outcome['strategy_id']):
    timeline=outcome['timeline'][-len(cases):]
    self.assertEqual([(t['at'],t['signal']) for t in timeline],list(zip(times,signals)))
    self.assertEqual([t['early_watch'] for t in timeline],statuses)
    for point,case in zip(timeline,cases):
     self.assertEqual(point['missing'],[leaf['metric'] for leaf,value in zip(leaves,case[:2]) if value is None])
    self.assertEqual(outcome['early_watch'],{'met':statuses.count('met'),'not_met':statuses.count('not_met'),
                     'unknown':29+statuses.count('unknown'),'first_met_at':times[statuses.index('met')]})
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
