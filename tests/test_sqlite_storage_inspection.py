import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from tools.inspect_sqlite_storage import inspect_backup

class BackupInspection(unittest.TestCase):
 def test_readonly_dry_run_and_consistent_counts(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'backup.sqlite'
   with sqlite3.connect(p) as c:
    c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,user_id INTEGER,status TEXT,created REAL,result TEXT)')
    c.executemany('INSERT INTO jobs VALUES(?,?,?,?,?)',[(i,1,'done',0,'secret') for i in range(1,26)])
    c.execute("INSERT INTO jobs VALUES(26,1,'running',0,'protected')")
   before=hashlib.sha256(p.read_bytes()).digest();r=inspect_backup(p,now=40*86400)
   self.assertEqual(before,hashlib.sha256(p.read_bytes()).digest())
   self.assertEqual(r['completed_jobs_eligible'],{'rows':6,'result_bytes':36})
   self.assertEqual(r['page_count']*r['page_size'],r['file_bytes'])
   self.assertNotIn('secret',str(r));self.assertNotIn('protected',str(r))
   self.assertIsNotNone(r['objects'])
   Path(str(p)+'-wal').touch()
   with self.assertRaisesRegex(ValueError,'backup_has_wal'):inspect_backup(p)

if __name__=='__main__':unittest.main()
