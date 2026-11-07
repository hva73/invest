import json,tempfile,unittest
from datetime import datetime,timezone,timedelta
import app,portfolios,portfolio_data,dashboard_projection as dashboard

class PortfolioValueChart(unittest.TestCase):
 def setUp(self):
  self.old=app.DB;self.temp=tempfile.TemporaryDirectory();app.DB=self.temp.name+'/db';app.init();app.create_user('test-password-long-enough')
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:root','name':'Root','kind':'portfolio'},{'id':'collections:ai','name':'AI','kind':'collection','parent_external_id':'portfolios:root'}])
   owned=portfolios.list_owned(c,1);self.root=next(p['id'] for p in owned if p['kind']=='portfolio');self.child=next(p['id'] for p in owned if p['kind']=='collection')
 def tearDown(self):app.DB=self.old;self.temp.cleanup()
 def save(self,pid,value,at,currency='DKK',result=None):
  data={'observed':at.isoformat(),'value':{'value':{'amount':value,'currency':currency},'source_time':at.isoformat(),'reported_result':{'amount':result,'currency':currency}},'positions':[],'positions_complete':True,'complete':True}
  with app.connect() as c:portfolio_data.save(c,1,pid,data)
 def test_root_history_does_not_double_count_collection_and_reports_real_points(self):
  self.save(self.root,'1000',self.now-timedelta(minutes=10),result='20');self.save(self.child,'300',self.now-timedelta(minutes=9));self.save(self.root,'1100',self.now,result='30')
  with app.connect() as c:
   history=dashboard.portfolio_value_history(c,1,self.now);total=c.execute('SELECT count(*) FROM display_portfolio_values').fetchone()[0]
  self.assertEqual(total,2);self.assertEqual([p['amount'] for p in history['periods']['week']],['1000','1100']);self.assertEqual(history['reported_result'],{'amount':'30','currency':'DKK'});self.assertEqual([p['reported_result'] for p in history['periods']['week']],['20','30'])
 def test_missing_currency_mixed_roots_and_failed_snapshots_do_not_fabricate_totals(self):
  self.save(self.root,'1000',self.now)
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:root','name':'Root','kind':'portfolio'},{'id':'portfolios:other','name':'Other','kind':'portfolio'}])
   other=next(p['id'] for p in portfolios.list_owned(c,1) if p['name']=='Other')
   self.assertIsNone(dashboard.portfolio_value_snapshot(c,1))
  self.save(other,'100',self.now,currency='USD')
  with app.connect() as c:self.assertIsNone(dashboard.portfolio_value_snapshot(c,1))
  self.save(other,'100',self.now+timedelta(seconds=1),currency='DKK')
  with app.connect() as c:
   value=dashboard.portfolio_value_snapshot(c,1);self.assertEqual(str(value['amount']),'1100');self.assertIsNone(value['reported_result'])
   c.execute('UPDATE portfolio_snapshots SET last_error=? WHERE portfolio_id=?',('unavailable',other));self.assertIsNone(dashboard.portfolio_value_snapshot(c,1))
 def test_scope_change_does_not_compare_different_portfolios(self):
  self.save(self.root,'1000',self.now-timedelta(minutes=2))
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'portfolios:root','name':'Root','kind':'portfolio'},{'id':'portfolios:second','name':'Second','kind':'portfolio'}]);second=next(p['id'] for p in portfolios.list_owned(c,1) if p['name']=='Second')
  self.save(second,'200',self.now-timedelta(minutes=1));self.save(self.root,'1100',self.now)
  with app.connect() as c:points=dashboard.portfolio_value_history(c,1,self.now)['periods']['week']
  self.assertEqual([p['amount'] for p in points],['1200','1300'])
 def test_history_starts_with_the_first_actual_observation(self):
  self.save(self.root,'1000',self.now-timedelta(minutes=2));self.save(self.root,'1010',self.now-timedelta(minutes=1));self.save(self.root,'1020',self.now)
  with app.connect() as c:history=dashboard.portfolio_value_history(c,1,self.now)
  points=history['periods']['week'];self.assertEqual(points[0]['amount'],'1000');self.assertEqual(points[-1]['amount'],'1020')
 def test_recorded_history_remains_visible_after_broker_error(self):
  self.save(self.root,'1000',self.now,result='20')
  with app.connect() as c:
   c.execute('UPDATE portfolio_snapshots SET last_error=? WHERE portfolio_id=?',('unavailable',self.root))
   history=dashboard.portfolio_value_history(c,1,self.now)
  self.assertEqual([p['amount'] for p in history['periods']['week']],['1000']);self.assertIsNone(history['reported_result'])

if __name__=='__main__':unittest.main()
