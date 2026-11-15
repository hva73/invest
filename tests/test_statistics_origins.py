import json, sqlite3, tempfile, unittest
from pathlib import Path
from statistics_origins import signal_order_sides
from realized_statistics import project

class OriginTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'db')
  with self.connect() as c:
   c.execute('CREATE TABLE broker_proposals(user_id INTEGER,portfolio_id INTEGER,kind TEXT,status TEXT,signal_event_id TEXT,intent_id TEXT,payload TEXT,response TEXT)')
 def tearDown(self):self.tmp.cleanup()
 def connect(self):return sqlite3.connect(self.path)
 def insert(self, *, uid=1, depot=1, event='hw-'+'a'*24, intent='intent-1', side='BUY', oid='broker-1', status='ACCEPTED', response_intent='intent-1'):
  with self.connect() as c:c.execute('INSERT INTO broker_proposals VALUES(?,?,?,?,?,?,?,?)',(uid,depot,'direct','sent',event,intent,json.dumps({'orders':[{'side':side}]}),json.dumps({'orderIntentId':response_intent,'orderId':oid,'status':status})))
 def test_explicit_accepted_intent_and_executed_order_required(self):
  self.insert(); evidence=signal_order_sides(self.connect,1,1);self.assertEqual(evidence,{'broker-1':'BUY'})
  buy={'id':'broker-1','side':'BUY','status':'FILLED','filledQuantity':'1','filledAveragePrice':'10','createdAt':'2026-01-01T00:00:00Z','scope':'ROOT','asset':{'ticker':'A','name':'A','currency':'USD'}}
  sell=dict(buy,id='other',side='SELL',createdAt='2026-01-02T00:00:00Z')
  row=project([buy,sell],signal_order_sides=evidence)['items'][0]
  self.assertEqual((row['buy_origin'],row['sell_origin']),('signal','unknown'))
  self.assertEqual(project([buy,sell],signal_order_sides={'broker-1':'SELL'})['items'][0]['buy_origin'],'unknown')
 def test_user_depot_pending_and_ambiguous_are_unknown(self):
  self.insert(uid=2,oid='foreign');self.insert(depot=2,oid='other');self.insert(oid='pending',status='PENDING');self.insert(oid='bad',response_intent='wrong');self.insert(oid='dup');self.insert(oid='dup')
  self.assertEqual(signal_order_sides(self.connect,1,1),{})
 def test_missing_schema_is_unknown(self):
  with self.connect() as c:c.execute('DROP TABLE broker_proposals')
  self.assertEqual(signal_order_sides(self.connect,1,1),{})
