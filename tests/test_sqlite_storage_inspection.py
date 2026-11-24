import hashlib
import io
import tarfile
import sqlite3
import tempfile
import unittest
from pathlib import Path
import jobs
from tools.inspect_sqlite_storage import inspect_backup, inspect_archive_database

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

 def test_archive_inspects_only_independently_verified_database(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'copy.sqlite'
   with sqlite3.connect(p) as c:
    c.execute('CREATE TABLE evidence(payload TEXT)')
    c.execute("INSERT INTO evidence VALUES('private content')")
   raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest()
   name='20261124-183000-test';archive=Path(d)/'backup.tar.gz'
   def build(items):
    with tarfile.open(archive,'w:gz') as t:
     for path,content in items:
      info=tarfile.TarInfo(path);info.size=len(content)
      t.addfile(info,io.BytesIO(content))
   member=name+'/escape.db'
   build([(member,raw),(name+'/manifest.json',b'{}')])
   r=inspect_archive_database(archive,name,digest,len(raw))
   self.assertEqual(r['source'],'verified_archive_database_member')
   self.assertEqual(r['file_bytes'],len(raw))
   self.assertNotIn('private content',str(r))
   with self.assertRaisesRegex(ValueError,'database_hash_mismatch'):
    inspect_archive_database(archive,name,'0'*64,len(raw))
   build([(member,raw),(member,raw)])
   with self.assertRaisesRegex(ValueError,'database_member_mismatch'):
    inspect_archive_database(archive,name,digest,len(raw))
   build([(member,raw),(name+'/../unsafe',b'bad')])
   with self.assertRaisesRegex(ValueError,'unsafe_archive_member'):
    inspect_archive_database(archive,name,digest,len(raw))
   build([(name+'/manifest.json',b'{}')])
   with self.assertRaisesRegex(ValueError,'database_member_missing'):
    inspect_archive_database(archive,name,digest,len(raw))

if __name__=='__main__':unittest.main()
