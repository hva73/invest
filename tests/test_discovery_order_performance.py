import json
import sqlite3
import unittest

from hotwatch_service import discovery_candidate_order


class DiscoveryOrder(unittest.TestCase):
 def test_order_matches_sql_for_candidate_positions_and_absent_candidates(self):
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
  db.execute('CREATE TABLE samples (id INTEGER, generated INTEGER, candidate_id TEXT, payload TEXT)')
  for ident,generated,candidates,links in [
   (3,20,['z','a','z'],['a','missing','z']),
   (2,20,['c','b'],['b','c']),
   (1,10,['e','d'],['d','e'])]:
   payload=json.dumps({'candidates':[{'candidate_id':x} for x in candidates]})
   db.executemany('INSERT INTO samples VALUES (?,?,?,?)',[(ident,generated,x,payload) for x in links])
  common='SELECT * FROM samples ORDER BY generated DESC,id DESC'
  rows=db.execute(common).fetchall()
  previous=db.execute(common+",(SELECT CAST(j.key AS INTEGER) FROM json_each(samples.payload,'$.candidates') j WHERE json_extract(j.value,'$.candidate_id')=samples.candidate_id LIMIT 1)").fetchall()
  self.assertEqual([(r['id'],r['candidate_id']) for r in discovery_candidate_order(rows)],[(r['id'],r['candidate_id']) for r in previous])


if __name__=='__main__':unittest.main()
