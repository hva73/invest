import tempfile,time,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import app,jobs
# Synthetic XML fixture used only in tests, never shipped as application data.
XML=b'<Envelope><Cube><Cube time="2026-01-02"><Cube currency="DKK" rate="7.5"/><Cube currency="USD" rate="1.1"/></Cube></Cube></Envelope>'
class Jobs(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.previous=app.DB;app.DB=self.tmp.name+'/jobs.db';app.init();app.create_user('test-password-long');self.uid=1
 def tearDown(self):app.DB=self.previous;self.tmp.cleanup()
 def payload(self):return jobs.parse_ecb(XML,datetime(2026,1,3,tzinfo=timezone.utc))
 def test_parser_rejects_bad_data(self):
  self.assertEqual(self.payload()['base'],'EUR')
  for xml in [XML.replace(b'7.5',b'NaN'),XML.replace(b'DKK',b'XXX'),XML.replace(b'2026-01-02',b'2099-01-02'),b'<!DOCTYPE x>'+XML]:
   with self.assertRaises(ValueError):jobs.parse_ecb(xml,datetime(2026,1,3,tzinfo=timezone.utc))
 def test_deduplication_and_resume(self):
  with app.connect() as c:jobs.enqueue(c,'ecb',1,'same',0);jobs.enqueue(c,'ecb',1,'same',0)
  self.assertTrue(jobs.run_one(app.connect,self.payload,at=1));self.assertFalse(jobs.run_one(app.connect,self.payload,at=2))
  with app.connect() as c:jobs.enqueue(c,'ecb',1,'next',0)
  jobs.run_one(app.connect,self.payload,at=2)
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM fx_snapshots').fetchone()[0],1)
  app.init();self.assertIsNotNone(jobs.status(app.connect,1)['fx'])
 def test_failure_retry_and_exhaustion(self):
  with app.connect() as c:jobs.enqueue(c,'ecb',1,'broken',0)
  def failed():raise OSError('secret-never-log-this')
  for when in [0,901,1802]:jobs.run_one(app.connect,failed,at=when)
  with app.connect() as c:
   row=dict(c.execute('SELECT * FROM jobs').fetchone());self.assertEqual(row['status'],'failed');self.assertEqual(row['attempts'],3);self.assertNotIn('secret',row['result'])
 def test_crash_lease_recovers(self):
  with app.connect() as c:
   jobs.enqueue(c,'ecb',1,'crash',0);c.execute("UPDATE jobs SET status='running',attempts=1,lease='old',lease_until=1")
  jobs.run_one(app.connect,self.payload,at=2)
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM jobs').fetchone()[0],'done')
 def test_schedule_handles_danish_summer_time(self):
  for stamp in ['2026-01-05T07:00:00+00:00','2026-07-05T06:00:00+00:00']:
   at=datetime.fromisoformat(stamp);jobs.schedule(app.connect,at);jobs.schedule(app.connect,at)
  with app.connect() as c:
   self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='report'").fetchone()[0],2)
   self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='ecb'").fetchone()[0],2)
 def test_report_privacy(self):
  with app.connect() as c:
   c.execute("INSERT INTO users(username,salt,hash,role) VALUES('other','test','test','member')")
   jobs.enqueue(c,'report',1,'owner-report',0)
  jobs.run_one(app.connect,at=0)
  self.assertEqual(len(jobs.status(app.connect,1)['reports']),1);self.assertEqual(jobs.status(app.connect,2)['reports'],[])
  self.assertIn('ikke en markedsanalyse',jobs.status(app.connect,1)['reports'][0]['body'])
