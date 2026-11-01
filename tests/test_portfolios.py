import tempfile,unittest
import app,portfolios
class Portfolios(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.previous=app.DB;app.DB=self.tmp.name+'/p.db';app.init();app.create_user('a-test-password-long')
  with app.connect() as c:c.execute("INSERT INTO users(username,salt,hash) VALUES('other','test','test')")
 def tearDown(self):app.DB=self.previous;self.tmp.cleanup()
 def test_empty_by_default_and_isolated(self):
  with app.connect() as c:
   self.assertEqual(portfolios.list_owned(c,1),[])
   pid=portfolios.create(c,1,'My collection')
   self.assertEqual(portfolios.list_owned(c,2),[])
   with self.assertRaises(ValueError):portfolios.rename(c,2,pid,'hijack')
   portfolios.rename(c,1,pid,'Renamed')
   self.assertEqual(portfolios.list_owned(c,1)[0]['name'],'Renamed')
 def test_reconcile_rename_add_remove_preserves_ids(self):
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'a','name':'First'},{'id':'b','name':'Same name'}])
   original={x['external_id']:x['id'] for x in portfolios.list_owned(c,1)}
   portfolios.replace_pluto(c,1,[{'id':'a','name':'Renamed'},{'id':'c','name':'Same name'}])
   rows={x['external_id']:x for x in portfolios.list_owned(c,1)}
   self.assertEqual(rows['a']['id'],original['a']);self.assertEqual(rows['a']['name'],'Renamed');self.assertEqual(rows['b']['active'],0);self.assertEqual(rows['c']['active'],1)
   self.assertEqual(portfolios.list_owned(c,2),[])
 def test_proposal_requires_owned_active_id(self):
  with app.connect() as c:pid=portfolios.create(c,1,'Any custom name')
  proposal={'portfolio_id':pid,'ticker':'TEST','quantity':1,'price':10,'stop':9,'target':11,'costs':0,'fx':1}
  with self.assertRaises(ValueError):app.proposal(proposal,2)
  app.proposal(proposal,1)
  with app.connect() as c:
   portfolios.rename(c,1,pid,'Changed name');row=c.execute('SELECT portfolio,portfolio_id FROM proposals').fetchone()
   self.assertEqual(row['portfolio'],'Any custom name');self.assertEqual(row['portfolio_id'],pid)
   c.execute('UPDATE portfolios SET active=0 WHERE id=?',(pid,))
  with self.assertRaises(ValueError):app.proposal(proposal,1)
 def test_incomplete_listing_does_not_archive(self):
  with app.connect() as c:
   portfolios.replace_pluto(c,1,[{'id':'a','name':'Existing'}])
   with self.assertRaises(ValueError):portfolios.replace_pluto(c,1,[{'id':'x','name':'X'},{'id':'x','name':'Y'}])
   self.assertEqual(portfolios.list_owned(c,1)[0]['active'],1)
