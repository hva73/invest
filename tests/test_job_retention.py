import sqlite3
import unittest
import jobs

class CompletedJobRetention(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:')
  self.c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,user_id INTEGER,status TEXT,created REAL,result TEXT)')
  self.now=100*86400
  self.c.executemany('INSERT INTO jobs VALUES(?,?,?,?,?)',[(i,1,'done',self.now-40*86400,'ok') for i in range(1,26)])
  self.c.executemany('INSERT INTO jobs VALUES(?,?,?,?,?)',[(30,1,'queued',0,'q'),(31,1,'running',0,'r'),(32,1,'failed',0,'f'),(33,2,'done',0,'last'),(34,1,'done',self.now-86400,'recent')])
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

if __name__=='__main__':unittest.main()
