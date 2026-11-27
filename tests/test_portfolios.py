import sqlite3
import tempfile,unittest
from contextlib import closing
from unittest.mock import patch
import app,portfolios


def measure_owned_listing(c, user_id):
    statements = []
    steps = 0

    def count_step():
        nonlocal steps
        steps += 1
        return 0

    c.set_trace_callback(statements.append)
    c.set_progress_handler(count_step, 1)
    try:
        rows = portfolios.list_owned(c, user_id)
    finally:
        c.set_progress_handler(None, 0)
        c.set_trace_callback(None)
    query, = statements
    plan = [row['detail'] for row in c.execute('EXPLAIN QUERY PLAN ' + query)]
    return rows, plan, steps


class Portfolios(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.previous=app.DB;app.DB=self.tmp.name+'/p.db'
  # Exercise the app's portfolio and proposal migrations independently of HOT WATCH.
  with patch('hotwatch_engine.init'):
   app.init()
  with app.connect() as c:
   c.executemany('INSERT INTO users(username,role) VALUES(?,?)',
                 [('owner','admin'),('other','member')])
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


class OwnedListingIndex(unittest.TestCase):
    def test_owned_listing_index_on_existing_portfolios(self):
        with closing(sqlite3.connect(":memory:")) as c:
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
            c.execute('CREATE TABLE proposals(user_id INTEGER, portfolio TEXT)')
            portfolios.init(c)
            # Model an existing installation before the listing index was added.
            c.execute('DROP INDEX IF EXISTS portfolios_owner_order')
            c.executemany('INSERT INTO users VALUES(?)', ((i,) for i in range(1, 101)))
            owner = 61
            expected = []
            records = []
            for i in range(1, 101):
                for j in range(32):
                    pid = len(records) + 1
                    name = ('a', 'A', 'B', 'b')[j % 4]
                    active = int(j % 3 != 0)
                    source = 'pluto' if j % 2 else 'local'
                    external_id = str(j) if source == 'pluto' else None
                    records.append((pid, i, name, active, source, external_id))
                    if i == owner:
                        expected.append((-active, name, pid))
            c.executemany('INSERT INTO portfolios(id,user_id,name,active,source,external_id,updated) '
                          'VALUES(?,?,?,?,?,?,0)', records)

            before, old_plan, old_steps = measure_owned_listing(c, owner)
            self.assertEqual([r['id'] for r in before], [pid for _, _, pid in sorted(expected)])
            self.assertIn('TEMP B-TREE', ' '.join(old_plan))

            portfolios.init(c)
            after, plan, steps = measure_owned_listing(c, owner)
            self.assertEqual(after, before)
            self.assertIn('USING INDEX portfolios_owner_order', ' '.join(plan))
            self.assertNotIn('TEMP B-TREE', ' '.join(plan))
            self.assertLess(steps, old_steps)

            version = c.execute('PRAGMA schema_version').fetchone()[0]
            portfolios.init(c)
            self.assertEqual(c.execute('PRAGMA schema_version').fetchone()[0], version)
            self.assertEqual(portfolios.list_owned(c, owner), after)
