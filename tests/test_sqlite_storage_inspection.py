import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
import jobs
from tools.inspect_sqlite_storage import inspect_backup

class BackupInspection(unittest.TestCase):
 def test_readonly_dry_run_and_consistent_counts(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'backup.sqlite'
   with sqlite3.connect(p) as c:
    c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,user_id INTEGER,status TEXT,created REAL,result TEXT,completed REAL,kind TEXT,lease TEXT,lease_until REAL)')
    c.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',[(i,1,'done',0,'secret',0,'ecb',None,None) for i in range(1,26)])
    c.execute("INSERT INTO jobs VALUES(26,1,'running',0,'protected',NULL,'ecb','lease',1)")
    c.execute('UPDATE jobs SET completed=NULL WHERE id=1')
    preview=jobs.cleanup_completed_jobs(c,40*86400)
   before=hashlib.sha256(p.read_bytes()).digest();r=inspect_backup(p,now=40*86400)
   self.assertEqual(before,hashlib.sha256(p.read_bytes()).digest())
   self.assertEqual(r['completed_jobs_eligible'],{'rows':5,'result_bytes':30})
   self.assertEqual(r['completed_jobs_eligible'],preview)
   self.assertEqual(r['completed_jobs_legacy_unknown'],1)
   self.assertEqual(r['page_count']*r['page_size'],r['file_bytes'])
   self.assertEqual(r['freelist_bytes'],r['freelist_count']*r['page_size'])
   self.assertNotIn('secret',str(r));self.assertNotIn('protected',str(r))
   self.assertIsNotNone(r['objects'])
   for suffix,reason in [('-wal','backup_has_wal'),('-journal','backup_has_journal')]:
    sidecar=Path(str(p)+suffix);sidecar.touch()
    with self.assertRaisesRegex(ValueError,reason):inspect_backup(p)
    sidecar.unlink()
 def test_legacy_database_reports_unknown_not_deletable(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old.sqlite'
   with sqlite3.connect(p) as c:
    c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,user_id INTEGER,status TEXT,created REAL,result TEXT)')
    c.executemany('INSERT INTO jobs VALUES(?,?,?,?,?)',[(i,1,'done',0,'old') for i in range(1,26)])
   r=inspect_backup(p,now=40*86400)
   self.assertEqual(r['completed_jobs_legacy_unknown'],25)
   self.assertEqual(r['completed_jobs_eligible'],{'rows':0,'result_bytes':0})

if __name__=='__main__':unittest.main()
