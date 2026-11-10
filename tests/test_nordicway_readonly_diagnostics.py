import importlib.util,json,sqlite3,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('nordicway_readonly_diagnostics',Path(__file__).resolve().parents[1]/'tools/nordicway_readonly_diagnostics.py')
diag=importlib.util.module_from_spec(spec);spec.loader.exec_module(diag)

class Diagnostics(unittest.TestCase):
 def test_read_only_aggregate_never_returns_private_values(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'var').mkdir();db=root/'var/escape.db';(root/'BUILD_COMMIT').write_text('a'*40)
   with sqlite3.connect(db) as c:
    c.execute('CREATE TABLE hw_heartbeat(id INTEGER,updated TEXT,status TEXT)')
    c.execute("INSERT INTO hw_heartbeat VALUES(1,'2026-11-10T21:00:00+00:00','running')")
    c.execute('CREATE TABLE hw_supervisor_status(id INTEGER,updated TEXT,status TEXT)')
    c.execute("INSERT INTO hw_supervisor_status VALUES(1,'2026-11-10T21:00:00+00:00','running')")
    c.execute('CREATE TABLE hw_sessions(id INTEGER,is_test INTEGER,status TEXT,next_due REAL,lease_until REAL,private TEXT)')
    c.execute("INSERT INTO hw_sessions VALUES(1,0,'ACTIVE',0,0,'secret-private-position')")
    c.execute("INSERT INTO hw_sessions VALUES(2,1,'ERROR',0,0,'secret-test')")
    c.execute("INSERT INTO hw_sessions VALUES(3,0,'ACTIVE',0,9999999999,'leased-job')")
   before=db.read_bytes()
   with patch.object(diag,'_processes',return_value={'status':'ok','counts':{'worker':1}}):
    out=diag.inspect(root,datetime(2026,11,10,21,0,10,tzinfo=timezone.utc))
   self.assertEqual(db.read_bytes(),before)
   self.assertEqual(out['database']['worker'],{'status':'running','age_seconds':10.0})
   self.assertEqual(out['database']['session_counts'],{'ACTIVE':2})
   self.assertEqual(out['database']['due_count'],1)
   self.assertEqual(out['installation']['declared_commit'],'a'*40)
   self.assertNotIn('secret',json.dumps(out))
   self.assertEqual(out['storage']['account_quota'],'unknown')
 def test_missing_or_live_journal_does_not_open_database(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);db=root/'var/escape.db';db.parent.mkdir()
   with patch.object(diag.sqlite3,'connect') as connect:
    self.assertEqual(diag._database(db,datetime.now(timezone.utc))['status'],'unavailable');connect.assert_not_called()
    db.write_bytes(b'test');Path(str(db)+'-wal').write_bytes(b'test')
    self.assertEqual(diag._database(db,datetime.now(timezone.utc))['reason'],'database_journal_present');connect.assert_not_called()
 def test_unrecognized_database_and_wal_header_are_not_opened(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Path(tmp)/'db';now=datetime.now(timezone.utc)
   with patch.object(diag.sqlite3,'connect') as connect:
    db.write_bytes(b'bad');self.assertEqual(diag._database(db,now)['reason'],'database_header_invalid')
    db.write_bytes(b'SQLite format 3\x00'+b'\x10\x00\x02\x02');self.assertEqual(diag._database(db,now)['reason'],'database_journal_mode_unsupported')
    connect.assert_not_called()
 def test_process_arguments_are_not_returned(self):
  result=type('Result',(),{'stdout':'python /app/hotwatch_service.py --private secret-value\npython /app/hotwatch_supervisor.py --run\n'})()
  with patch.object(diag.subprocess,'run',return_value=result):out=diag._processes()
  self.assertEqual(out['counts']['worker'],1);self.assertEqual(out['counts']['supervisor'],1)
  self.assertNotIn('secret-value',json.dumps(out))
if __name__=='__main__':unittest.main()
