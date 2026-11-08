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
 def test_fallback_reports_why_and_does_not_modify_existing_sessions(self):
  with app.connect() as c:
   c.execute("INSERT INTO hw_strategy_preferences VALUES(1,'manual','missing','1.0.0',?)",(app.now(),))
  result=strategy_center.resolve(app.connect,1);self.assertEqual(result['mode'],'fallback');self.assertEqual(result['strategy_id'],'escape_momentum');self.assertIn('standardstrategien',result['reason'])
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
if __name__=='__main__':unittest.main()
