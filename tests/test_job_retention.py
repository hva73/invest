import sqlite3
import unittest
import jobs

class CompletedJobRetention(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:')
  self.c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,user_id INTEGER,status TEXT,created REAL,result TEXT,completed REAL,kind TEXT,lease TEXT,lease_until REAL)')
  self.c.execute('CREATE TABLE job_retention_state(id INTEGER PRIMARY KEY,last_run REAL NOT NULL)')
  self.now=100*86400
  self.old=self.now-40*86400
  self.c.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',[(i,1,'done',self.old,'ok',self.old,'ecb',None,None) for i in range(1,26)])
  self.c.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',[
   (30,1,'queued',0,'q',None,'ecb',None,None),
   (31,1,'running',0,'r',None,'ecb','lease',1),
   (32,1,'failed',0,'f',None,'ecb',None,None),
   (33,2,'done',0,'last',0,'ecb',None,None),
   (34,1,'done',self.now-86400,'recent',self.now-86400,'ecb',None,None)])
  self.c.commit()
 def tearDown(self):self.c.close()
 def test_dry_run_and_retention_preserve_pending_failed_recent_and_last_20(self):
  before=self.c.execute('SELECT * FROM jobs ORDER BY id').fetchall()
  preview=jobs.cleanup_completed_jobs(self.c,self.now)
  self.assertEqual(before,self.c.execute('SELECT * FROM jobs ORDER BY id').fetchall())
  self.assertEqual(preview,{'rows':9,'result_bytes':18})
  result=jobs.cleanup_completed_jobs(self.c,self.now,dry_run=False)
  self.assertEqual(result,preview)
  remaining=self.c.execute('SELECT id FROM jobs ORDER BY id').fetchall()
  self.assertEqual(remaining,[(i,) for i in list(range(10,26))+[30,31,32,33,34]])
  self.assertEqual(jobs.cleanup_completed_jobs(self.c,self.now,dry_run=False)['rows'],0)
 def test_work_is_bounded(self):
  result=jobs.cleanup_completed_jobs(self.c,self.now,dry_run=False,limit=2)
  self.assertEqual(result['rows'],2)
  self.assertEqual(self.c.execute('SELECT count(*) FROM jobs').fetchone()[0],28)
  for n in (0,-1,501,True):
   with self.assertRaises(ValueError):jobs.cleanup_completed_jobs(self.c,self.now,limit=n)
 def test_legacy_recent_completion_unknown_kind_and_lease_preserved(self):
  self.c.execute('UPDATE jobs SET completed=NULL WHERE id=1')
  self.c.execute('UPDATE jobs SET completed=? WHERE id=2',(self.now-1,))
  self.c.execute("UPDATE jobs SET kind='unknown' WHERE id=3")
  self.c.execute("UPDATE jobs SET lease='stale' WHERE id=4")
  self.c.execute("UPDATE jobs SET lease_until=1 WHERE id=5")
  result=jobs.cleanup_completed_jobs(self.c,self.now,dry_run=False)
  self.assertEqual(result['rows'],4)
  self.assertEqual(self.c.execute('SELECT id FROM jobs WHERE id<=9 ORDER BY id').fetchall(),[(i,) for i in range(1,6)])
 def test_daily_maintenance_is_disabled_by_default_and_serialized(self):
  self.assertIsNone(jobs.maintain_completed_jobs(lambda:self.c,self.now))
  self.assertEqual(self.c.execute('SELECT count(*) FROM jobs').fetchone()[0],30)
  self.assertEqual(jobs.maintain_completed_jobs(lambda:self.c,self.now,enabled=True)['rows'],9)
  self.assertIsNone(jobs.maintain_completed_jobs(lambda:self.c,self.now+3600,enabled=True))
  self.assertEqual(jobs.maintain_completed_jobs(lambda:self.c,self.now+86400,enabled=True)['rows'],0)

class CompletionMigration(unittest.TestCase):
 def test_legacy_schema_migration_and_real_job_completion(self):
  c=sqlite3.connect(':memory:')
  self.addCleanup(c.close)
  c.row_factory=sqlite3.Row
  c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,user_id INTEGER NOT NULL,dedupe TEXT NOT NULL UNIQUE,status TEXT NOT NULL,available REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,lease TEXT,lease_until REAL,result TEXT,created REAL NOT NULL)')
  c.execute("INSERT INTO jobs(kind,user_id,dedupe,status,available,created,result) VALUES('ecb',1,'legacy','done',0,0,'preserve')")
  jobs.init(c);jobs.init(c)
  c.commit()
  self.assertIsNone(c.execute("SELECT completed FROM jobs WHERE dedupe='legacy'").fetchone()[0])
  jobs.enqueue(c,'ecb',1,'new',0)
  c.commit()
  payload={'source_url':jobs.ECB_URL,'base':'EUR','rates':{'DKK':7.5},'source_date':'2026-01-01','observed':'2026-01-01T00:00:00+00:00'}
  self.assertTrue(jobs.run_one(lambda:c,lambda:payload,at=120))
  self.assertEqual(tuple(c.execute("SELECT status,completed FROM jobs WHERE dedupe='new'").fetchone()),('done',120))
  self.assertIsNone(c.execute("SELECT completed FROM jobs WHERE dedupe='legacy'").fetchone()[0])

if __name__=='__main__':unittest.main()
