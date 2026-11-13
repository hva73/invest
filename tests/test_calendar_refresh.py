import ast,copy,hashlib,json,sqlite3,threading,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch

def extract(path,cls,names,namespace):
 tree=ast.parse(Path(path).read_text())
 c=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
 c.body=[x for x in c.body if isinstance(x,ast.FunctionDef) and x.name in names]
 exec(compile(ast.Module(body=[c],type_ignores=[]),path,'exec'),namespace)
 return namespace[cls]

NOW=datetime(2026,11,13,14,tzinfo=timezone.utc)
stamp=lambda x:datetime.fromisoformat(x)
ns={'utc':lambda:NOW,'stamp':stamp,'json':json}
Adapter=extract('hotwatch_adapters.py','EODHDAdapter',{'market_status'},ns)
fns={'hashlib':hashlib,'time':time,'threading':threading,'copy':copy,'datetime':datetime,'timezone':timezone,'re':__import__('re'),
     '_status_cache':{},'_status_locks':[threading.Lock() for _ in range(32)],'STATUS_CACHE_TTL_S':60,'_result':lambda status,endpoint,**kw:{'status':status,**kw}}
Feeds=extract('eodhd_feeds.py','EODHDFeeds',{'market_status','market_status_for_scan'},fns)
class TestCalendar(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.execute('create table hw_exchange_status(exchange text,received text,is_open int)')
  self.db.execute('create table hw_exchange_calendar(exchange text,received text,timezone text,calendar text)')
  self.adapter=Adapter();self.adapter.connect=lambda:self.db
  self.feed=Feeds();self.feed._key='fixture';self.feed._shared_status=True;self.calls=[]
  self.feed._market_status_uncached=lambda exchange:self.calls.append(exchange) or {'status':'OK','received_at':datetime.now(timezone.utc).isoformat(),'exchange_open':True,'calendar':{}}
  fns['_status_cache'].clear()
 def put(self,age):
  stamp=(NOW-timedelta(seconds=age)).isoformat()
  self.db.execute('delete from hw_exchange_status');self.db.execute('delete from hw_exchange_calendar')
  self.db.execute('insert into hw_exchange_status values(?,?,?)',('US',stamp,1))
  self.db.execute('insert into hw_exchange_calendar values(?,?,?,?)',('US',stamp,'America/New_York',json.dumps({'open':'09:30'})))
 def test_recent_db_reused_without_changing_received_at(self):
  self.put(20);r=self.adapter.market_status(self.feed,'US',120)
  self.assertEqual(r['received_at'],(NOW-timedelta(seconds=20)).isoformat());self.assertEqual(self.calls,[])
 def test_110_second_db_refreshes(self):
  self.put(110);r=self.adapter.market_status(self.feed,'US',120)
  self.assertEqual(r['status'],'OK');self.assertEqual(self.calls,['US']);self.assertNotEqual(r['received_at'],(NOW-timedelta(seconds=110)).isoformat())
 def test_cache_respects_smaller_freshness_budget(self):
  self.put(110);key=(hashlib.sha256(b'fixture').digest(),'US')
  old=(datetime.now(timezone.utc)-timedelta(seconds=70)).isoformat()
  fns['_status_cache'][key]=(time.monotonic()-5,{'status':'OK','received_at':old})
  self.adapter.market_status(self.feed,'US',120);self.assertEqual(self.calls,['US'])
 def test_error_is_not_relabelled_fresh(self):
  self.put(110);self.feed._market_status_uncached=lambda exchange:{'status':'LOCAL_BUDGET_EXHAUSTED'}
  r=self.adapter.market_status(self.feed,'US',120);self.assertEqual(r,{'status':'LOCAL_BUDGET_EXHAUSTED'})
 def test_generic_mock_uses_existing_contract_and_preserves_error(self):
  self.adapter.connect=None;client=Mock()
  client.market_status.return_value={'status':'LOCAL_BUDGET_EXHAUSTED'}
  self.assertEqual(self.adapter.market_status(client,'US',120),{'status':'LOCAL_BUDGET_EXHAUSTED'})
  client.market_status.assert_called_once_with('US')
 def test_regular_status_keeps_existing_cache_behavior(self):
  key=(hashlib.sha256(b'fixture').digest(),'US')
  fns['_status_cache'][key]=(time.monotonic()-5,{'status':'OK'})
  self.assertEqual(self.feed.market_status('US'),{'status':'OK'});self.assertEqual(self.calls,[])
 def test_future_db_and_mismatched_records_are_not_reused(self):
  self.put(-2);self.adapter.market_status(self.feed,'US',120);self.assertEqual(self.calls,['US'])
  self.calls.clear();fns['_status_cache'].clear();self.put(10)
  self.db.execute("update hw_exchange_calendar set received=?",(NOW.isoformat(),))
  self.adapter.market_status(self.feed,'US',120);self.assertEqual(self.calls,['US'])
 def test_fresh_shared_cache_keeps_original_receipt_time(self):
  self.put(110);key=(hashlib.sha256(b'fixture').digest(),'US')
  received=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat()
  fns['_status_cache'][key]=(time.monotonic()-5,{'status':'OK','received_at':received})
  result=self.adapter.market_status(self.feed,'US',120)
  self.assertEqual(result['received_at'],received);self.assertEqual(self.calls,[])
 def test_short_budget_never_uses_old_shared_cache(self):
  self.put(16);key=(hashlib.sha256(b'fixture').digest(),'US')
  old=(datetime.now(timezone.utc)-timedelta(seconds=20)).isoformat()
  fns['_status_cache'][key]=(time.monotonic()-5,{'status':'OK','received_at':old})
  self.adapter.market_status(self.feed,'US',30);self.assertEqual(self.calls,['US'])
if __name__=='__main__':unittest.main()
