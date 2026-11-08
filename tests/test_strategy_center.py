import copy,json,tempfile,unittest
import app,hotwatch_engine,hotwatch_strategy,strategy_center
class Strategies(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=app.DB;app.DB=self.temp.name+'/db';app.init();app.create_user('test-password-long-enough')
  with app.connect() as c:c.execute("INSERT INTO users(username,salt,hash,role,active) VALUES('member','00','00','member',1)")
 def tearDown(self):app.DB=self.old;self.temp.cleanup()
 def test_default_and_user_scoped_selection(self):
  self.assertEqual(strategy_center.resolve(app.connect,1)['strategy_id'],'escape_momentum')
  strategy_center.save(app.connect,1,{'mode':'manual','strategy_id':'escape_momentum','version':'1.0.0'},app.now())
  self.assertEqual(strategy_center.resolve(app.connect,1)['mode'],'manual');self.assertEqual(strategy_center.resolve(app.connect,2)['mode'],'auto')
  strategy_center.save(app.connect,1,{'mode':'auto'},app.now());self.assertEqual(strategy_center.resolve(app.connect,1)['mode'],'auto')
 def test_unqualified_and_other_users_strategies_cannot_be_selected(self):
  spec=copy.deepcopy(hotwatch_strategy.BASELINE);spec.update(strategy_id='future-test',version='1.0.0');hotwatch_engine.upload_strategy(app.connect,1,'test',spec)
  for uid in (1,2):
   with self.assertRaises(ValueError):strategy_center.save(app.connect,uid,{'mode':'manual','strategy_id':'future-test','version':'1.0.0'},app.now())
  self.assertEqual(strategy_center.resolve(app.connect,1)['strategy_id'],'escape_momentum')
 def test_catalyst_drafts_are_private_versioned_and_never_qualified(self):
  data={'source_id':'escape_early_catalyst','source_version':'0.1.0','description':'Min nyhedsstrategi','parameters':{'momentum_pct':'0.5','min_relative_volume':'2','max_spread_pct':'0.4'}}
  first=strategy_center.draft(app.connect,1,data)
  data.update(source_id=first['strategy_id'],source_version=first['version']);data['parameters']['max_spread_pct']='0.3'
  second=strategy_center.draft(app.connect,1,data)
  self.assertEqual((first['version'],second['version']),('0.1.0','0.1.1'))
  with app.connect() as c:
   rows=c.execute('SELECT version,payload,validation_status FROM hw_strategies WHERE owner_id=1 ORDER BY version').fetchall()
   self.assertEqual([json.loads(r['payload'])['parameters']['max_spread_pct'] for r in rows],['0.4','0.3'])
   self.assertTrue(all(r['validation_status']=='schema_validated' for r in rows))
  with self.assertRaises(ValueError):strategy_center.save(app.connect,1,{'mode':'manual','strategy_id':first['strategy_id'],'version':second['version']},app.now())
  with self.assertRaises(ValueError):strategy_center.draft(app.connect,2,data)
 def test_example_respects_news_and_all_numeric_thresholds(self):
  m={'catalyst_verified':True,'catalyst_age_minutes':'10','return_3_pct':'0.5','relative_volume':'2','spread_pct':'0.4'}
  request={'strategy_id':'escape_early_catalyst','version':'0.1.0','metrics':m}
  self.assertTrue(strategy_center.simulate(app.connect,1,request)['matches'])
  for key,value in [('catalyst_verified',False),('catalyst_age_minutes','31'),('return_3_pct','0.1'),('relative_volume','0.5'),('spread_pct','2')]:
   changed=dict(m);changed[key]=value
   self.assertFalse(strategy_center.simulate(app.connect,1,{**request,'metrics':changed})['matches'])
  for value in ('NaN','Infinity','-1'):
   with self.assertRaises(ValueError):strategy_center.simulate(app.connect,1,{**request,'metrics':dict(m,relative_volume=value)})
 def test_early_v1_parameters_can_be_edited_as_private_immutable_version(self):
  initial=hotwatch_strategy.EARLY_CATALYST_V1;fields=strategy_center.EARLY_EDITABLE
  params={key:(str(initial['parameters'][key]).lower() if isinstance(initial['parameters'][key],bool) else str(initial['parameters'][key])) for key in fields};params.update(news_max_age_minutes='90',momentum_window_minutes='4',confirmation_count='3',heat_limit_pct='12',heat_high_pct='25')
  data={'source_id':'escape_early_catalyst','source_version':'1.0.0','description':'Min Early Catalyst','parameters':params}
  result=strategy_center.draft(app.connect,1,data)
  with app.connect() as c:
   saved=json.loads(c.execute('SELECT payload FROM hw_strategies WHERE owner_id=1 AND strategy_id=?',(result['strategy_id'],)).fetchone()[0]);base=json.loads(c.execute("SELECT payload FROM hw_strategies WHERE owner_id=0 AND strategy_id='escape_early_catalyst' AND version='1.0.0'").fetchone()[0])
  self.assertEqual(saved['parameters']['news_max_age_minutes'],90);self.assertEqual(saved['parameters']['momentum_window_minutes'],4);self.assertEqual(saved['parameters']['confirmation_count'],3);self.assertEqual(base['parameters']['news_max_age_minutes'],120)
  with self.assertRaises(ValueError):strategy_center.save(app.connect,1,{'mode':'manual','strategy_id':result['strategy_id'],'version':result['version']},app.now())
 def test_invalid_draft_leaves_library_unchanged(self):
  with self.assertRaises(ValueError):strategy_center.draft(app.connect,1,{'source_id':'escape_early_catalyst','source_version':'0.1.0','description':'test','parameters':{'momentum_pct':'1','min_relative_volume':'-2','max_spread_pct':'0.4'}})
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_strategies WHERE owner_id=1').fetchone()[0],0)
 def test_fallback_reports_why_and_does_not_modify_existing_sessions(self):
  with app.connect() as c:
   c.execute("INSERT INTO hw_strategy_preferences VALUES(1,'manual','missing','1.0.0',?)",(app.now(),))
  result=strategy_center.resolve(app.connect,1);self.assertEqual(result['mode'],'fallback');self.assertEqual(result['strategy_id'],'escape_momentum');self.assertIn('standardstrategien',result['reason'])
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
if __name__=='__main__':unittest.main()
