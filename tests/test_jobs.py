import tempfile,time,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import app,jobs,portfolio_data
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
 def test_status_searches_owner_history_for_latest_twenty_jobs(self):
  own_ids=[]
  with app.connect() as c:
   owner=c.execute("INSERT INTO users(username,salt,hash) VALUES('other','test','test')").lastrowid
   for i in range(25):
    for uid in (owner,self.uid):
     job=c.execute("""INSERT INTO jobs(kind,user_id,dedupe,status,available,created)
                      VALUES('report',?,?,'done',0,0)""",(uid,f'history-{uid}-{i}'))
     if uid==owner:
      own_ids.append(job.lastrowid)

  statements=[]
  def traced_connect():
   c=app.connect()
   c.set_trace_callback(statements.append)
   return c
  rows=jobs.status(traced_connect,owner)['jobs']
  self.assertEqual([row['id'] for row in rows],list(reversed(own_ids[-20:])))
  query,=[sql for sql in statements if 'FROM jobs ' in sql]
  with app.connect() as c:
   plan='\n'.join(row['detail'] for row in c.execute('EXPLAIN QUERY PLAN '+query))
  self.assertRegex(plan,r'SEARCH jobs USING INDEX jobs_user_id_id_desc \(user_id=\?\)')
 def test_idle_preflight_searches_both_queue_indexes(self):
  with app.connect() as c:
   c.executemany("""INSERT INTO jobs(kind,user_id,dedupe,status,available,created)
                    VALUES('report',1,?,'done',0,0)""",[(f'history-{i}',) for i in range(128)])
   jobs.enqueue(c,'report',1,'future',20)
   jobs.enqueue(c,'report',1,'occupied',0)
   c.execute("UPDATE jobs SET status='running',attempts=1,lease='owner',lease_until=20 WHERE dedupe='occupied'")

  statements=[]
  def traced_connect():
   c=app.connect()
   c.set_trace_callback(statements.append)
   return c
  self.assertFalse(jobs.run_one(traced_connect,at=10))
  preflight,=[sql for sql in statements if sql.lstrip().upper().startswith('SELECT')]
  with app.connect() as c:
   plan='\n'.join(row['detail'] for row in c.execute('EXPLAIN QUERY PLAN '+preflight))
   for index,column in [('jobs_queued_available','available'),('jobs_running_lease_until','lease_until')]:
    self.assertRegex(plan,rf'SEARCH jobs USING (?:COVERING )?INDEX {index} \({column}<\?\)')
    self.assertEqual(c.execute("SELECT partial FROM pragma_index_list('jobs') WHERE name=?",(index,)).fetchone()[0],1)
 def test_due_jobs_run_in_available_then_id_order(self):
  with app.connect() as c:
   for key,available in [('later',10),('first-tie',5),('second-tie',5),('future',11)]:
    jobs.enqueue(c,'report',1,key,available)
  for _ in range(3):
   self.assertTrue(jobs.run_one(app.connect,at=10))
  self.assertFalse(jobs.run_one(app.connect,at=10))
  with app.connect() as c:
   slots=[row['slot'] for row in c.execute('SELECT slot FROM reports ORDER BY id')]
   self.assertEqual(slots,['first-tie','second-tie','later'])
 def test_idle_poll_with_another_writer(self):
  statements=[]
  def worker_connect():
   c=app.connect()
   c.execute('PRAGMA busy_timeout=0')
   c.set_trace_callback(statements.append)
   return c
  for state,stamp in (('empty',0),('future',9),('unexpired',9),('lease deadline',10)):
   with self.subTest(state=state), app.connect() as writer:
    if state=='future':
     jobs.enqueue(writer,'report',1,'future',12)
    elif state=='unexpired':
     jobs.enqueue(writer,'report',1,'occupied',0)
     writer.execute("UPDATE jobs SET status='running',attempts=1,lease='owner',lease_until=10 WHERE dedupe='occupied'")
    writer.commit()
    writer.execute('BEGIN IMMEDIATE')
    statements.clear()
    self.assertFalse(jobs.run_one(worker_connect,at=stamp))
    self.assertFalse(any(sql.lstrip().upper().startswith('BEGIN') for sql in statements))
  self.assertTrue(jobs.run_one(app.connect,at=12))
  self.assertTrue(jobs.run_one(app.connect,at=12))
  with app.connect() as c:
   rows=c.execute('SELECT dedupe,status,attempts,lease FROM jobs ORDER BY id').fetchall()
   self.assertEqual([tuple(row) for row in rows],[('future','done',1,None),('occupied','done',2,None)])
 def test_expired_final_attempt_is_failed_without_due_work(self):
  with app.connect() as c:
   jobs.enqueue(c,'report',1,'crashed',0)
   c.execute("UPDATE jobs SET status='running',attempts=3,lease='old',lease_until=10")
  self.assertFalse(jobs.run_one(app.connect,at=11))
  with app.connect() as c:
   row=c.execute('SELECT status,attempts,lease,lease_until FROM jobs').fetchone()
   self.assertEqual(tuple(row),('failed',3,None,None))
 def test_due_job_claimed_between_preflight_and_writer_lock(self):
  with app.connect() as c:jobs.enqueue(c,'report',1,'contested',10)
  competing_claims=[]
  def before_statement(sql):
   if sql.upper()=='BEGIN IMMEDIATE':
    competing_claims.append(jobs.run_one(app.connect,at=10))
  def worker_connect():
   c=app.connect()
   c.set_trace_callback(before_statement)
   return c
  self.assertFalse(jobs.run_one(worker_connect,at=10))
  self.assertEqual(competing_claims,[True])
  with app.connect() as c:
   row=c.execute('SELECT status,attempts,lease,lease_until FROM jobs').fetchone()
   self.assertEqual(tuple(row),('done',1,None,None))
   self.assertEqual(c.execute('SELECT count(*) FROM reports').fetchone()[0],1)
 def enqueue_pluto(self):
  with app.connect() as c:
   pid=c.execute("INSERT INTO portfolios(user_id,name,source,updated) VALUES(?,'Fixture','pluto',0)",(self.uid,)).lastrowid
   jobs.enqueue(c,'pluto_data',self.uid,'pluto-fixture',0,pid)
  return pid
 def test_late_pluto_success_preserves_reclaimed_success(self):
  pid=self.enqueue_pluto()
  reclaimed={'observed':'2026-01-02T12:00:00+00:00','errors':[]}
  delayed={'observed':'2026-01-02T12:01:00+00:00','errors':['positions: fixture']}
  claims=[]
  def delayed_read(connect,user_id,portfolio_id):
   with patch('portfolio_data.read',return_value=reclaimed):
    claims.append(jobs.run_one(connect,at=601))
   return delayed
  with patch('portfolio_data.read',side_effect=delayed_read):
   self.assertTrue(jobs.run_one(app.connect,at=0))
  self.assertEqual(claims,[True])
  with app.connect() as c:
   self.assertEqual(portfolio_data.snapshots(c,self.uid),{
    str(pid):{'data':reclaimed,'last_error':None,'last_attempt':reclaimed['observed']}})
   job=c.execute('SELECT status,attempts,result,lease,lease_until FROM jobs').fetchone()
   self.assertEqual(tuple(job),('done',2,'Pluto-data hentet',None,None))
 def test_late_pluto_failure_preserves_reclaimed_success(self):
  pid=self.enqueue_pluto()
  fresh={'observed':'2026-01-02T12:00:00+00:00','errors':[]}
  claims=[]
  def late_failure(connect,user_id,portfolio_id):
   with patch('portfolio_data.read',return_value=fresh):
    claims.append(jobs.run_one(connect,at=600))  # Still leased at the exact deadline.
    claims.append(jobs.run_one(connect,at=601))
   raise OSError('original read failed')
  with patch('portfolio_data.read',side_effect=late_failure):
   self.assertTrue(jobs.run_one(app.connect,at=0))
  self.assertEqual(claims,[False,True])
  with app.connect() as c:
   job=c.execute('SELECT status,attempts,result,available,lease,lease_until FROM jobs').fetchone()
   self.assertEqual(tuple(job),('done',2,'Pluto-data hentet',0,None,None))
   snapshot=portfolio_data.snapshots(c,self.uid)[str(pid)]
   self.assertEqual(snapshot,{'data':fresh,'last_error':None,'last_attempt':fresh['observed']})
 def test_current_pluto_failure_marks_snapshot_and_retries(self):
  pid=self.enqueue_pluto()
  saved={'observed':'2026-01-01T12:00:00+00:00','errors':[]}
  with app.connect() as c:
   portfolio_data.save(c,self.uid,pid,saved)
   other=c.execute("INSERT INTO users(username,salt,hash) VALUES('other','test','test')").lastrowid
   other_pid=c.execute("INSERT INTO portfolios(user_id,name,source,updated) VALUES(?,'Fixture','pluto',0)",(other,)).lastrowid
   portfolio_data.save(c,other,other_pid,saved)
  with patch('portfolio_data.read',side_effect=OSError('secret-never-log-this')):
   for attempt,when in enumerate((0,900,1800),1):
    self.assertFalse(jobs.run_one(app.connect,at=when-1))
    self.assertTrue(jobs.run_one(app.connect,at=when))
    with app.connect() as c:
     job=c.execute('SELECT status,attempts,available,lease,lease_until,result FROM jobs').fetchone()
     self.assertEqual(tuple(job),('failed' if attempt==3 else 'queued',attempt,when+900,None,None,
                                  'Kørslen fejlede; kontrollér datakilde og serveropsætning'))
     snapshot=portfolio_data.snapshots(c,self.uid)[str(pid)]
     self.assertEqual(snapshot['data'],saved)
     self.assertEqual(snapshot['last_error'],'Automatisk Pluto-læsning fejlede; gemte data kan være forældede')
     self.assertEqual(portfolio_data.snapshots(c,other)[str(other_pid)],
                      {'data':saved,'last_error':None,'last_attempt':saved['observed']})
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
