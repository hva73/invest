"""Automatic holding watches use synthetic owned snapshots and no provider calls."""
import hashlib,json,os,sqlite3,tempfile,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,hotwatch_engine as engine,hotwatch_service as service
from hotwatch_adapters import reserve,DataUnavailable
import test_trade_service as fixtures

class SQLiteLockDiagnostics(unittest.TestCase):
 def test_lock_codes_and_legacy_messages_keep_details_private(self):
  cases=(
   (None,'database is locked',True),
   (None,'database table is locked',True),
   (None,'database schema is locked: private_name',True),
   (None,'database table is locked: private_name',True),
   (None,'no such table: database is locked',False),
   (None,'database is locked by private_name',False),
   (517,'private_name',True),  # SQLITE_BUSY_SNAPSHOT
   (262,'private_name',True),  # SQLITE_LOCKED_SHAREDCACHE
   (1,'database is locked',False),
  )
  for code,message,busy in cases:
   with self.subTest(code=code,message=message):
    error=sqlite3.OperationalError(message)
    if code is not None:error.sqlite_errorcode=code
    kind='DATABASE_BUSY' if busy else 'DATABASE_ERROR'
    self.assertEqual(service.processing_error_code(error),'PROCESSING_'+kind+'_OTHER_0')
    self.assertEqual(service.reference_error_code(error),'REFERENCE_'+kind)

class DiscoveryAttemptPerformance(unittest.TestCase):
 def test_user_scoped_attempt_join_preserves_selection_and_bounds_sql(self):
  now=datetime(2026,11,25,12,tzinfo=timezone.utc)
  candidate_ids=[f'shared-{i:02}' for i in range(24)]
  payload=json.dumps({'report_id':'current','candidates':[{'candidate_id':cid} for cid in candidate_ids]})
  for count in (1,10,100):
   with self.subTest(users=count),tempfile.TemporaryDirectory() as temp,patch.object(app,'DB',temp+'/db'):
    app.init()
    with app.connect() as c:
     for uid in range(1,count+1):
      c.execute('INSERT INTO users(id,username,active) VALUES(?,?,1)',(uid,f'user-{uid}'))
      row_id=c.execute('INSERT INTO ingested_reports(user_id,report_id,received,payload,digest,is_test,generated_epoch,report_type) VALUES(?,?,?,?,?,0,?,?)',
                       (uid,'current',now.isoformat(),payload,'synthetic',now.timestamp(),'hourly')).lastrowid
      c.executemany('INSERT INTO report_candidate_links VALUES(?,0,?,?,?)',[(uid,cid,row_id,now.timestamp()) for cid in candidate_ids])
    expected=[];expected_cursor=23
    with app.connect() as c:
     for uid in range(1,count+1):
      eligible_index={1:22,2:0}.get(uid%3)
      for index,cid in enumerate(candidate_ids):
       if index==eligible_index and uid%3==1:continue
       report_id='previous' if index==eligible_index and uid%2==0 else 'current'
       retry=now.timestamp() if index==eligible_index and uid%2 else now.timestamp()+600
       c.execute('INSERT INTO hw_discovery_attempts VALUES(?,?,?,?,?,?,?,NULL)',(uid,0,cid,report_id,'NOT_NEW',now.isoformat(),retry))
      if eligible_index is not None:
       cid=candidate_ids[eligible_index]
       c.execute('INSERT INTO hw_discovery_attempts VALUES(?,1,?,?,?,?,?,NULL)',(uid,cid,'current','NOT_NEW',now.isoformat(),now.timestamp()+600))
       expected.append((uid,cid))
       expected_cursor+=(eligible_index-expected_cursor)%len(candidate_ids)
    statements=[]
    def traced_connect():
     connection=app.connect()
     connection.set_trace_callback(statements.append)
     return connection
    with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':''}), \
         patch.object(engine,'utc',return_value=now), \
         patch.object(service,'auto_activate_candidate',return_value={'status':'NOT_NEW'}) as activate:
     cursor=service.auto_discover(traced_connect,23)
    self.assertEqual([(call.args[1],call.args[4]['candidate_id']) for call in activate.call_args_list],expected)
    self.assertEqual(cursor,expected_cursor+1)
    reads=[sql for sql in statements if sql.lstrip().upper().startswith(('SELECT','WITH'))]
    self.assertEqual(len(reads),1+4*count)
    self.assertEqual(sum('hw_discovery_attempts' in sql for sql in reads),count)
    with app.connect() as c:
     actual=c.execute('SELECT user_id,candidate_id,next_attempt FROM hw_discovery_attempts WHERE is_test=0 AND next_attempt=? ORDER BY user_id',(now.timestamp()+300,)).fetchall()
     self.assertEqual([tuple(row) for row in actual],[(uid,cid,now.timestamp()+300) for uid,cid in expected])

class HoldingScanPerformance(unittest.TestCase):
 now=datetime(2026,11,25,12,tzinfo=timezone.utc)

 def seed(self,users,size,case,history=0,activation=0):
  temp=tempfile.TemporaryDirectory()
  self.addCleanup(temp.cleanup)
  db=patch.object(app,'DB',temp.name+'/db')
  db.start()
  self.addCleanup(db.stop)
  app.init()
  at=self.now.isoformat()
  self.assets=[f'shared-{i:02}' for i in range(size)]
  positions=[{'kind':'holding','asset_id':aid,'quantity':'1'} for aid in self.assets]
  payload=json.dumps({'positions_complete':True,'observed':at,'positions':positions})
  insert_session="""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                    VALUES(?,?,0,?,'manual holding',?,?,'fixture','{}','{}',?,?,0)"""
  with app.connect() as c:
   for uid in range(1,users+1):
    pid=2*uid
    c.execute('INSERT INTO users(id,username) VALUES(?,?)',(uid,f'user-{uid}'))
    c.execute("INSERT INTO portfolios(id,user_id,name,source,updated) VALUES(?,?,'Test','pluto',0)",(pid,uid))
    c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(pid,uid,at,payload,at))
    if case=='killed':
     c.execute('INSERT INTO hw_control VALUES(?,1,?,?)',(uid,at,'fixture'))
    for i,aid in enumerate(self.assets):
     request=json.dumps({'asset_id':aid,'portfolio_ids':[pid],'watch_mode':'exit'})
     if case=='early' and uid==1 and i>=activation:
      c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(uid,pid,aid,'POSITION_CLOSED',None,0,at))
     elif case in ('linked','automatic','unlinked') or (case=='early' and uid==1) or (case=='mixed' and i==0):
      watch=('hw-holding-'+hashlib.sha256(f'{uid}|{pid}|{aid}'.encode()).hexdigest()[:28]
             if case=='automatic' else f'watch-{i}')
      c.execute(insert_session,(uid,watch,aid,'PAUSED',request,at,at))
      if case!='unlinked' and (case!='early' or uid!=1 or i!=0):
       c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(uid,pid,aid,'LINKED',watch,0,at))
     elif case!='killed':
      c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(uid,pid,aid,'IDENTITY_UNVERIFIED',None,self.now.timestamp()+600,at))
    request=json.dumps({'asset_id':self.assets[-1],'portfolio_ids':[pid],'watch_mode':'exit'})
    c.executemany(insert_session,((uid,f'old-{i}','old','COMPLETED',request,at,at) for i in range(history)))

 def scan(self,verify=None,statements=None,warm_schema=False):
  # Profile the full tick and its selection phase separately. Fixture setup
  # and assertions are outside both counters.
  stats=dict(steps=0,rows=0,decodes=0,writes=0,reads=0,locked_steps=0,locked_rows=0,lookup_steps=0,
             total_steps=0,total_rows=0,total_decodes=0)
  selecting=True
  stats['connections']=0
  def connect():
   nonlocal selecting
   stats['connections']+=1
   if stats['connections']>1:selecting=False
   c=app.connect()
   if warm_schema:
    # Exclude schema parsing on each new connection, as in the pinned VM profile.
    c.execute('SELECT 1 FROM users LIMIT 1').fetchall()
   at_position=False
   def progress():
    stats['total_steps']+=1
    if selecting:
     stats['steps']+=1
     if at_position:stats['lookup_steps']+=1
     if c.in_transaction:stats['locked_steps']+=1
    return 0
   def row(cursor,values):
    stats['total_rows']+=1
    if selecting:
     stats['rows']+=1
     if c.in_transaction:stats['locked_rows']+=1
    return sqlite3.Row(cursor,values)
   def trace(sql):
    nonlocal at_position,selecting
    if sql.startswith('SELECT count(*) FROM hw_sessions'):selecting=False
    if not selecting:return
    if statements is not None:statements.append(sql)
    if sql.startswith('SELECT killed FROM hw_control'):at_position=True
    if sql.lstrip().upper().startswith(('SELECT','WITH','PRAGMA')):stats['reads']+=1
    if sql.lstrip().upper().startswith(('BEGIN','INSERT','UPDATE','DELETE','REPLACE')):stats['writes']+=1
   if selecting:c.set_trace_callback(trace)
   c.set_progress_handler(progress,1)
   c.row_factory=row
   return c
  loads=json.loads
  def decode(raw,*args,**kwargs):
   data=loads(raw,*args,**kwargs)
   if isinstance(data,dict) and ('asset_id' in data or 'positions' in data):
    stats['total_decodes']+=1
    if selecting:stats['decodes']+=1
   return data
  verified=[]
  def record(conn,uid,holding):
   verified.append((uid,holding['asset_id']))
   if verify:return verify(conn,uid,holding)
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'0','ESCAPE_HW_CAPACITY':'3000'}),patch.object(json,'loads',decode):
   result=service.auto_holdings_tick(connect,verify=record,now=self.now)
  return result,verified,stats

 def at_user_gate(self,callback):
  execute=app.DatabaseConnection.execute
  count=0
  def intercept(c,sql,*args):
   nonlocal count
   if sql.startswith('SELECT killed FROM hw_control'):
    count+=1
    callback(count)
   return execute(c,sql,*args)
  return patch.object(app.DatabaseConnection,'execute',intercept)

 def original_idle_lookup_steps(self,users):
  # Measure the pre-reset per-position queries on this SQLite version. Idle
  # rows never enter activation or reconciliation, so these are all its reads.
  steps=0
  def progress():
   nonlocal steps
   steps+=1
   return 0
  with app.connect() as c:
   c.execute('SELECT 1 FROM hw_system_control').fetchall()
   c.set_progress_handler(progress,1)
   for uid in range(1,users+1):
    for aid in self.assets:
     killed=c.execute('SELECT killed FROM hw_control WHERE user_id=?',(uid,)).fetchone()
     if killed and killed[0]:continue
     c.execute("""SELECT watch_id,status,request FROM hw_sessions WHERE user_id=? AND is_test=0
                  AND json_extract(request,'$.asset_id')=? ORDER BY id DESC""",(uid,aid)).fetchall()
     c.execute("""SELECT status,watch_id,next_attempt FROM hw_holding_autowatch
                  WHERE user_id=? AND portfolio_id=? AND asset_id=?""",(uid,2*uid,aid)).fetchone()
  return steps

 def test_idle_and_killed_workloads(self):
  for users in (1,10,100):
   for size in (1,26):
    for case in ('linked','automatic','mixed','deferred','killed'):
     with self.subTest(users=users,size=size,case=case):
      self.seed(users,size,case)
      result,verified,stats=self.scan()
      self.assertEqual((result,verified,stats['writes']),(None,[],0))
      self.assertLessEqual(stats['lookup_steps'],self.original_idle_lookup_steps(users))
      linked=size if case in ('linked','automatic') else int(case=='mixed')
      self.assertEqual(stats['decodes'],users*(1+linked))
      self.assertEqual(stats['rows'],1+users*(1+size+linked))
      reads_per_position=1 if case=='killed' else 3
      self.assertLessEqual(stats['reads'],2+users*size*reads_per_position)
      self.doCleanups()

 def test_first_reopened_holding_stays_within_pinned_tick_budget(self):
  # Full-tick counts on f18e919, SQLite 3.51.0, for the two verifier outcomes.
  for verified,expected,max_steps,max_rows,max_decodes in (
    (False,'IDENTITY_UNVERIFIED',316,5,1),(True,'LINKED',1110,11,3)):
   with self.subTest(verified=verified):
    self.seed(1,1,'early')
    aid=self.assets[0]
    instrument={'asset_id':aid,'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
    result,visits,stats=self.scan(verify=lambda *_:instrument if verified else None,warm_schema=True)
    self.assertEqual((result,visits),(expected,[(1,aid)]))
    self.assertLessEqual(stats['total_steps'],max_steps)
    self.assertLessEqual(stats['total_rows'],max_rows)
    self.assertLessEqual(stats['total_decodes'],max_decodes)
    with app.connect() as c:
     attempt=c.execute('SELECT status,watch_id,next_attempt FROM hw_holding_autowatch').fetchone()
     self.assertEqual((attempt['status'],attempt['next_attempt']),(expected,self.now.timestamp()+300))
     sessions=c.execute('SELECT watch_id,request FROM hw_sessions').fetchall()
     if verified:
      self.assertEqual([row['watch_id'] for row in sessions],[attempt['watch_id']])
      request=json.loads(sessions[0]['request'])
      self.assertEqual((request['portfolio_ids'],request['asset_id'],request['watch_mode']),([2],aid,'exit'))
     else:self.assertEqual((sessions,attempt['watch_id']),([],None))
    self.doCleanups()

 def test_paused_positions_link_in_one_commit_within_pinned_budget(self):
  # Pinned full-tick VM counts with no history or pre-existing links.
  for users,size,max_steps in ((1,1,196),(10,1,1402),(100,1,13462),
                              (1,26,7646),(10,26,76127),(100,26,760937)):
   with self.subTest(users=users,size=size):
    self.seed(users,size,'unlinked')
    statements=[]
    result,visits,stats=self.scan(statements=statements,warm_schema=True)
    self.assertEqual((result,visits,statements.count('COMMIT')),(None,[],1))
    self.assertLessEqual(stats['total_steps'],max_steps)
    self.assertLessEqual(stats['total_rows'],1+users*(1+size))
    self.assertEqual(stats['total_decodes'],users*(1+size))
    self.assertEqual(stats['locked_rows'],0)
    with app.connect() as c:
     rows=c.execute("""SELECT a.user_id,a.portfolio_id,a.asset_id,a.watch_id,a.status,s.status
                       FROM hw_holding_autowatch a JOIN hw_sessions s
                       ON s.user_id=a.user_id AND s.watch_id=a.watch_id AND s.is_test=0
                       ORDER BY a.user_id,a.asset_id""").fetchall()
     self.assertEqual(list(map(tuple,rows)),[(uid,2*uid,aid,f'watch-{i}','LINKED','PAUSED')
                      for uid in range(1,users+1) for i,aid in enumerate(self.assets)])
    result,visits,idle=self.scan()
    self.assertEqual((result,visits,idle['writes']),(None,[],0))
    self.doCleanups()

 def test_early_activation_bounds_work_while_writing(self):
  for users in (1,10,100):
   for size,activation in ((1,0),(26,0),(26,1),(26,2),(26,3)):
    with self.subTest(users=users,size=size,activation=activation):
     # All the completed requests belong to the last asset. The tick must
     # reach the same holding with the same locked work as an empty history.
     runs=[]
     for history in (0,2048):
      self.seed(users,size,'early',activation=activation)
      if history:
       self.add_history(history)
      result,verified,stats=self.scan()
      self.assertEqual((result,verified),('IDENTITY_UNVERIFIED',[(1,self.assets[activation])]))
      # One selection scope and one result scope, separated by verification.
      self.assertEqual(stats['connections'],2)
      self.assertEqual(stats['locked_rows'],0)
      self.assertEqual(stats['decodes'],1+activation)
      runs.append(stats)
      self.doCleanups()
     for key in ('rows','locked_rows','decodes','reads','writes'):
      self.assertEqual(runs[0][key],runs[1][key],key)
     self.assertLessEqual(runs[1]['locked_steps'],runs[0]['locked_steps']+10)
     self.assertLessEqual(runs[1]['steps'],runs[0]['steps']+10)

 def test_duplicate_position_observes_the_link_from_its_first_visit(self):
  self.seed(1,2,'unlinked')
  with app.connect() as c:
   payload=json.loads(c.execute('SELECT payload FROM portfolio_snapshots').fetchone()[0])
   payload['positions'].insert(1,payload['positions'][0])
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps(payload),))
  statements=[]
  self.assertEqual(self.scan(statements=statements)[:2],(None,[]))
  self.assertEqual(sum(q.startswith('INSERT INTO hw_holding_autowatch') for q in statements),2)
  with app.connect() as c:
   rows=c.execute('SELECT asset_id,status,watch_id FROM hw_holding_autowatch ORDER BY asset_id')
   self.assertEqual(list(map(tuple,rows)),[(aid,'LINKED',f'watch-{i}') for i,aid in enumerate(self.assets)])

 def test_invalid_system_switch_leaves_reopened_position_untouched(self):
  self.seed(1,1,'early')
  with app.connect() as c:c.execute("UPDATE hw_system_control SET killed='unknown'")
  result,visits,stats=self.scan()
  self.assertEqual((result,visits,stats['writes'],stats['decodes']),(None,[],0,0))
  with app.connect() as c:c.execute('UPDATE hw_system_control SET killed=0')
  self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[(1,self.assets[0])]))

 def test_pending_links_recheck_kill_and_reopen_in_order(self):
  self.seed(4,1,'unlinked')
  aid=self.assets[0]
  execute=app.DatabaseConnection.execute
  raced=False
  def change(c,sql,*args):
   nonlocal raced
   if sql=='BEGIN IMMEDIATE' and not raced:
    raced=True
    with app.connect() as other:
     other.execute("INSERT INTO hw_control VALUES(2,1,?,'fixture')",(self.now.isoformat(),))
     other.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE user_id=3")
     other.execute("INSERT INTO hw_holding_autowatch VALUES(3,6,?,'POSITION_CLOSED','watch-0',0,?)",
                   (aid,self.now.isoformat()))
   return execute(c,sql,*args)
  with patch.object(app.DatabaseConnection,'execute',change):
   self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[(3,aid)]))
  with app.connect() as c:
   rows=c.execute('SELECT user_id,status,watch_id FROM hw_holding_autowatch ORDER BY user_id')
   self.assertEqual(list(map(tuple,rows)),[(1,'LINKED','watch-0'),(3,'IDENTITY_UNVERIFIED',None)])
   c.execute('UPDATE hw_control SET killed=0 WHERE user_id=2')
  self.assertEqual(self.scan()[:2],(None,[]))
  with app.connect() as c:
   rows=c.execute("SELECT user_id,watch_id FROM hw_holding_autowatch WHERE status='LINKED' ORDER BY user_id")
   self.assertEqual(list(map(tuple,rows)),[(1,'watch-0'),(2,'watch-0'),(4,'watch-0')])

 def test_idle_position_reopened_at_gate_follows_committed_link(self):
  self.seed(1,3,'linked')
  with app.connect() as c:
   c.execute('DELETE FROM hw_holding_autowatch WHERE asset_id=?',(self.assets[0],))
  def reopen(position):
   if position!=2:return
   with app.connect() as other:
    self.assertEqual(other.execute('SELECT status FROM hw_holding_autowatch WHERE asset_id=?',
                                   (self.assets[0],)).fetchone()[0],'LINKED')
    other.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE watch_id='watch-1'")
    other.execute("UPDATE hw_holding_autowatch SET status='POSITION_CLOSED',next_attempt=0 WHERE asset_id=?",
                  (self.assets[1],))
  with self.at_user_gate(reopen):
   self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[(1,self.assets[1])]))

 def test_competing_tick_claims_same_position_before_first_write(self):
  self.seed(1,1,'early')
  aid=self.assets[0]
  instrument={'asset_id':aid,'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
  execute=app.DatabaseConnection.execute
  won=[]
  def race(c,sql,*args):
   if not won and (sql=='BEGIN IMMEDIATE' or sql.startswith('INSERT INTO hw_holding_autowatch')):
    won.append(None)
    won[0]=service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now)
   return execute(c,sql,*args)
  with patch.object(app.DatabaseConnection,'execute',race):
   self.assertEqual(self.scan()[:2],(None,[]))
  self.assertEqual(won,['LINKED'])
  with app.connect() as c:
   row=c.execute("SELECT s.status,a.status FROM hw_holding_autowatch a JOIN hw_sessions s ON s.user_id=a.user_id AND s.watch_id=a.watch_id").fetchone()
   self.assertEqual(tuple(row),('CREATED','LINKED'))

 def test_snapshot_change_before_claim_checks_each_portfolio_under_writer(self):
  # The first position needs a link update. Another connection also changes
  # the second portfolio before that update commits.
  for change in ('closed','failed','inactive_user','inactive_portfolio','refreshed'):
   with self.subTest(change=change):
    self.seed(3,1,'early',activation=1)
    aid=self.assets[0]
    with app.connect() as c:
     c.execute('UPDATE hw_holding_autowatch SET next_attempt=0 WHERE user_id IN (2,3)')
    execute=app.DatabaseConnection.execute
    raced=False
    def race(c,sql,*args):
     nonlocal raced
     if not raced and sql=='BEGIN IMMEDIATE':
      raced=True
      with app.connect() as other:
       if change=='failed':other.execute("UPDATE portfolio_snapshots SET last_error='unavailable' WHERE user_id=2")
       elif change=='inactive_user':other.execute('UPDATE users SET active=0 WHERE id=2')
       elif change=='inactive_portfolio':other.execute('UPDATE portfolios SET active=0 WHERE user_id=2')
       else:
        positions=[] if change=='closed' else [{'kind':'holding','asset_id':aid,'quantity':'2'}]
        payload=json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':positions})
        other.execute('UPDATE portfolio_snapshots SET payload=? WHERE user_id=2',(payload,))
     return execute(c,sql,*args)
    seen=[]
    with patch.object(app.DatabaseConnection,'execute',race):
     result,verified,_=self.scan(verify=lambda conn,uid,h:seen.append((uid,h['quantity'])))
    owner=2 if change=='refreshed' else 3
    self.assertTrue(raced)
    self.assertEqual((result,verified,seen),('IDENTITY_UNVERIFIED',[(owner,aid)],[(owner,'2' if owner==2 else '1')]))
    with app.connect() as c:
     self.assertEqual(c.execute('SELECT status FROM hw_holding_autowatch WHERE user_id=1').fetchone()[0],'LINKED')
     if owner==3:self.assertEqual(c.execute('SELECT next_attempt FROM hw_holding_autowatch WHERE user_id=2').fetchone()[0],0)
    self.doCleanups()

 def test_retry_can_finish_while_first_verifier_is_still_running(self):
  self.seed(1,1,'early')
  aid=self.assets[0]
  instrument={'asset_id':aid,'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
  def slow_verifier(connect,uid,holding):
   with app.connect() as other:
    other.execute('PRAGMA busy_timeout=0')
    other.execute('BEGIN IMMEDIATE')
    attempt=other.execute('SELECT status,next_attempt FROM hw_holding_autowatch').fetchone()
    self.assertEqual(tuple(attempt),('VERIFYING',self.now.timestamp()+300))
   retry=self.now+timedelta(seconds=300)
   self.assertEqual(service.auto_holdings_tick(connect,verify=lambda *_:instrument,now=retry),'LINKED')
   return None
  result,verified,_=self.scan(verify=slow_verifier)
  self.assertEqual((result,verified),(None,[(1,aid)]))
  with app.connect() as c:
   sessions=c.execute('SELECT watch_id,status FROM hw_sessions').fetchall()
   self.assertEqual(len(sessions),1)
   self.assertEqual(sessions[0]['status'],'CREATED')
   link=c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()
   self.assertEqual(tuple(link),('LINKED',sessions[0]['watch_id']))

 def test_worker_releases_database_scope_for_verification_and_rolls_back_rejected_link(self):
  from concurrent.futures import ThreadPoolExecutor
  self.seed(1,1,'early')
  aid=self.assets[0]
  instrument={'asset_id':aid,'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
  worker=service.serialized_database(app.connect)
  def close_position():
   with worker() as other:
    payload=other.execute('SELECT payload FROM portfolio_snapshots').fetchone()[0]
    current=json.loads(payload)
    current['positions']=[]
    other.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps(current),))
    return payload
  saved=[]
  with ThreadPoolExecutor(max_workers=1) as pool:
   def verify(*args):
    saved.append(pool.submit(close_position).result(timeout=3))
    return instrument
   self.assertEqual(service.auto_holdings_tick(worker,verify=verify,now=self.now),'holding_not_verified')
  with app.connect() as c:
   self.assertEqual(tuple(c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()),('holding_not_verified',None))
   self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
   c.execute('UPDATE portfolio_snapshots SET payload=?',(saved[0],))
  self.assertEqual(service.auto_holdings_tick(worker,verify=lambda *_:instrument,now=self.now+timedelta(seconds=300)),'LINKED')

 def test_operator_kill_between_preflight_and_reservation(self):
  self.seed(1,1,'early')
  execute=app.DatabaseConnection.execute
  def kill(c,sql,*args):
   if sql=='BEGIN IMMEDIATE':
    with app.connect() as other:other.execute('UPDATE hw_system_control SET killed=1 WHERE id=1')
   return execute(c,sql,*args)
  with patch.object(app.DatabaseConnection,'execute',kill):
   self.assertEqual(self.scan()[:2],(None,[]))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_holding_autowatch').fetchone()[0],'POSITION_CLOSED')
   c.execute('UPDATE hw_system_control SET killed=0 WHERE id=1')
  self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[(1,self.assets[0])]))

 def test_expired_verifier_cannot_create_watch_after_a_newer_failed_check(self):
  self.seed(1,1,'early')
  aid=self.assets[0]
  instrument={'asset_id':aid,'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
  def delayed(connect,uid,holding):
   retry=self.now+timedelta(seconds=300)
   self.assertEqual(service.auto_holdings_tick(connect,verify=lambda *_:None,now=retry),'IDENTITY_UNVERIFIED')
   return instrument
  self.assertEqual(self.scan(verify=delayed)[:2],(None,[(1,aid)]))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
   self.assertEqual(tuple(c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()),('IDENTITY_UNVERIFIED',None))
   c.execute('UPDATE hw_holding_autowatch SET next_attempt=0')
  self.assertEqual(self.scan(verify=lambda *_:instrument)[:2],('LINKED',[(1,aid)]))

 def test_first_verified_position_creates_one_exit_watch_with_history(self):
  self.seed(100,26,'early',activation=1)
  self.add_history(2048)
  aid=self.assets[1]
  instrument={'asset_id':aid,'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
  result,verified,stats=self.scan(verify=lambda *_:instrument)
  self.assertEqual((result,verified,stats['decodes']),('LINKED',[(1,aid)],2))
  with app.connect() as c:
   created=c.execute("SELECT user_id,watch_id,request FROM hw_sessions WHERE status='CREATED'").fetchall()
   self.assertEqual(len(created),1)
   request=json.loads(created[0]['request'])
   self.assertEqual((created[0]['user_id'],request['asset_id'],request['portfolio_ids'],request['watch_mode']),(1,aid,[2],'exit'))
   link=c.execute('SELECT status,watch_id FROM hw_holding_autowatch WHERE user_id=1 AND portfolio_id=2 AND asset_id=?',(aid,)).fetchone()
   self.assertEqual(tuple(link),('LINKED',created[0]['watch_id']))
   self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE status='COMPLETED'").fetchone()[0],2048)

 def test_verified_activation_work_with_and_without_history(self):
  for users in (1,10,100):
   for size in (1,26):
    with self.subTest(users=users,size=size):
     runs=[]
     for history in (0,2048):
      self.seed(users,size,'early')
      self.add_history(history)
      aid=self.assets[0]
      instrument={'asset_id':aid,'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
      result,verified,stats=self.scan(verify=lambda *_:instrument)
      self.assertEqual((result,verified),('LINKED',[(1,aid)]))
      with app.connect() as c:
       created=c.execute("SELECT user_id,request FROM hw_sessions WHERE status='CREATED'").fetchall()
       self.assertEqual(len(created),1)
       request=json.loads(created[0]['request'])
       self.assertEqual((created[0]['user_id'],request['portfolio_ids'],request['asset_id'],request['watch_mode']),
                        (1,[2],aid,'exit'))
      runs.append(stats)
      self.doCleanups()
     self.assertEqual(runs[0]['total_rows'],runs[1]['total_rows'])
     self.assertEqual(runs[0]['total_decodes'],runs[1]['total_decodes'])
     self.assertLessEqual(runs[1]['total_steps'],runs[0]['total_steps']+10)

 def add_history(self,count):
  at=self.now.isoformat()
  request=json.dumps({'asset_id':self.assets[-1],'portfolio_ids':[2],'watch_mode':'exit'})
  with app.connect() as c:
   c.executemany("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                    VALUES(1,?,0,'old','manual holding','COMPLETED',?,'fixture','{}','{}',?,?,0)""",
                 ((f'history-{i}',request,at,at) for i in range(count)))

 def test_idle_work_is_independent_of_history_for_the_visited_asset(self):
  self.seed(1,26,'mixed')
  before=self.scan()
  self.add_history(2048)
  after=self.scan()
  self.assertEqual(before[:2],(None,[]))
  self.assertEqual(before,after)

 def test_idle_read_budget_survives_unrelated_commits(self):
  for case in ('linked','deferred'):
   with self.subTest(case=case):
    self.seed(100,1,case)
    def changed(position):
     self.assertLessEqual(position,100)
     with app.connect() as other:
      other.execute("UPDATE users SET salt=? WHERE id=100",(str(position),))
    with self.at_user_gate(changed):result,verified,stats=self.scan()
    self.assertEqual((result,verified,stats['writes']),(None,[],0))
    self.assertLessEqual(stats['reads'],302)
    self.doCleanups()

 def test_ambiguous_open_watches_stop_after_two_eligible_matches(self):
  self.seed(1,1,'automatic')
  aid=self.assets[0]
  at=self.now.isoformat()
  with app.connect() as c:
   request=json.dumps({'asset_id':aid,'watch_mode':'exit','portfolio_ids':[2]})
   c.executemany("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                    VALUES(1,?,0,?,'other holding','ACTIVE',?,'fixture','{}','{}',?,?,0)""",
                 ((f'manual-{i}',f'zz-{i}',request,at,at) for i in range(2048)))
  for expected_write in (True,False):
   result,verified,stats=self.scan()
   self.assertEqual((result,verified,stats['decodes']),(None,[],3))
   # An unchanged version lets the writer use the exact preflight decision.
   self.assertEqual(stats['locked_rows'],0)
   self.assertLessEqual(stats['rows']-stats['locked_rows'],5)
   self.assertEqual(bool(stats['writes']),expected_write)
   with app.connect() as c:
    self.assertEqual(tuple(c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()),('AMBIGUOUS',None))
  with app.connect() as c:c.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE purpose='other holding'")
  self.assertEqual(self.scan()[:2],(None,[]))
  with app.connect() as c:
   link=c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()
   self.assertEqual(tuple(link),('LINKED',c.execute("SELECT watch_id FROM hw_sessions WHERE status='PAUSED'").fetchone()[0]))

 def test_stopped_automatic_watch_is_read_once_and_open_watch_takes_priority(self):
  self.seed(1,1,'automatic')
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET status='COMPLETED'")
   watch=c.execute('SELECT watch_id FROM hw_sessions').fetchone()[0]
  sql=[]
  self.assertEqual(self.scan(statements=sql)[:2],(None,[]))
  self.assertEqual(sum('FROM hw_sessions' in query for query in sql),1)
  with app.connect() as c:
   self.assertEqual(tuple(c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()),('STOPPED',watch))
   c.execute("UPDATE hw_sessions SET status='PAUSED'")
  self.assertEqual(self.scan()[:2],(None,[]))
  with app.connect() as c:
   self.assertEqual(tuple(c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()),('LINKED',watch))

 def test_terminal_link_precedes_default_without_decoding_both_requests(self):
  self.seed(1,1,'automatic')
  aid=self.assets[0]
  with app.connect() as c:
   default=c.execute('SELECT watch_id FROM hw_sessions').fetchone()[0]
   c.execute("UPDATE hw_sessions SET status='COMPLETED'")
   c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                SELECT user_id,'manual',is_test,candidate_id,purpose,'EXPIRED',request,digest,strategy,state,created,updated,next_due
                FROM hw_sessions""")
  for portfolio,expected,decodes in ((2,'manual',2),(3,default,3)):
   with self.subTest(portfolio=portfolio):
    with app.connect() as c:
     request=json.dumps({'asset_id':aid,'portfolio_ids':[portfolio],'watch_mode':'exit'})
     c.execute("UPDATE hw_sessions SET request=? WHERE watch_id='manual'",(request,))
     c.execute("UPDATE hw_holding_autowatch SET status='LINKED',watch_id='manual'")
    result,verified,stats=self.scan()
    self.assertEqual((result,verified,stats['decodes']),(None,[],decodes))
    with app.connect() as c:
     link=c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()
     self.assertEqual(tuple(link),('STOPPED',expected))

 def test_kill_during_verification_blocks_creation_and_allows_later_retry(self):
  for scope,error in (('user','kill_switch_active'),('system','operator_kill_switch')):
   with self.subTest(scope=scope):
    self.seed(1,1,'early')
    aid=self.assets[0]
    instrument={'asset_id':aid,'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
    def kill(connect,uid,holding):
     with app.connect() as c:
      if scope=='system':c.execute('UPDATE hw_system_control SET killed=1 WHERE id=1')
      else:c.execute("INSERT INTO hw_control VALUES(?,1,?,'fixture')",(uid,self.now.isoformat()))
     return instrument
    self.assertEqual(self.scan(verify=kill)[:2],(error,[(1,aid)]))
    with app.connect() as c:
     self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
     self.assertEqual(tuple(c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()),(error,None))
     c.execute('UPDATE hw_system_control SET killed=0 WHERE id=1')
     c.execute('UPDATE hw_control SET killed=0 WHERE user_id=1')
    retry=self.now+timedelta(seconds=300)
    self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=retry),'LINKED')
    self.doCleanups()

 def test_user_then_portfolio_then_payload_order_with_interleaved_ids(self):
  self.seed(2,2,'deferred')
  with app.connect() as c:
   at=self.now.isoformat()
   for pid,uid in ((9,1),(1,2),(7,1)):
    c.execute("INSERT INTO portfolios(id,user_id,name,source,updated) VALUES(?,?,'Test','pluto',0)",(pid,uid))
    positions=[{'kind':'holding','asset_id':f'{pid}-{i}','quantity':'1'} for i in ('b','a')]
    payload=json.dumps({'positions_complete':True,'observed':at,'positions':positions})
    c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(pid,uid,at,payload,at))
  for expected in ((1,'7-b'),(1,'7-a'),(1,'9-b'),(1,'9-a'),(2,'1-b'),(2,'1-a')):
   self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[expected]))

 def test_fifth_watch_stops_before_later_tenant_is_selected(self):
  self.seed(2,5,'linked')
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE user_id=2 AND watch_id='watch-0'")
   c.execute("UPDATE hw_holding_autowatch SET status='POSITION_CLOSED' WHERE user_id=2 AND asset_id=?",(self.assets[0],))
  def change(position):
   if position==3:
    with app.connect() as c:c.execute("UPDATE users SET salt='changed' WHERE id=1")
   if position==5:
    with app.connect() as c:c.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE user_id=1 AND watch_id='watch-4'")
  with self.at_user_gate(change):result,verified,_=self.scan()
  self.assertEqual((result,verified),('IDENTITY_UNVERIFIED',[(2,self.assets[0])]))
  with app.connect() as c:
   self.assertEqual(tuple(c.execute("SELECT status,watch_id FROM hw_holding_autowatch WHERE user_id=1 AND asset_id=?",(self.assets[4],)).fetchone()),('STOPPED','watch-4'))

 def test_gate_change_resumes_at_next_holding(self):
  self.seed(1,2,'killed')
  def resume(position):
   if position==2:
    with app.connect() as other:other.execute('UPDATE hw_control SET killed=0 WHERE user_id=1')
  with self.at_user_gate(resume):
   result,verified,_=self.scan()
  self.assertEqual((result,verified),('IDENTITY_UNVERIFIED',[(1,self.assets[1])]))

 def test_kill_before_due_position_leaves_it_for_explicit_resume(self):
  self.seed(2,2,'deferred')
  aid=self.assets[1]
  with app.connect() as c:
   c.execute('UPDATE hw_holding_autowatch SET next_attempt=0 WHERE asset_id=?',(aid,))
  def kill(position):
   if position==2:
    with app.connect() as other:
     other.execute("INSERT INTO hw_control VALUES(1,1,?,'fixture')",(self.now.isoformat(),))
  with self.at_user_gate(kill):
   self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[(2,aid)]))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT next_attempt FROM hw_holding_autowatch WHERE user_id=1 AND asset_id=?',(aid,)).fetchone()[0],0)
   c.execute('UPDATE hw_control SET killed=0 WHERE user_id=1')
  self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[(1,aid)]))

 def test_idle_scan_after_unrelated_commit_with_writer_still_held(self):
  self.seed(100,1,'linked')
  with app.connect() as other:
   def reserve(position):
    if position==2:
     other.execute("UPDATE users SET username='renamed' WHERE id=1")
     other.commit()
     other.execute('BEGIN IMMEDIATE')
   with self.at_user_gate(reserve):result,verified,stats=self.scan()
   self.assertTrue(other.in_transaction)
   self.assertEqual((result,verified,stats['writes']),(None,[],0))

 def test_changed_link_releases_writer_before_next_position(self):
  self.seed(2,2,'early',activation=1)
  with app.connect() as c:
   c.execute('UPDATE hw_holding_autowatch SET next_attempt=0 WHERE user_id=2')
  def kill_after_link(position):
   if position==2:
    with app.connect() as other:
     other.execute('PRAGMA busy_timeout=0')
     link=other.execute('SELECT status,watch_id FROM hw_holding_autowatch WHERE user_id=1 AND asset_id=?',
                        (self.assets[0],)).fetchone()
     self.assertEqual(tuple(link),('LINKED','watch-0'))
     other.execute("INSERT INTO hw_control VALUES(1,1,?,'fixture')",(self.now.isoformat(),))
  with self.at_user_gate(kill_after_link):
   self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[(2,self.assets[0])]))
  with app.connect() as c:
   status=c.execute('SELECT status FROM hw_holding_autowatch WHERE user_id=1 AND asset_id=?',(self.assets[1],)).fetchone()
   self.assertEqual(status[0],'POSITION_CLOSED')
   c.execute('UPDATE hw_control SET killed=0 WHERE user_id=1')
  self.assertEqual(self.scan()[:2],('IDENTITY_UNVERIFIED',[(1,self.assets[1])]))

 def test_fresh_stop_and_retry_precede_later_tenant(self):
  self.seed(100,26,'mixed',history=64)
  aid=self.assets[0]
  # All portfolios share the asset and watch IDs. Only user 99's watch stops.
  with app.connect() as c:
   c.execute("UPDATE hw_holding_autowatch SET next_attempt=0 WHERE user_id=100 AND asset_id=?",(self.assets[1],))
  def change(position):
   if position>98*26+1 or position%26!=1:return
   with app.connect() as other:
    if position<=98*26:
     other.execute('UPDATE users SET salt=? WHERE id=100',(str(position),))
    if position==98*26+1:
     other.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE user_id=99 AND watch_id='watch-0'")
     other.execute('UPDATE hw_holding_autowatch SET next_attempt=0 WHERE user_id=99 AND asset_id=?',(self.assets[1],))
  with self.at_user_gate(change):result,verified,_=self.scan()
  self.assertEqual((result,verified),('IDENTITY_UNVERIFIED',[(99,self.assets[1])]))
  with app.connect() as c:
   stops=[tuple(r) for r in c.execute("SELECT user_id,portfolio_id,asset_id,watch_id FROM hw_holding_autowatch WHERE status='STOPPED'")]
   self.assertEqual(stops,[(99,198,aid,'watch-0')])
   self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE status='PAUSED'").fetchone()[0],99)
   self.assertEqual(c.execute('SELECT next_attempt FROM hw_holding_autowatch WHERE user_id=100 AND asset_id=?',(self.assets[1],)).fetchone()[0],0)

 def test_indexed_history_respects_identity_and_terminal_precedence(self):
  self.seed(1,26,'mixed',history=64)
  at=self.now.isoformat()
  def watch(aid,generation=None):
   key=f'1|2|{aid}'+('|' + generation if generation else '')
   return 'hw-holding-'+hashlib.sha256(key.encode()).hexdigest()[:28]

  with app.connect() as c:
   for index,variant in enumerate(('manual','generation','old','entry','other-portfolio','other-asset','test'),1):
    aid=self.assets[index]
    wid=watch(aid,at) if variant=='generation' else watch(aid)
    prior_status='POSITION_CLOSED' if variant in ('generation','old') else 'LINKED'
    c.execute('UPDATE hw_holding_autowatch SET status=?,watch_id=? WHERE user_id=1 AND portfolio_id=2 AND asset_id=?',
              (prior_status,'manual-'+aid,aid))
    request=json.dumps({'asset_id':'different' if variant=='other-asset' else aid,
                        'watch_mode':'entry' if variant=='entry' else 'exit',
                        'portfolio_ids':[3 if variant=='other-portfolio' else 2]})
    ids=(wid,'manual-'+aid) if variant=='manual' else (wid,)
    for identity in ids:
     c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                  VALUES(1,?,?,?,'history','COMPLETED',?,'x','{}','{}',?,?,0)""",
               (identity,int(variant=='test'),aid,request,at,at))
  result,verified,_=self.scan()
  self.assertEqual((result,verified),(None,[]))
  with app.connect() as c:
   stopped=c.execute("SELECT asset_id,watch_id FROM hw_holding_autowatch WHERE status='STOPPED' ORDER BY asset_id").fetchall()
   self.assertEqual(list(map(tuple,stopped)),[(self.assets[1],'manual-'+self.assets[1]),(self.assets[2],watch(self.assets[2],at))])

 def test_reopened_position_keeps_priority_after_unrelated_commit(self):
  self.seed(2,5,'linked')
  at=self.now.isoformat()
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE user_id=2 AND watch_id='watch-0'")
   c.execute("UPDATE hw_holding_autowatch SET status='POSITION_CLOSED',next_attempt=0 WHERE user_id=2 AND asset_id=?",(self.assets[0],))
  def reconcile(position):
   if position not in (3,5):return
   with app.connect() as other:
    if position==3:
     other.execute("UPDATE users SET username='renamed' WHERE id=1")
    else:
     other.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE user_id=1 AND watch_id='watch-4'")
     other.execute("UPDATE hw_holding_autowatch SET status='POSITION_CLOSED',updated=?,next_attempt=0 WHERE user_id=1 AND asset_id=?",(at,self.assets[4]))
  with self.at_user_gate(reconcile):result,verified,_=self.scan()
  self.assertEqual((result,verified),('IDENTITY_UNVERIFIED',[(1,self.assets[4])]))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_holding_autowatch WHERE user_id=2 AND asset_id=?',(self.assets[0],)).fetchone()[0],'POSITION_CLOSED')

class HoldingAutowatch(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.Trading();self.fixture.setUp();self.pid=self.fixture.root
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.holding={'kind':'holding','asset_id':'synthetic-asset','ticker':'TEST','name':'Test Company','quantity':'1'}
  with app.connect() as c:
   data={'positions_complete':True,'observed':self.now.isoformat(),'positions':[self.holding]}
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(self.pid,1,self.now.isoformat(),json.dumps(data),self.now.isoformat()))
  self.instrument={'asset_id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ','currency':'USD','isin':'US1234567890'}
  self.verify=lambda *_:self.instrument
  self.lookup=lambda *_:{'choices':[{'symbol':'TEST.US','currency':'USD','isin':'US1234567890'}]}
 def tearDown(self):self.fixture.tearDown()
 def test_closure_before_first_scan_write_uses_new_holding_generation(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  earlier={'kind':'holding','asset_id':'earlier','quantity':'1'}
  at=self.now.isoformat()
  def set_positions(positions):
   payload=json.dumps({'positions_complete':True,'observed':at,'positions':positions})
   with app.connect() as c:
    c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(payload,self.pid))
  set_positions([earlier,self.holding])
  with app.connect() as c:
   old_watch=c.execute('SELECT watch_id FROM hw_sessions').fetchone()[0]
   request=json.dumps({'asset_id':'earlier','portfolio_ids':[self.pid],'watch_mode':'exit'})
   c.execute("""
    INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
    VALUES(1,'earlier',0,'earlier','manual holding','PAUSED',?,'synthetic','{}','{}',?,?,0)
   """,(request,at,at))

  reconcile=service.reconcile_closed_holdings
  execute=app.DatabaseConnection.execute
  closed_at=self.now+timedelta(seconds=1)
  raced=False
  def race_before_scan_write(connection,sql,*args):
   nonlocal raced
   if not raced and (sql=='BEGIN IMMEDIATE' or sql.startswith('INSERT INTO hw_holding_autowatch')):
    raced=True
    set_positions([earlier])
    self.assertEqual(reconcile(app.connect,closed_at),1)
    set_positions([earlier,self.holding])
   return execute(connection,sql,*args)

  verified=[]
  def verify(_,uid,holding):
   verified.append((uid,holding['asset_id']))
   return self.instrument

  with patch.object(app.DatabaseConnection,'execute',race_before_scan_write), \
       patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_CAPACITY':'40','ESCAPE_HW_EODHD_REST_ENABLED':'0'}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=verify,now=closed_at),'LINKED')
  self.assertTrue(raced)
  aid=self.holding['asset_id']
  self.assertEqual(verified,[(1,aid)])
  identity=f'1|{self.pid}|{aid}|{closed_at.isoformat()}'
  watch='hw-holding-'+hashlib.sha256(identity.encode()).hexdigest()[:28]
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_sessions WHERE watch_id=?',(old_watch,)).fetchone()[0],'COMPLETED')
   attempts=c.execute('SELECT asset_id,status,watch_id FROM hw_holding_autowatch ORDER BY asset_id').fetchall()
   self.assertEqual([tuple(row) for row in attempts],[('earlier','LINKED','earlier'),(aid,'LINKED',watch)])
   self.assertEqual(c.execute('SELECT status FROM hw_sessions WHERE watch_id=?',(watch,)).fetchone()[0],'CREATED')

 def test_idle_identity_recheck_does_not_reserve_database_writer(self):
  holder=app.connect()
  try:
   holder.execute('BEGIN IMMEDIATE')
   self.assertEqual(service.verify_cxe_feeds(app.connect,self.now),0)
  finally:
   holder.rollback();holder.close()
 def test_present_holding_reconciliation_does_not_reserve_database_writer(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  holder=app.connect()
  try:
   holder.execute('BEGIN IMMEDIATE')
   self.assertEqual(service.reconcile_closed_holdings(app.connect,self.now),0)
  finally:
   holder.rollback();holder.close()
 def test_holding_returning_after_preflight_is_not_closed(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[]}),))
  calls=[]
  def racing_connect():
   calls.append(1)
   if len(calls)==2:
    with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[self.holding]}),))
   return app.connect()
  self.assertEqual(service.reconcile_closed_holdings(racing_connect,self.now),0)
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_sessions').fetchone()[0],'CREATED')
 def test_full_capacity_prioritizes_verified_holding_over_unowned_idle_entry(self):
  with app.connect() as c:
   strategy=c.execute("SELECT payload FROM hw_strategies WHERE strategy_id='escape_momentum' LIMIT 1").fetchone()['payload']
   req={'watch_mode':'entry','asset_id':'other-asset'}
   c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,'entry-capacity',0,'candidate-capacity','automatic discovery','ACTIVE',?,'x',?,'{\"signal\":\"WAIT\"}',?,?,0)",(json.dumps(req),strategy,self.now.isoformat(),self.now.isoformat()))
   row=c.execute("SELECT id FROM hw_sessions WHERE watch_id='entry-capacity'").fetchone()
   context={'status':'verified','position':'none','orders':[],'as_of':self.now.isoformat()}
   c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(row['id'],self.now.isoformat(),json.dumps(context)))
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_CAPACITY':'1','ESCAPE_HW_EODHD_REST_ENABLED':'0'}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   self.assertEqual(c.execute("SELECT status FROM hw_sessions WHERE watch_id='entry-capacity'").fetchone()[0],'EXPIRED')
   self.assertEqual(c.execute("SELECT count(*) FROM hw_events WHERE event_type='CAPACITY_RELEASED'").fetchone()[0],1)
   self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE purpose='automatic holding watch' AND status='CREATED'").fetchone()[0],1)
 def test_capacity_does_not_release_unknown_held_paused_or_buy_entries(self):
  with app.connect() as c:
   strategy=c.execute("SELECT payload FROM hw_strategies WHERE strategy_id='escape_momentum' LIMIT 1").fetchone()['payload']
   for i,(status,signal,position) in enumerate([('ACTIVE','BUY','none'),('PAUSED','WAIT','none'),('ACTIVE','WAIT','held'),('ACTIVE','WAIT','unknown')]):
    c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,?,0,?,'automatic discovery',?,?,'x',?,?,?,?,0)",(f'protected-{i}',f'candidate-{i}',status,json.dumps({'watch_mode':'entry'}),strategy,json.dumps({'signal':signal}),self.now.isoformat(),self.now.isoformat()))
    rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(rid,self.now.isoformat(),json.dumps({'status':'verified','position':position,'orders':[],'as_of':self.now.isoformat()})))
   self.assertIsNone(engine.entry_for_holding(c,1,self.now))
 def test_capacity_uses_newer_held_observation_instead_of_old_absence(self):
  with app.connect() as c:
   strategy=c.execute("SELECT payload FROM hw_strategies WHERE strategy_id='escape_momentum' LIMIT 1").fetchone()['payload']
   c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,'entry-race',0,'race','automatic discovery','ACTIVE',?,'x',?,'{\"signal\":\"WAIT\"}',?,?,0)",(json.dumps({'watch_mode':'entry'}),strategy,self.now.isoformat(),self.now.isoformat()))
   rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
   old={'status':'verified','position':'none','orders':[],'as_of':(self.now-timedelta(seconds=1)).isoformat()}
   new={'status':'verified','position':'held','orders':[],'as_of':self.now.isoformat()}
   c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(rid,old['as_of'],json.dumps(old)))
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(rid,'eodhd','synthetic',self.now.timestamp(),self.now.isoformat(),json.dumps({'context':new}),'x'))
   self.assertIsNone(engine.entry_for_holding(c,1,self.now))
 def test_capacity_release_rejects_pending_buy_and_recent_orders(self):
  with app.connect() as c:
   strategy=c.execute("SELECT payload FROM hw_strategies WHERE strategy_id='escape_momentum' LIMIT 1").fetchone()['payload']
   for i,state in enumerate(({'signal':'WAIT','pending':'BUY'},{'signal':'WAIT'})):
    c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,?,0,?,'automatic discovery','ACTIVE',?,'x',?,?,?,?,0)",(f'pending-{i}',f'candidate-pending-{i}',json.dumps({'watch_mode':'entry'}),strategy,json.dumps(state),self.now.isoformat(),self.now.isoformat()))
    rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    context={'status':'verified','position':'none','orders':[] if i==0 else [{'order_id':'order'}],'as_of':self.now.isoformat()}
    c.execute('INSERT INTO hw_context_events(watch_row_id,observed,payload) VALUES(?,?,?)',(rid,self.now.isoformat(),json.dumps(context)))
   self.assertIsNone(engine.entry_for_holding(c,1,self.now))
 def test_reference_errors_are_specific_without_exception_content(self):
  import sqlite3
  for error,expected in [(KeyError('secret'),'REFERENCE_FIELD_MISSING'),(TypeError('secret'),'REFERENCE_TYPE_ERROR'),(ValueError('secret'),'REFERENCE_VALUE_ERROR'),(sqlite3.OperationalError('secret'),'REFERENCE_DATABASE_ERROR')]:
   self.assertEqual(service.reference_error_code(error),expected)
   self.assertNotIn('secret',service.reference_error_code(error))
 def test_legacy_recheck_leaves_verified_exit_and_kill_switch_unchanged(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  self.assertEqual(service.queue_unverified_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();self.assertEqual(json.loads(row['request'])['watch_mode'],'exit')
   c.execute("UPDATE hw_system_control SET killed=1 WHERE id=1")
   c.execute('DELETE FROM hw_verified_feed_links')
  self.assertEqual(service.queue_unverified_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT killed FROM hw_system_control WHERE id=1').fetchone()[0],1)
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT status FROM hw_sessions WHERE id=?',(row['id'],)).fetchone()[0],'CREATED')
 def test_provisional_verification_defers_concurrent_claim_without_starving_queue(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='TEST.US')
   c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(req),row['id']))
   c.execute('INSERT INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],'TEST.US','{}',self.now.isoformat()))
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(row['id'],self.now.timestamp()-1,'VERIFICATION_FAILED',self.now.isoformat()))
  def claim_during_verification(*_):
   with app.connect() as c:c.execute('UPDATE hw_sessions SET lease_until=? WHERE id=?',(self.now.timestamp()+2,row['id']))
   return self.instrument
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',side_effect=claim_during_verification),patch('hotwatch_adapters.search_eodhd_symbols',return_value=self.lookup()):
   self.assertEqual(service.verify_provisional_feeds(app.connect,self.now),0)
  with app.connect() as c:
   recovery=c.execute('SELECT status,next_attempt FROM hw_feed_recovery WHERE watch_row_id=?',(row['id'],)).fetchone()
   self.assertEqual(recovery['status'],'CONCURRENT_SESSION_BUSY');self.assertEqual(recovery['next_attempt'],self.now.timestamp()+60)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',side_effect=AssertionError('must not retry deferred watch')):
   self.assertEqual(service.verify_provisional_feeds(app.connect,self.now+timedelta(seconds=3)),0)
 def test_saved_share_class_alias_evidence_stays_verified_and_cannot_switch_class(self):
  instrument={'asset_id':'synthetic-berkshire','ticker':'BRK.B','name':'Berkshire Hathaway Class B','exchange':'NYSE','currency':'USD','type':'CS','isin':None}
  listing={'Code':'BRK-B','Name':'Berkshire Hathaway Inc','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US0846707026'}
  choices=[{'symbol':'BRK-B.US','exchange':'US','currency':'USD','isin':'US0846707026'}]
  catalog={'received_at':self.now.isoformat(),'rows':[listing]}
  with patch('eodhd_us_reference.get_reference',return_value=catalog):evidence=service.cxe_verified_match(instrument,choices,self.now,app.connect,1)
  self.assertEqual(evidence['symbol'],'BRK-B.US')
  service.remember_verified_feed(app.connect,1,dict(instrument,isin=evidence['isin']),evidence['symbol'],self.now,cxe_evidence=evidence)
  req={'asset_id':instrument['asset_id'],'ticker':'BRK.B','exchange':'NYSE','quote_currency':'USD','provider_symbol':'BRK-B.US'}
  with app.connect() as c:
   self.assertTrue(engine.valid_cxe_evidence(c,1,req,self.now))
   self.assertFalse(engine.valid_cxe_evidence(c,1,dict(req,ticker='BRK.A'),self.now))
   self.assertFalse(engine.valid_cxe_evidence(c,1,dict(req,provider_symbol='BRK-A.US'),self.now))
 def tick(self,**kwargs):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_CAPACITY':'40','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}):return service.auto_holdings_tick(app.connect,now=self.now,**kwargs)
 def test_verified_holding_creates_exit_only_session_and_never_restarts_stopped(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute("SELECT * FROM hw_sessions WHERE purpose='automatic holding watch'").fetchone();data=json.loads(row['request'])
   self.assertEqual(data['watch_mode'],'exit');self.assertEqual(data['portfolio_ids'],[self.pid]);self.assertEqual(data['provider_symbol'],'TEST.US')
   import dashboard_projection
   link=dashboard_projection.position_hotwatch(c,1,self.pid,self.holding['asset_id'],{'candidate_id':'other-candidate','trade_cycle_id':'other-cycle'})
   self.assertEqual(link['session']['watch_id'],row['watch_id']);self.assertEqual(link['link_basis'],'unique_asset_and_portfolio_scope')
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
  engine.control(app.connect,1,row['watch_id'],False,'stop',self.now)
  self.assertIsNone(self.tick(verify=self.verify,lookup=self.lookup))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_holding_autowatch').fetchone()[0],'STOPPED')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],1)
 def test_entry_only_watch_does_not_replace_position_monitoring(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT id,request FROM hw_sessions').fetchone();req=json.loads(row['request']);req['watch_mode']='entry';req['watch_id']='manual-entry-only';req['candidate_id']='manual-candidate';req['purpose']='manual entry'
   c.execute('UPDATE hw_sessions SET watch_id=?,candidate_id=?,purpose=?,request=? WHERE id=?',('manual-entry-only','manual-candidate','manual entry',json.dumps(req),row['id']))
   c.execute('DELETE FROM hw_holding_autowatch')
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   modes=[json.loads(row['request'])['watch_mode'] for row in c.execute('SELECT request FROM hw_sessions')]
  self.assertEqual(sorted(modes),['entry','exit'])
 def test_accepted_proposal_does_not_attribute_a_preexisting_holding(self):
  import hotwatch_strategy
  entry={'asset_id':self.holding['asset_id'],'watch_mode':'entry','trade_cycle_id':'cycle-original'}
  with app.connect() as c:
   c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,'entry-origin',0,'candidate-original','automatic discovery','ACTIVE',?,'synthetic',?,'{}',?,?,0)",(json.dumps(entry),json.dumps(hotwatch_strategy.EARLY_CATALYST_V1),self.now.isoformat(),self.now.isoformat()))
   payload={'orders':[{'assetId':self.holding['asset_id'],'side':'BUY'}]}
   response={'orderIntentId':'intent-synthetic','status':'ACCEPTED'}
   c.execute("INSERT INTO broker_proposals(user_id,fingerprint,report_id,candidate_id,kind,portfolio_id,payload,status,created,intent_id,response) VALUES(1,'synthetic','@hotwatch','entry-origin','direct',?,?,'sent',?,'intent-synthetic',?)",(self.pid,json.dumps(payload),self.now.timestamp(),json.dumps(response)))
   self.assertIsNone(service.holding_origin(c,1,self.pid,self.holding['asset_id']))
   c.execute("UPDATE broker_proposals SET response=?",(json.dumps({'orderIntentId':'intent-synthetic','status':'PENDING'}),))
   self.assertIsNone(service.holding_origin(c,1,self.pid,self.holding['asset_id']))
  def read_only_check(connect,uid,proposal_id):
   with connect() as c:c.execute('UPDATE broker_proposals SET response=? WHERE id=?',(json.dumps(response),proposal_id))
  with patch('trade_service.check',side_effect=read_only_check) as check:
   service.refresh_holding_origin(app.connect,1,self.pid,self.holding['asset_id']);self.assertEqual(check.call_count,1)
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute("SELECT request FROM hw_sessions WHERE purpose='automatic holding watch'").fetchone();req=json.loads(row['request'])
   self.assertNotIn('origin_candidate_id',req);self.assertNotIn('origin_trade_cycle_id',req);self.assertEqual(req['strategy_id'],'escape_momentum');self.assertEqual(req['portfolio_ids'],[self.pid]);self.assertEqual(req['watch_mode'],'exit')
 def test_manual_pause_is_preserved(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:wid=c.execute('SELECT watch_id FROM hw_sessions').fetchone()[0]
  engine.control(app.connect,1,wid,False,'pause',self.now)
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('paused watch must not be replaced'),lookup=self.lookup))
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_sessions').fetchone()[0],'PAUSED')
 def test_exit_watch_ends_only_on_fresh_complete_absence_and_reopens_on_new_holding(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   old=c.execute('SELECT watch_id FROM hw_sessions').fetchone()[0]
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':False,'observed':self.now.isoformat(),'positions':[]}),))
  self.assertEqual(service.reconcile_closed_holdings(app.connect,self.now),0)
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[]}),))
  self.assertEqual(service.reconcile_closed_holdings(app.connect,self.now),1)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_sessions WHERE watch_id=?',(old,)).fetchone()[0],'COMPLETED')
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[self.holding]}),))
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   sessions=c.execute('SELECT watch_id,status FROM hw_sessions ORDER BY id').fetchall();self.assertEqual(len(sessions),2);self.assertNotEqual(sessions[0]['watch_id'],sessions[1]['watch_id'])
 def test_ambiguous_eodhd_symbol_uses_verified_pluto_instead(self):
  bad=lambda *_:{'choices':[{'symbol':'ONE.US','currency':'USD','isin':'US1234567890'},{'symbol':'TWO.US','currency':'USD','isin':'US1234567890'}]}
  self.assertEqual(self.tick(verify=self.verify,lookup=bad),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT request FROM hw_sessions').fetchone();self.assertEqual(json.loads(row['request'])['provider'],'pluto')
 def test_failed_incomplete_or_stale_scope_does_not_start(self):
  with app.connect() as c:c.execute("UPDATE portfolio_snapshots SET last_error='unavailable'")
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('must not look up'),lookup=self.lookup))
  with app.connect() as c:c.execute("UPDATE portfolio_snapshots SET last_error=NULL,payload=?",(json.dumps({'positions_complete':False,'positions':[self.holding]}),))
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('must not look up'),lookup=self.lookup))
 def test_waiting_identity_does_not_reserve_unused_shared_capacity(self):
  with app.connect() as c:c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','VERIFYING',None,self.now.timestamp()+300,self.now.isoformat()))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(10):reserve(app.connect,1,'eodhd',self.now)
   for _ in range(2):reserve(app.connect,1,'eodhd',self.now,purpose='holding_identity')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now,purpose='holding_identity')
 def test_eodhd_budget_has_separate_default_and_respects_explicit_settings(self):
  with patch.dict(os.environ,{},clear=True):
   self.assertEqual(engine.provider_request_limit('eodhd'),800)
   self.assertEqual(engine.provider_request_limit('pluto'),12)
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'40'},clear=True):
   self.assertEqual(engine.provider_request_limit('eodhd'),40)
   self.assertEqual(engine.provider_request_limit('pluto'),12)
 def test_pluto_budget_is_shared_by_scan_and_identity_in_either_order(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   c.execute("UPDATE hw_sessions SET request=json_set(request,'$.provider','pluto'),next_due=?",(self.now.timestamp(),))
   c.execute("UPDATE hw_holding_autowatch SET status='VERIFYING'")
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'12'}):
   for at,first,second in [(self.now,'scan','identity'),(self.now+timedelta(minutes=1),'identity','scan')]:
    amounts={'scan':5,'identity':7}
    for _ in range(amounts[first]):reserve(app.connect,1,'pluto',at,purpose=first)
    for _ in range(amounts[second]):reserve(app.connect,1,'pluto',at,purpose=second)
    with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',at,purpose=second)
 def test_old_discovery_attempt_does_not_permanently_reserve_pluto_budget(self):
  with app.connect() as c:
   c.execute('INSERT INTO hw_discovery_attempts VALUES(?,?,?,?,?,?,?,?)',(1,0,'old-candidate','old-report','PROVIDER_RATE_BUDGET',self.now.isoformat(),self.now.timestamp(),None))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(12):reserve(app.connect,1,'pluto',self.now,purpose='scan')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',self.now,purpose='scan')
 def test_candidate_and_holding_checks_do_not_wait_for_alternating_minutes(self):
  with app.connect() as c:
   c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','VERIFYING',None,self.now.timestamp()+300,self.now.isoformat()))
   c.execute('INSERT INTO hw_discovery_attempts VALUES(?,?,?,?,?,?,?,?)',(1,0,self.fixture.report['candidates'][0]['candidate_id'],'trade-source','PROVIDER_RATE_BUDGET',self.now.isoformat(),self.now.timestamp(),None))
  at=self.now
  if int(at.timestamp()//60)%2:at+=timedelta(minutes=1)
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'12'}):
   reserve(app.connect,1,'pluto',at,purpose='candidate_identity')
   reserve(app.connect,1,'pluto',at,purpose='holding_identity')
   at+=timedelta(minutes=1)
   reserve(app.connect,1,'pluto',at,purpose='holding_identity')
   reserve(app.connect,1,'pluto',at,purpose='candidate_identity')
 def test_candidates_waiting_for_capacity_do_not_block_existing_identity_recovery(self):
  with app.connect() as c:
   c.execute('INSERT INTO hw_discovery_attempts VALUES(?,?,?,?,?,?,?,?)',(1,0,self.fixture.report['candidates'][0]['candidate_id'],'trade-source','global_capacity_limit',self.now.isoformat(),self.now.timestamp(),None))
  at=self.now
  if int(at.timestamp()//60)%2:at+=timedelta(minutes=1)
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(12):reserve(app.connect,1,'pluto',at,purpose='holding_identity')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'pluto',at,purpose='holding_identity')
 def test_pending_exchange_does_not_reserve_unused_capacity(self):
  with app.connect() as c:c.execute('INSERT INTO hw_exchange_status(exchange,next_attempt) VALUES(?,?)',('CO',self.now.timestamp()+60))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(11):reserve(app.connect,1,'eodhd',self.now)
   reserve(app.connect,1,'eodhd',self.now,purpose='exchange_status')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now,purpose='exchange_status')
 def test_feed_recovery_does_not_reserve_unused_capacity(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT id FROM hw_sessions').fetchone()
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(row['id'],self.now.timestamp(),'PLUTO_ISIN_MISSING',self.now.isoformat()))
  with patch.dict(os.environ,{'ESCAPE_HW_REQUESTS_PER_MINUTE':'12','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'12'}):
   for _ in range(10):reserve(app.connect,1,'eodhd',self.now)
   for _ in range(2):reserve(app.connect,1,'eodhd',self.now,purpose='holding_identity')
   with self.assertRaisesRegex(DataUnavailable,'PROVIDER_RATE_BUDGET'):reserve(app.connect,1,'eodhd',self.now,purpose='holding_identity')
 def test_runner_starts_the_automatic_holding_loop(self):
  runner=service.Runner(app.connect);calls=[]
  def activate(connect):
   calls.append(connect);runner.stop.set()
  with patch.object(service,'exchange_status_tick',return_value=None),patch.object(service,'auto_holdings_tick',side_effect=activate),patch.object(runner,'drain',return_value=0):runner.run(interval=0.01)
  self.assertEqual(calls,[runner.connect])
 def test_full_capacity_skips_external_lookups(self):
  with patch.object(engine,'capacity',return_value=0):
   status=self.tick(verify=lambda *_:self.fail('capacity must be checked first'),lookup=self.lookup)
  self.assertEqual(status,'CAPACITY_LIMIT')
 def test_reset_prioritizes_uncovered_holdings_and_retries_capacity_promptly(self):
  with app.connect() as c:
   self.assertTrue(service.pending_holding_slots(c,1,self.now))
   c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','CAPACITY_LIMIT',None,self.now.timestamp()+300,self.now.isoformat()))
  engine.reset_automatic_candidates(app.connect,1,self.now)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT next_attempt FROM hw_holding_autowatch').fetchone()[0],self.now.timestamp())
   self.assertTrue(service.pending_holding_slots(c,1,self.now))
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:self.assertFalse(service.pending_holding_slots(c,1,self.now))
 def test_candidate_waits_for_known_holding_after_reset(self):
  import report_ingest
  from test_intel_workflows import merc_report
  report=merc_report(False);report.update(report_id='priority-report',generated_at=self.now.isoformat(),positions=[],orders=[])
  candidate=report['candidates'][0];candidate.update(candidate_id='priority-scho',ticker='SCHO',company_name='Schouw & Co A/S',asset_id='priority-asset',exchange='CHIX')
  candidate['decision'].update(decided_at=self.now.isoformat(),data_as_of=self.now.isoformat(),deadline=(self.now+timedelta(hours=24)).isoformat())
  self.assertTrue(report_ingest.save(app.connect,1,report)[1]['ok'])
  engine.reset_automatic_candidates(app.connect,1,self.now-timedelta(seconds=1))
  with patch.object(engine,'capacity',return_value=1):blocked=service.auto_activate_candidate(app.connect,1,False,report,candidate,verify=lambda *_:self.fail('last slot belongs to owned holding'))
  self.assertEqual(blocked['status'],'HOLDINGS_PRIORITY')
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  instrument={'asset_id':'priority-asset','ticker':'SCHO','name':'Schouw & Co A/S','exchange':'CHIX','currency':'DKK','type':'CS','isin':None}
  result=service.auto_activate_candidate(app.connect,1,False,report,candidate,verify=lambda *_:instrument)
  self.assertEqual(result['status'],'CREATED')
 def test_missing_eodhd_key_uses_verified_pluto_without_eodhd_lookup(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   status=service.auto_holdings_tick(app.connect,verify=self.verify,lookup=lambda *_:self.fail('must not call EODHD'),now=self.now)
  self.assertEqual(status,'LINKED')
  with app.connect() as c:self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()[0])['provider'],'pluto')
 def test_missing_isin_does_not_prevent_verified_pluto_identity(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ','currency':'USD'}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw):
   instrument=service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'))
  self.assertIsNone(instrument['isin']);self.assertEqual(instrument['asset_id'],'synthetic-asset')
  self.assertEqual(self.tick(verify=lambda *_:instrument,lookup=lambda *_:self.fail('No ISIN means no automatic EODHD match')),'LINKED')
  with app.connect() as c:self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()[0])['provider'],'pluto')
 def test_crypto_search_candidate_does_not_enable_unverified_price_feed(self):
  instrument={'asset_id':'synthetic-asset','ticker':'BTC','name':'Bitcoin','exchange':'WINTERMUTE','currency':'USD','type':'CRYPTO','isin':None}
  holding=dict(self.holding,ticker='BTC',name='Bitcoin')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  choices={'choices':[{'symbol':'BTC-USD.CC','name':'Bitcoin','exchange':'CC','currency':'USD','isin':None}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()['request'])['provider'],'pluto')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_verified_feed_links').fetchone()[0],0)
 def test_btc_reference_preserves_eodhd_budget_reason_and_retry(self):
  instrument={'asset_id':'54368e0b-2d53-401e-bf68-1033a5b84b08','ticker':'BTC','name':'Bitcoin','type':'CRYPTO','exchange':'WINTERMUTE','currency':'USD','isin':None}
  for reason,expected in [('EODHD_DAILY_BUDGET','EODHD_DAILY_BUDGET'),('PROVIDER_RATE_BUDGET','PROVIDER_RATE_BUDGET'),('unknown','PROVIDER_RATE_BUDGET')]:
   with self.subTest(reason=reason),patch('eodhd_feeds.EODHDFeeds.snapshot',return_value={'status':'LOCAL_BUDGET_EXHAUSTED','budget_reason':reason,'retry_after_s':123}):
    with self.assertRaises(DataUnavailable) as caught:service.cxe_verified_match(instrument,[],self.now,app.connect,1)
    self.assertEqual(caught.exception.code,expected)
    self.assertEqual(caught.exception.retry_after_s,123)
 def test_owner_approved_btc_mapping_preserves_two_depots_and_existing_history(self):
  from test_hotwatch_engine import tick
  from hotwatch_adapters import EODHDAdapter
  aid='54368e0b-2d53-401e-bf68-1033a5b84b08';instrument={'asset_id':aid,'ticker':'BTC','name':'Bitcoin','type':'CRYPTO','exchange':'WINTERMUTE','currency':'USD','isin':None}
  quantities={self.fixture.root:'0.00019026',self.fixture.child:'0.0001914'}
  with app.connect() as c:
   for pid,qty in quantities.items():
    data={'positions_complete':True,'complete':True,'observed':self.now.isoformat(),'positions':[{'kind':'holding','asset_id':aid,'ticker':'BTC','name':'Bitcoin','quantity':qty}]}
    import portfolio_data
    portfolio_data.save(c,1,pid,data)
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  with app.connect() as c:
   before=c.execute('SELECT * FROM hw_sessions ORDER BY id').fetchall();self.assertEqual(len(before),2)
   for row in before:
    s=tick(self.now-timedelta(seconds=20),held=True);s.update(source='pluto',asset_id=aid,ticker='BTC',sample_id='historical-'+str(row['id']),market_status='UNKNOWN',session_key='legacy',bid=None,ask=None)
    c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],'pluto',s['sample_id'],(self.now-timedelta(seconds=20)).timestamp(),self.now.isoformat(),json.dumps(s),engine.checksum(s)))
    c.execute('UPDATE hw_sessions SET last_data=? WHERE id=?',(s['event_time'],row['id']))
  quote={'status':'OK','price':'75946.0234375','event_time':(self.now-timedelta(seconds=10)).isoformat()}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('eodhd_feeds.EODHDFeeds.snapshot',return_value=quote):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),2)
  with app.connect() as c:
   after=c.execute('SELECT * FROM hw_sessions ORDER BY id').fetchall();self.assertEqual([r['watch_id'] for r in after],[r['watch_id'] for r in before])
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],2)
   self.assertEqual(c.execute('SELECT count(*) FROM hw_verified_feed_links').fetchone()[0],1)
   self.assertEqual({tuple(json.loads(r['request'])['portfolio_ids']) for r in after},{(self.fixture.root,),(self.fixture.child,)})
   for row in after:
    req=json.loads(row['request']);self.assertEqual(req['provider_symbol'],'BTC-USD.CC');self.assertTrue(engine.valid_cxe_evidence(c,1,req,self.now))
   with patch.dict(os.environ,{'ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'0','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_FUSE_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'30'}):
    self.assertEqual(engine.effective_poll_interval(c,req),60)
    self.assertEqual(engine.effective_poll_interval(c,dict(req,asset_id='other-asset')),300)
    self.assertEqual(req['risk']['max_quote_age_s'],120)
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):return json.dumps({'code':'BTC-USD','timestamp':int(self.now.timestamp())-10,'close':'75946.0234375','currency':'USD'}).encode()
  outer=self
  class Opener:
   def open(self,*args,**kwargs):
    response=Response();response.now=outer.now;return response
  adapter=EODHDAdapter(app.connect,1,Opener())
  def context(req,currency):
   ctx=tick(self.now,held=True)['context'];ctx['quantity']=quantities[req['portfolio_ids'][0]];return ctx
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic','ESCAPE_HW_EODHD_FAST_POLL_ENABLED':'0','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE':'30','ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'0','ESCAPE_HW_EODHD_BARS_ENABLED':'0'}),patch('hotwatch_adapters.reserve'),patch.object(adapter.pluto,'safe_context',side_effect=context):
   for row in after:
    req=json.loads(row['request']);sample=adapter.poll({'id':row['id'],'request_data':req,'state':row['state']})
    self.assertEqual(sample['currency'],'USD');self.assertEqual(sample['context']['quantity'],quantities[req['portfolio_ids'][0]])
    out=engine.ingest(app.connect,1,row['watch_id'],False,sample,self.now)
    self.assertEqual(out['calculation']['signal'],'NO_DATA')
    self.assertEqual(out['session']['display_status'],'KURS MODTAGET · MARKEDSSTATUS UKENDT')
    self.assertEqual(out['session']['effective_min_interval_s'],60)
    self.assertEqual((engine.stamp(out['session']['next_due_at'])-self.now).total_seconds(),60)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],4)
   import dashboard_projection
   for row in after:
    pid=json.loads(row['request'])['portfolio_ids'][0]
    displayed=dashboard_projection.position_hotwatch(c,1,pid,aid,None)['session']
    self.assertEqual(displayed['display_status'],'KURS MODTAGET · MARKEDSSTATUS UKENDT');self.assertEqual(displayed['warmup']['count'],1);self.assertTrue(displayed['warmup']['historical'])
  from hotwatch_warmup import refresh
  end=self.now.replace(second=0,microsecond=0)
  bars=[{'bar_open_at':(end-timedelta(minutes=34-i)).isoformat(),'open':'100','high':'102','low':'99','close':'101','volume':'20'} for i in range(34)]
  class History:
   def intraday(self,symbol,interval,start,end):
    self.assertion=(symbol,interval);return {'status':'OK','bars':bars}
  feed=History();job=dict(after[-1]);job['request_data']=json.loads(job['request'])
  from unittest.mock import Mock
  runner=service.Runner(app.connect);adapter_stub=Mock();adapter_stub.poll.return_value=sample;runner.adapters[(1,'eodhd')]=adapter_stub;runner.health=Mock();runner.log=Mock()
  runner_job=dict(job,lease_owner='test-lease')
  with patch('hotwatch_service.engine.claim',return_value=runner_job),patch('hotwatch_service.engine.ingest',return_value={'calculation':{'signal':'NO_DATA'}}),patch('hotwatch_warmup.refresh') as refresh_call:
   self.assertTrue(runner.once(self.now));self.assertEqual(refresh_call.call_count,1)
  class ChangingIdentity:
   def intraday(self,symbol,interval,start,end):
    with app.connect() as c:c.execute('UPDATE hw_verified_feed_links SET verified_epoch=verified_epoch+1 WHERE asset_id=?',(aid,))
    return {'status':'OK','bars':bars}
  self.assertIsNone(refresh(app.connect,job,self.now,ChangingIdentity()))
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_warmup_history').fetchone()[0],0)
   c.execute('UPDATE hw_verified_feed_links SET verified_epoch=verified_epoch-1 WHERE asset_id=?',(aid,))
  self.assertEqual(refresh(app.connect,job,self.now,feed),'OK');self.assertEqual(feed.assertion,('BTC-USD.CC','1m'))
  with app.connect() as c:
   current=c.execute('SELECT * FROM hw_sessions WHERE id=?',(job['id'],)).fetchone();view=engine.view(c,current,self.now);warm=view['data_status']['analysis_warmup']
   self.assertEqual(warm['state'],'WARMUP COMPLETE');self.assertEqual(warm['count'],34);self.assertEqual(warm['freshness'],'FRESH');self.assertIsNotNone(warm['metrics']['ema_long']);self.assertEqual(view['signal'],'NO_DATA')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],4)
   self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)
   displayed=dashboard_projection.position_hotwatch(c,1,json.loads(job['request'])['portfolio_ids'][0],aid,None)['session'];self.assertEqual(displayed['display_status'],view['display_status']);self.assertEqual(displayed['warmup']['count'],1);self.assertTrue(displayed['warmup']['historical'])
  class WrongSymbol:
   def intraday(self,symbol,interval,start,end):return {'status':'OK','bars':[dict(bars[-1],symbol='OTHER-USD.CC')]}
  self.assertEqual(refresh(app.connect,job,self.now+timedelta(seconds=301),WrongSymbol()),'NO_VALID_BARS')
  with app.connect() as c:
   saved=c.execute('SELECT bars,status FROM hw_warmup_history WHERE watch_row_id=?',(job['id'],)).fetchone();self.assertEqual(len(json.loads(saved['bars'])),34);self.assertEqual(saved['status'],'NO_VALID_BARS')
  class PartialHistory:
   def intraday(self,symbol,interval,start,end):return {'status':'OK','bars':bars[-3:]}
  partial_job=dict(after[0]);partial_job['request_data']=json.loads(partial_job['request'])
  self.assertEqual(refresh(app.connect,partial_job,self.now,PartialHistory()),'OK')
  with app.connect() as c:
   for i in (1,2):
    at=end+timedelta(minutes=i);live=dict(sample,event_time=at.isoformat(),sample_id='future-fixture-'+str(i),price='102')
    c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(partial_job['id'],'eodhd',live['sample_id'],at.timestamp(),at.isoformat(),json.dumps(live),engine.checksum(live)))
   current=c.execute('SELECT * FROM hw_sessions WHERE id=?',(partial_job['id'],)).fetchone()
   from hotwatch_warmup import status as warmup_status
   partial=warmup_status(c,current,partial_job['request_data'],end+timedelta(minutes=2,seconds=1))
   self.assertEqual(partial['count'],5);self.assertEqual(partial['state'],'WARMUP');self.assertEqual(partial['remaining'],29)
  with app.connect() as c:
   current=c.execute('SELECT * FROM hw_sessions WHERE id=?',(after[-1]['id'],)).fetchone();stale=engine.view(c,current,self.now+timedelta(seconds=131))
   self.assertEqual(stale['data_status']['quote_freshness'],'STALE');self.assertEqual(stale['signal'],'NO_DATA')
   c.execute('DELETE FROM hw_cxe_feed_evidence')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch.object(adapter.pluto,'safe_context',return_value=tick(self.now,held=True)['context']):
   with self.assertRaisesRegex(DataUnavailable,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):adapter.poll({'id':after[-1]['id'],'request_data':req,'state':after[-1]['state']})
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):engine.ingest(app.connect,1,after[-1]['watch_id'],False,sample,self.now)
 def test_pepe_is_a_provisional_reference_and_cannot_use_external_prices(self):
  aid='4cde5f75-df03-4abc-9063-cfc588e31c11';instrument={'asset_id':aid,'ticker':'PEPE','name':'Pepe','type':'CRYPTO','exchange':'UKENDT','currency':'USD','isin':None}
  with app.connect() as c:
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[{'kind':'holding','asset_id':aid,'ticker':'PEPE','quantity':'1'}]}),))
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('eodhd_feeds.EODHDFeeds.snapshot',side_effect=AssertionError('PEPE must not use external quotes')):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();self.assertEqual(json.loads(row['request'])['provider'],'pluto')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_verified_feed_links').fetchone()[0],0)
  data=engine.item(app.connect,1,row['watch_id'],False)['session']['data_status'];self.assertEqual(data['reference_candidate']['symbol'],'PEPE24478-USD.CC');self.assertFalse(data['reference_candidate']['verified'])
  with app.connect() as c:
   req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='PEPE24478-USD.CC');c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(req),row['id']))
  from hotwatch_warmup import refresh
  pepe_job=dict(row);pepe_job['request_data']=req
  self.assertIsNone(refresh(app.connect,pepe_job,self.now,client=object()))
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_UNVERIFIED'):engine.ingest(app.connect,1,row['watch_id'],False,{},self.now)
 def test_complete_broker_identity_does_not_spend_second_lookup_for_missing_isin(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','name':'Test Inc','exchange':'NASDAQ','currency':'USD','type':'CS'}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw) as call:
   instrument=service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'))
  self.assertIsNone(instrument['isin']);self.assertEqual(instrument['type'],'CS');self.assertEqual(call.call_count,1)
 def test_missing_exchange_is_recovered_only_from_same_pluto_asset_id(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','currency':'USD'}}
  matches=[{'id':'another-asset','ticker':'TEST','exchange':'OTHER','currency':'USD'},{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ','currency':'USD'}]
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,matches]):
   instrument=service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'))
  self.assertEqual(instrument['exchange'],'NASDAQ');self.assertEqual(instrument['asset_id'],'synthetic-asset')
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,matches[:1]]):
   self.assertEqual(service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'))['exchange'],'UKENDT')
 def test_flat_pluto_asset_format_and_unknown_exchange_still_allow_position_monitoring(self):
  raw={'assetId':'synthetic-asset','ticker':'TEST','currency':'USD'}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,[]]):
   instrument=service.holding_instrument(app.connect,1,self.holding)
  self.assertEqual(instrument['asset_id'],'synthetic-asset');self.assertEqual(instrument['exchange'],'UKENDT')
  self.assertEqual(self.tick(verify=lambda *_:instrument,lookup=lambda *_:self.fail('No verified ISIN')),'LINKED')
  with app.connect() as c:self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()[0])['provider'],'pluto')
 def test_pluto_nested_isin_is_used_only_when_unambiguous(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ','currency':'USD','identifiers':[{'type':'ISIN','value':'US1234567890'}]}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw):
   self.assertEqual(service.holding_instrument(app.connect,1,self.holding)['isin'],'US1234567890')
  raw['asset']['isin']='US9999999999';diagnostic={}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value=raw):
   self.assertIsNone(service.holding_instrument(app.connect,1,self.holding,diagnostic))
  self.assertEqual(diagnostic['code'],'PLUTO_ASSET_METADATA_MISSING')
 def test_identity_diagnostics_explain_missing_and_conflicting_currency(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ'}};diagnostic={}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,[]]):self.assertIsNone(service.holding_instrument(app.connect,1,self.holding,diagnostic))
  self.assertEqual(diagnostic['code'],'PLUTO_CURRENCY_MISSING')
  diagnostic={};raw['asset']['currency']='EUR'
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,[]]):self.assertIsNone(service.holding_instrument(app.connect,1,dict(self.holding,currency='USD'),diagnostic))
  self.assertEqual(diagnostic['code'],'PLUTO_CURRENCY_MISMATCH')
  diagnostic={}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',return_value={'assetId':'different-asset','ticker':'TEST','currency':'USD'}):self.assertIsNone(service.holding_instrument(app.connect,1,self.holding,diagnostic))
  self.assertEqual(diagnostic['code'],'PLUTO_ASSET_ID_MISMATCH')
 def test_holding_worker_records_specific_failure_without_fabricating_a_session(self):
  raw={'asset':{'id':'synthetic-asset','ticker':'TEST','exchange':'NASDAQ'}}
  with patch('trade_service.client',return_value=(object(),{})),patch('trade_service.call',side_effect=[raw,[]]):
   self.assertEqual(self.tick(),'PLUTO_CURRENCY_MISSING')
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_holding_autowatch').fetchone()[0],'PLUTO_CURRENCY_MISSING')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_sessions').fetchone()[0],0)
 def test_verified_existing_candidate_feed_creates_separate_holding_watch(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(watch_mode='entry',purpose='candidate',watch_id='existing-candidate',candidate_id='existing-candidate')
   c.execute('UPDATE hw_sessions SET watch_id=?,candidate_id=?,purpose=?,request=? WHERE id=?',('existing-candidate','existing-candidate','candidate',json.dumps(req),row['id']))
   c.execute('DELETE FROM hw_holding_autowatch')
   sample={'verification':'verified','asset_id':'synthetic-asset','ticker':'TEST','currency':'USD'}
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],'eodhd','identity-evidence',self.now.timestamp(),self.now.isoformat(),json.dumps(sample),'digest'))
  with patch('hotwatch_service.holding_instrument',side_effect=AssertionError('reuse existing verified identity')),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=AssertionError('reuse existing verified feed')):
   self.assertEqual(self.tick(),'LINKED')
  with app.connect() as c:
   requests=[json.loads(r['request']) for r in c.execute('SELECT request FROM hw_sessions ORDER BY id')]
  self.assertEqual([r['watch_mode'] for r in requests],['entry','exit']);self.assertEqual(requests[1]['provider_symbol'],'TEST.US')
 def test_empty_automatic_session_recovers_only_from_recent_verified_identity(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  with app.connect() as c:
   old=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(old['request']);req.update(watch_mode='entry',purpose='candidate',watch_id='historical-candidate',candidate_id='historical-candidate')
   c.execute("UPDATE hw_sessions SET watch_id=?,candidate_id=?,purpose=?,request=?,status='COMPLETED' WHERE id=?",('historical-candidate','historical-candidate','candidate',json.dumps(req),old['id']))
   c.execute('DELETE FROM hw_holding_autowatch')
   sample={'verification':'verified','asset_id':'synthetic-asset','ticker':'TEST','currency':'USD'}
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(old['id'],'eodhd','evidence',self.now.timestamp(),self.now.isoformat(),json.dumps(sample),'digest'))
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=None):
   with app.connect() as c:c.execute('DELETE FROM hw_verified_feed_links')
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   service.remember_verified_feed(app.connect,1,self.instrument,'TEST.US',self.now)
   with app.connect() as c:c.execute("UPDATE hw_verified_feed_links SET verified_epoch=?",((self.now-timedelta(days=8)).timestamp(),))
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   with app.connect() as c:
    c.execute("UPDATE hw_verified_feed_links SET verified_epoch=?,currency='EUR'",(self.now.timestamp(),))
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   with app.connect() as c:
    c.execute("UPDATE hw_verified_feed_links SET currency='USD'")
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   row=c.execute("SELECT * FROM hw_sessions WHERE purpose='automatic holding watch'").fetchone();req=json.loads(row['request'])
   self.assertEqual((req['provider'],req['provider_symbol']),('eodhd','TEST.US'))
   self.assertEqual(c.execute("SELECT count(*) FROM hw_events WHERE watch_row_id=? AND event_type='PROVIDER_CHANGED'",(row['id'],)).fetchone()[0],1)
 def test_feed_recovery_chooses_oldest_due_attempt_before_session_id(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   first=dict(c.execute('SELECT * FROM hw_sessions').fetchone());first_id=first.pop('id')
   req=json.loads(first['request']);req.update(asset_id='synthetic-second',ticker='SECOND',watch_id='second-watch',candidate_id='second-candidate')
   first.update(watch_id='second-watch',candidate_id='second-candidate',request=json.dumps(req),digest='second-digest')
   cols=list(first);c.execute('INSERT INTO hw_sessions('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',tuple(first.values()))
   second_id=c.execute("SELECT id FROM hw_sessions WHERE watch_id='second-watch'").fetchone()['id']
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(first_id,self.now.timestamp()-1,'PROVIDER_RATE_BUDGET',self.now.isoformat()))
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(second_id,self.now.timestamp()-120,'PROVIDER_RATE_BUDGET',self.now.isoformat()))
  seen=[]
  def check(connect,uid,holding):seen.append(holding['ticker']);return None
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',side_effect=check):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  self.assertEqual(seen,['SECOND'])
 def test_feed_recovery_identifies_budget_provider_without_changing_public_status_or_retry(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}):
   for source in ('pluto','eodhd'):
    with self.subTest(source=source):
     with app.connect() as c:c.execute('DELETE FROM hw_feed_recovery')
     pluto=DataUnavailable('PROVIDER_RATE_BUDGET',429) if source=='pluto' else self.instrument
     eodhd=DataUnavailable('PROVIDER_RATE_BUDGET',429) if source=='eodhd' else AssertionError('EODHD must not be called')
     with patch('hotwatch_service.holding_instrument',side_effect=pluto if isinstance(pluto,Exception) else None,return_value=pluto),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=eodhd):
      self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
     with app.connect() as c:
      raw=c.execute('SELECT status,next_attempt FROM hw_feed_recovery').fetchone()
      self.assertEqual(raw['status'],source.upper()+'_RATE_BUDGET')
      self.assertEqual(raw['next_attempt'],self.now.timestamp()+60)
     session=engine.sync(app.connect,1,False,limit=1,session_limit=10,summary_only=True)['open_sessions'][0]
     self.assertEqual((session['feed_recovery_status'],session['feed_recovery_provider']),('PROVIDER_RATE_BUDGET',source))
     detail=engine.sync(app.connect,1,False,limit=1,session_limit=10,summary_only=False)['open_sessions'][0]
     self.assertEqual((detail['feed_recovery_status'],detail['feed_recovery_provider']),('PROVIDER_RATE_BUDGET',source))
   with app.connect() as c:c.execute("UPDATE hw_feed_recovery SET status='PROVIDER_RATE_BUDGET'")
   session=engine.sync(app.connect,1,False,limit=1,session_limit=10,summary_only=True)['open_sessions'][0]
   self.assertEqual((session['feed_recovery_status'],session['feed_recovery_provider']),('PROVIDER_RATE_BUDGET',None))
   with app.connect() as c:c.execute('DELETE FROM hw_feed_recovery')
   with patch('hotwatch_service.holding_instrument',return_value=self.instrument),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=DataUnavailable('EODHD_DAILY_BUDGET',429)):
    self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   session=engine.sync(app.connect,1,False,limit=1,session_limit=10,summary_only=True)['open_sessions'][0]
   self.assertEqual((session['feed_recovery_status'],session['feed_recovery_provider']),('EODHD_DAILY_BUDGET','eodhd'))
   for requested,delay in ((123,123),(float('nan'),60)):
    with app.connect() as c:c.execute('DELETE FROM hw_feed_recovery')
    error=DataUnavailable('PROVIDER_RATE_BUDGET',429);error.retry_after_s=requested
    with patch('hotwatch_service.holding_instrument',return_value=self.instrument),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=error):
     self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
    with app.connect() as c:self.assertEqual(c.execute('SELECT next_attempt FROM hw_feed_recovery').fetchone()['next_attempt'],self.now.timestamp()+delay)
 def test_extreme_recovery_retry_remains_readable_in_both_sync_modes(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  error=DataUnavailable('PROVIDER_RATE_BUDGET',429);error.retry_after_s=1e308
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=self.instrument),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=error):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:next_attempt=c.execute('SELECT next_attempt FROM hw_feed_recovery').fetchone()['next_attempt']
  self.assertGreater(next_attempt,self.now.timestamp()+86400)
  self.assertLessEqual(next_attempt,253402214400)
  for summary in (True,False):
   session=engine.sync(app.connect,1,False,limit=1,session_limit=10,summary_only=summary)['open_sessions'][0]
   self.assertEqual(session['next_feed_recovery_at'],'9999-12-31T00:00:00+00:00')
   self.assertEqual(session['feed_recovery_provider'],'eodhd')
  with app.connect() as c:c.execute('UPDATE hw_feed_recovery SET next_attempt=?',(1e308,))
  for summary in (True,False):
   session=engine.sync(app.connect,1,False,limit=1,session_limit=10,summary_only=summary)['open_sessions'][0]
   self.assertIsNone(session['next_feed_recovery_at'])
 def test_candidate_recovery_reports_pluto_budget_without_claiming_eodhd_failure(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(purpose='automatic discovery',watch_mode='entry',report_id='synthetic-report')
   c.execute("UPDATE hw_sessions SET purpose='automatic discovery',request=? WHERE id=?",(json.dumps(req),row['id']))
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.verified_discovery_instrument',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429)):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  session=engine.sync(app.connect,1,False,limit=1,session_limit=10,summary_only=True)['open_sessions'][0]
  self.assertEqual((session['watch_kind'],session['feed_recovery_status'],session['feed_recovery_provider']),('candidate','PROVIDER_RATE_BUDGET','pluto'))
 def test_candidate_recovery_reuses_only_connection_not_identity(self):
  import trade_service
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(purpose='automatic discovery',watch_mode='entry')
   c.execute("UPDATE hw_sessions SET purpose='automatic discovery',request=? WHERE id=?",(json.dumps(req),row['id']))
  calls=[]
  def request(client,method,params=None,notification=False):
   calls.append((method,(params or {}).get('name')))
   if method=='initialize':return {'protocolVersion':'2025-06-18'}
   if method=='notifications/initialized':return None
   if method=='tools/list':return {'tools':[{'name':name,'inputSchema':spec['inputSchema'],'annotations':{'readOnlyHint':spec['readOnlyHint']}} for name,spec in trade_service.CONTRACT.items()]}
   if params['name']=='search_assets':return {'structuredContent':{'assets':[{'id':'synthetic-asset','ticker':'TEST','name':'Test Company','exchange':'NASDAQ','currency':'USD'}]}}
   if params['name']=='get_asset':return {'structuredContent':{'asset':{'id':'synthetic-asset','ticker':'TEST','name':'Test Company','exchange':'NASDAQ','currency':'USD','type':'CS'}}}
   raise AssertionError(params)
  cache={}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('mcp_client.MCP.request',request),patch('hotwatch_adapters.reserve'),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429)):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now,identity_cache=cache),0)
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now+timedelta(seconds=61),identity_cache=cache),0)
   self.assertEqual(calls.count(('initialize',None)),1);self.assertEqual(calls.count(('tools/list',None)),1)
   # A rotated access token must create a new gateway and a new handshake.
   with patch('oauth.access_token',return_value='rotated-synthetic-token'):
    self.assertEqual(service.recover_automatic_feeds(app.connect,self.now+timedelta(seconds=122),identity_cache=cache),0)
  self.assertEqual(calls.count(('initialize',None)),2);self.assertEqual(calls.count(('tools/list',None)),2)
  self.assertEqual(calls.count(('tools/call','search_assets')),3);self.assertEqual(calls.count(('tools/call','get_asset')),3)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_verified_feed_links').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT status FROM hw_feed_recovery').fetchone()[0],'EODHD_RATE_BUDGET')
 def test_failed_cached_broker_connection_is_discarded(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(purpose='automatic discovery',watch_mode='entry')
   c.execute("UPDATE hw_sessions SET purpose='automatic discovery',request=? WHERE id=?",(json.dumps(req),row['id']))
  cache={}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.verified_discovery_instrument',side_effect=ConnectionError('synthetic secret')):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now,identity_cache=cache),0)
  self.assertEqual(cache,{})
 def test_pluto_budget_denial_keeps_established_connection_for_retry(self):
  import trade_service
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(purpose='automatic discovery',watch_mode='entry')
   c.execute("UPDATE hw_sessions SET purpose='automatic discovery',request=? WHERE id=?",(json.dumps(req),row['id']))
  calls=[];blocked=[True]
  def request(client,method,params=None,notification=False):
   name=(params or {}).get('name');calls.append((method,name))
   if method=='initialize':return {'protocolVersion':'2025-06-18'}
   if method=='notifications/initialized':return None
   if method=='tools/list':return {'tools':[{'name':name,'inputSchema':spec['inputSchema'],'annotations':{'readOnlyHint':spec['readOnlyHint']}} for name,spec in trade_service.CONTRACT.items()]}
   if name=='search_assets':
    if blocked[0]:blocked[0]=False;raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
    return {'structuredContent':{'assets':[{'id':'synthetic-asset','ticker':'TEST','name':'Test Company','exchange':'NASDAQ','currency':'USD'}]}}
   if name=='get_asset':return {'structuredContent':{'asset':{'id':'synthetic-asset','ticker':'TEST','name':'Test Company','exchange':'NASDAQ','currency':'USD','type':'CS'}}}
   raise AssertionError(name)
  cache={}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('mcp_client.MCP.request',request),patch('hotwatch_adapters.reserve'),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429)):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now,identity_cache=cache),0);self.assertIn(1,cache)
   with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_feed_recovery').fetchone()[0],'PLUTO_RATE_BUDGET')
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now+timedelta(seconds=61),identity_cache=cache),0)
  self.assertEqual(calls.count(('initialize',None)),1);self.assertEqual(calls.count(('tools/call','search_assets')),2);self.assertEqual(calls.count(('tools/call','get_asset')),1)
 def test_budget_during_handshake_discards_partial_connection(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(purpose='automatic discovery',watch_mode='entry')
   c.execute("UPDATE hw_sessions SET purpose='automatic discovery',request=? WHERE id=?",(json.dumps(req),row['id']))
  def request(client,method,params=None,notification=False):
   if method=='initialize':return {'protocolVersion':'2025-06-18'}
   if method=='notifications/initialized':raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
   raise AssertionError(method)
  cache={}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('mcp_client.MCP.request',request),patch('hotwatch_adapters.reserve'):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now,identity_cache=cache),0)
  self.assertEqual(cache,{})
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_feed_recovery').fetchone()[0],'PLUTO_RATE_BUDGET')
 def test_holding_connection_failure_does_not_discard_candidate_cache(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  adapter=object();cache={1:(1,adapter)}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',side_effect=ConnectionError('synthetic')):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now,identity_cache=cache),0)
  self.assertIs(cache[1][1],adapter)
 def test_candidate_recovery_replaces_expired_connection(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(purpose='automatic discovery',watch_mode='entry')
   c.execute("UPDATE hw_sessions SET purpose='automatic discovery',request=? WHERE id=?",(json.dumps(req),row['id']))
  expired=object();cache={1:(0,expired)}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.time.monotonic',return_value=300),patch('hotwatch_service.verified_discovery_instrument',return_value=None) as verify:
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now,identity_cache=cache),0)
  self.assertIsNot(verify.call_args.kwargs['adapter'],expired);self.assertIs(cache[1][1],verify.call_args.kwargs['adapter'])
 def test_candidate_recovery_connections_are_separate_per_user(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   c.execute("INSERT INTO users(username,salt,hash) VALUES('other','synthetic','synthetic')")
   row=dict(c.execute('SELECT * FROM hw_sessions').fetchone());row.pop('id')
   req=json.loads(row['request']);req.update(purpose='automatic discovery',watch_mode='entry')
   c.execute("UPDATE hw_sessions SET purpose='automatic discovery',request=?",(json.dumps(req),))
   req.update(watch_id='other-watch',candidate_id='other-candidate',asset_id='other-asset',ticker='OTHER')
   row.update(user_id=2,watch_id='other-watch',candidate_id='other-candidate',purpose='automatic discovery',request=json.dumps(req),digest='other-digest')
   cols=list(row);c.execute('INSERT INTO hw_sessions('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',tuple(row.values()))
  cache={};seen=[]
  def verify(connect,uid,holding,adapter=None):seen.append((uid,adapter));return None
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.verified_discovery_instrument',side_effect=verify):
   service.recover_automatic_feeds(app.connect,self.now,identity_cache=cache)
   service.recover_automatic_feeds(app.connect,self.now+timedelta(seconds=1),identity_cache=cache)
  self.assertEqual({uid for uid,_ in seen},{1,2});self.assertEqual(set(cache),{1,2});self.assertIsNot(cache[1][1],cache[2][1])
 def test_recovery_matches_isin_and_currency_without_prior_observation(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  choices={'choices':[{'symbol':'TEST.US','isin':self.instrument['isin'],'currency':'USD'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=self.instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT request FROM hw_sessions').fetchone();self.assertEqual(json.loads(row['request'])['provider_symbol'],'TEST.US')
 def test_recovery_does_not_guess_ambiguous_isin_match(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  choices={'choices':[{'symbol':'TEST.US','isin':self.instrument['isin'],'currency':'USD'},{'symbol':'TEST.X','isin':self.instrument['isin'],'currency':'USD'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=self.instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT status FROM hw_feed_recovery').fetchone()['status'],'EODHD_IDENTITY_UNCERTAIN')
   self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()['request'])['provider'],'pluto')
 def test_recovery_uses_us_catalog_when_search_omits_isin_and_currency(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  instrument=dict(self.instrument,name='Test Company',type='CS')
  choices={'choices':[{'symbol':'TEST.US','exchange':'US','isin':None,'currency':None}]}
  catalog={'received_at':self.now.isoformat(),'rows':[{'Code':'TEST','Name':'Test Company','Exchange':'NASDAQ','Currency':'USD','Country':'USA','Type':'Common Stock','Isin':instrument['isin']}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('eodhd_us_reference.get_reference',return_value=catalog):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT request FROM hw_sessions').fetchone();self.assertEqual(json.loads(row['request'])['provider_symbol'],'TEST.US')
   evidence=json.loads(c.execute('SELECT payload FROM hw_cxe_feed_evidence').fetchone()['payload'])
   self.assertEqual((evidence['basis'],evidence['isin']),('pluto_asset_us_listing',instrument['isin']))
 def test_us_catalog_recovery_rejects_conflicts_and_ambiguity(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  instrument=dict(self.instrument,name='Test Company',type='CS')
  listing={'Code':'TEST','Name':'Test Company','Exchange':'NASDAQ','Currency':'USD','Country':'USA','Type':'Common Stock','Isin':instrument['isin']}
  choice={'symbol':'TEST.US','exchange':'US','isin':None,'currency':None}
  cases=[([dict(listing,Isin='US9999999999')],[choice]),([dict(listing,Name='Different Issuer')],[choice]),([listing,listing],[choice]),([listing],[dict(choice,isin='US9999999999')]),([listing],[dict(choice,currency='EUR')])]
  for rows,choices in cases:
   with self.subTest(rows=rows,choices=choices):
    with app.connect() as c:c.execute('DELETE FROM hw_feed_recovery')
    catalog={'received_at':self.now.isoformat(),'rows':rows}
    with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value={'choices':choices}),patch('eodhd_us_reference.get_reference',return_value=catalog):
     self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
    with app.connect() as c:
     self.assertEqual(json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()['request'])['provider'],'pluto')
     self.assertEqual(c.execute('SELECT count(*) FROM hw_verified_feed_links').fetchone()[0],0)
 def test_candidate_recovery_uses_verified_us_catalog(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(purpose='automatic discovery',watch_mode='entry')
   c.execute("UPDATE hw_sessions SET purpose='automatic discovery',request=? WHERE id=?",(json.dumps(req),row['id']))
  instrument=dict(self.instrument,name='Test Company',type='CS')
  choices={'choices':[{'symbol':'TEST.US','exchange':'US','isin':None,'currency':None}]}
  catalog={'received_at':self.now.isoformat(),'rows':[{'Code':'TEST','Name':'Test Company','Exchange':'NASDAQ','Currency':'USD','Country':'USA','Type':'Common Stock','Isin':instrument['isin']}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.verified_discovery_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('eodhd_us_reference.get_reference',return_value=catalog):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   req=json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()['request'])
   self.assertEqual(req['provider_symbol'],'TEST.US')
   self.assertTrue(engine.verified_automatic_feed(c,1,req,self.now))
 def test_recovery_reports_missing_isin_without_guessing(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  instrument=dict(self.instrument,isin=None)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',side_effect=AssertionError('cannot match without ISIN')):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_feed_recovery').fetchone()['status'],'PLUTO_ISIN_MISSING')
 def test_provisional_match_requires_unique_issuer_ticker_currency_and_market(self):
  novo={'ticker':'NOVOB','name':'Novo Nordisk A/S','currency':'DKK','exchange':'CHIX'}
  choices=[{'symbol':'NVO.US','name':'Novo Nordisk A/S','exchange':'US','currency':'USD'},{'symbol':'NOVO-B.CO','name':'Novo Nordisk A/S','exchange':'CO','currency':'DKK'}]
  self.assertEqual(service.provisional_feed_match(novo,choices)['symbol'],'NOVO-B.CO')
  tsm={'ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Ltd.','currency':'USD','exchange':'NYSE'}
  us={'symbol':'TSM.US','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD'}
  self.assertEqual(service.provisional_feed_match(tsm,[us])['symbol'],'TSM.US')
  self.assertIsNone(service.provisional_feed_match(tsm,[us,dict(us)]))
  self.assertIsNone(service.provisional_feed_match(tsm,[dict(us,name='Different Company')]))
  self.assertIsNone(service.provisional_feed_match(tsm,[dict(us,currency='EUR')]))
  self.assertIsNone(service.provisional_feed_match(dict(tsm,exchange='UKENDT'),[us]))
  self.assertIsNone(service.provisional_feed_match(dict(tsm,ticker='TSMA'),[us]))
  asml={'ticker':'ASML','name':'ASML Holding NV','currency':'EUR','exchange':'CHIX'}
  amsterdam={'symbol':'ASML.AS','name':'ASML Holding NV','exchange':'AS','currency':'EUR'}
  frankfurt={'symbol':'ASML.F','name':'ASML Holding NV','exchange':'F','currency':'EUR'}
  self.assertEqual(service.provisional_feed_match(asml,[amsterdam])['symbol'],'ASML.AS')
  self.assertIsNone(service.provisional_feed_match(asml,[amsterdam,frankfurt]))
 def test_provisional_quote_is_visible_but_cannot_generate_a_signal_or_false_stop(self):
  from test_hotwatch_engine import tick
  holding=dict(self.holding,ticker='TSM')
  with app.connect() as c:
   payload={'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps(payload),))
  instrument={'asset_id':'synthetic-asset','ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Ltd.','exchange':'NYSE','currency':'USD','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  choices={'choices':[{'symbol':'TSM.US','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='TSM.US');req['risk']['stop_price']='105';c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(req),row['id']))
   c.execute('INSERT INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],'TSM.US',json.dumps({'pluto_venue':'NYSE','eodhd_venue':'US'}),self.now.isoformat()))
   self.assertEqual(req['provider_symbol'],'TSM.US')
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links WHERE watch_row_id=?',(row['id'],)).fetchone()[0],1)
  from hotwatch_adapters import EODHDAdapter,unknown_context
  calls=[]
  class Feed:
   def snapshot(self,symbol):calls.append(symbol);return {'status':'OK','event_time':self_now.isoformat(),'price':'100','volume':None}
   def capture(self,*args,**kwargs):raise AssertionError('unverified source must use one snapshot')
  self_now=self.now;adapter=EODHDAdapter(app.connect,1)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch.object(adapter,'feeds',return_value=Feed()),patch.object(adapter.pluto,'context',return_value=unknown_context()):
   with self.assertRaisesRegex(DataUnavailable,'EODHD_INSTRUMENT_UNVERIFIED'):
    adapter.poll({'id':row['id'],'request_data':req,'state':'{}'})
  self.assertEqual(calls,[])
  sample=tick(self.now,1,price='100',held=True)
  sample.update(source='eodhd',ticker='TSM',asset_id='synthetic-asset',market_status='UNKNOWN',session_key='test:UNKNOWN',feed_type='synthetic EODHD snapshot',bid=None,ask=None)
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_UNVERIFIED'):
   engine.ingest(app.connect,1,req['watch_id'],False,sample,self.now)
  # Simulate an already persisted observation from an older installed version.
  sample['verification']='unverified'
  with app.connect() as c:
   c.execute('INSERT INTO hw_samples(watch_row_id,source,sample_id,event_epoch,received,payload,digest) VALUES(?,?,?,?,?,?,?)',(row['id'],'eodhd',sample['sample_id'],self.now.timestamp(),self.now.isoformat(),json.dumps(sample),engine.checksum(sample)))
   c.execute('UPDATE hw_sessions SET last_data=? WHERE id=?',(self.now.isoformat(),row['id']))
   stored=json.loads(c.execute('SELECT payload FROM hw_samples').fetchone()['payload'])
  result=engine.item(app.connect,1,req['watch_id'],False)
  self.assertEqual(stored['verification'],'unverified')
  self.assertEqual(result['session']['signal'],'NO_DATA')
  self.assertIn('DATA_UNVERIFIED',result['session']['display_reason_codes'])
  self.assertIsNone(result['session']['data_status']['price'])
  self.assertEqual(result['session']['data_status']['price_status'],'UNVERIFIED')
  self.assertEqual(result['session']['display_status'],'KURSKILDE IKKE BEKRÆFTET')
  import dashboard_projection
  with app.connect() as c:
   position=dashboard_projection.position_hotwatch(c,1,self.pid,'synthetic-asset',None)
  self.assertEqual(position['session']['display_status'],'KURSKILDE IKKE BEKRÆFTET')
  self.assertIsNone(position['session']['warmup'])
  synced=engine.sync(app.connect,1,False,summary_only=True)
  self.assertEqual(synced['open_sessions'][0]['identity_verification'],'unverified')
  self.assertEqual(synced['open_sessions'][0]['last_data_at'],self.now.isoformat())
  verified=dict(instrument,isin='US1234567890');check_at=self.now+timedelta(minutes=6)
  with app.connect() as c:c.execute('UPDATE hw_feed_recovery SET next_attempt=0')
  wrong={'choices':[{'symbol':'DIFFERENT.US','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD','isin':'US1234567890'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=verified),patch('hotwatch_adapters.search_eodhd_symbols',return_value=wrong):
   self.assertEqual(service.verify_provisional_feeds(app.connect,check_at),0)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links').fetchone()[0],1)
   recovery=c.execute('SELECT next_attempt FROM hw_feed_recovery').fetchone()
   self.assertEqual(recovery['next_attempt'],check_at.timestamp()+300)
   # Existing installations may still have a six-hour retry from older code.
   c.execute("UPDATE hw_feed_recovery SET next_attempt=?,status='CXE_REFERENCE_INVALID'",(check_at.timestamp()+21600,))
  right={'choices':[{'symbol':'TSM.US','name':'Taiwan Semiconductor Manufacturing','exchange':'US','currency':'USD','isin':'US1234567890'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=verified),patch('hotwatch_adapters.search_eodhd_symbols',return_value=right):
   self.assertEqual(service.verify_provisional_feeds(app.connect,check_at+timedelta(minutes=4)),0)
   self.assertEqual(service.verify_provisional_feeds(app.connect,check_at+timedelta(minutes=6)),1)
  self.assertEqual(engine.sync(app.connect,1,False,summary_only=True)['open_sessions'][0]['identity_verification'],'unverified')
  at=check_at+timedelta(minutes=7);new_sample=tick(at,2,price='101',held=True)
  new_sample.update(source='eodhd',ticker='TSM',asset_id='synthetic-asset',market_status='UNKNOWN',session_key='test:UNKNOWN',feed_type='synthetic EODHD snapshot',bid=None,ask=None)
  refreshed=engine.ingest(app.connect,1,req['watch_id'],False,new_sample,at)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT count(*) FROM hw_samples').fetchone()[0],2)
   self.assertEqual(json.loads(c.execute('SELECT payload FROM hw_samples ORDER BY id DESC LIMIT 1').fetchone()['payload'])['verification'],'verified')
  self.assertEqual(refreshed['calculation']['supporting_metrics']['sample_count'],1)
  with patch('hotwatch_engine.utc',return_value=at):
   self.assertEqual(engine.sync(app.connect,1,False,summary_only=True)['open_sessions'][0]['identity_verification'],'verified')
 def test_asml_cxe_recovery_revalidates_and_blocks_changed_identity(self):
  holding=dict(self.holding,ticker='ASML')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  instrument={'asset_id':'synthetic-asset','ticker':'ASML','name':'ASML Holding NV','exchange':'CHIX','currency':'EUR','type':'CS','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  with app.connect() as c:before=c.execute('SELECT watch_id FROM hw_sessions').fetchone()['watch_id']
  from cxe_reference import parse_reference
  raw=('environment=PROD,created='+self.now.strftime('%Y-%m-%d')+',time='+self.now.strftime('%H:%MZ')+',warning=\n'
       'company_name,bats_name,isin,currency,mic,bloomberg_primary,asset_class,live,corporate_action_status\n'
       'ASML Holding NV,ASMLa,NL0010273215,EUR,XAMS,ASML NA Equity,EQTY,t,\n').encode()
  reference=parse_reference(raw,self.now)
  choices={'choices':[{'symbol':'ASML.AS','exchange':'AS','currency':None,'isin':'NL0010273215'},{'symbol':'ASML.F','exchange':'F','currency':'EUR','isin':'NL0010273215'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',return_value=reference):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);self.assertEqual(row['watch_id'],before);self.assertEqual(req['provider_symbol'],'ASML.AS')
   evidence=c.execute('SELECT * FROM hw_cxe_feed_evidence').fetchone();self.assertEqual(evidence['status'],'MATCHED');self.assertEqual(json.loads(evidence['payload'])['isin'],'NL0010273215');self.assertEqual(json.loads(evidence['payload'])['currency_basis'],'cxe_primary_listing')
   c.execute('UPDATE hw_cxe_feed_evidence SET next_attempt=0')
  from test_hotwatch_engine import tick
  sample=tick(self.now,1,held=True);sample.update(source='eodhd',ticker='ASML',asset_id='synthetic-asset',currency='EUR',venue='EODHD:AS',market_status='UNKNOWN',feed_type='synthetic EODHD quote',bid=None,ask=None)
  engine.ingest(app.connect,1,before,False,sample,self.now)
  state=engine.item(app.connect,1,before,False)['session']['data_status']
  self.assertEqual((state['holding_verified'],state['instrument_match_verified'],state['quote_feed_verified'],state['quote_freshness']),(True,True,True,'FRESH'))
  with app.connect() as c:
   original=c.execute('SELECT payload FROM hw_cxe_feed_evidence').fetchone()['payload'];tampered=json.loads(original);tampered['pluto']['currency']='USD'
   c.execute('UPDATE hw_cxe_feed_evidence SET payload=?',(json.dumps(tampered),))
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):
   engine.ingest(app.connect,1,before,False,dict(sample,sample_id='tampered-evidence'),self.now)
  with app.connect() as c:c.execute('UPDATE hw_cxe_feed_evidence SET payload=?',(original,))
  from cxe_reference import ReferenceUnavailable
  with patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',side_effect=ReferenceUnavailable('CXE_REFERENCE_UNAVAILABLE')):
   self.assertEqual(service.verify_cxe_feeds(app.connect,self.now+timedelta(minutes=1)),0)
  with app.connect() as c:
   retry=c.execute('SELECT status,payload FROM hw_cxe_feed_evidence').fetchone();self.assertEqual(retry['status'],'MATCHED');self.assertEqual(json.loads(retry['payload'])['last_revalidation_error'],'CXE_REFERENCE_UNAVAILABLE')
   c.execute('UPDATE hw_cxe_feed_evidence SET next_attempt=0')
  with patch('hotwatch_service.holding_instrument',return_value=dict(instrument,type='ADRC')),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices):
   self.assertEqual(service.verify_cxe_feeds(app.connect,self.now+timedelta(minutes=1)),0)
  with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM hw_cxe_feed_evidence').fetchone()['status'],'CONFLICT')
  failed=engine.item(app.connect,1,before,False)['session'];self.assertFalse(failed['data_status']['instrument_match_verified']);self.assertFalse(failed['data_status']['quote_feed_verified']);self.assertEqual(failed['signal'],'NO_DATA')
  with self.assertRaisesRegex(engine.EngineError,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):
   engine.ingest(app.connect,1,before,False,dict(sample,sample_id='inflight-after-conflict'),self.now+timedelta(minutes=1))
  from hotwatch_adapters import EODHDAdapter,unknown_context
  adapter=EODHDAdapter(app.connect,1)
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch.object(adapter.pluto,'context',return_value=unknown_context()):
   with self.assertRaisesRegex(DataUnavailable,'EODHD_INSTRUMENT_REVALIDATION_REQUIRED'):adapter.poll({'id':row['id'],'request_data':req,'state':'{}'})
 def test_observed_fcx_recovery_uses_exact_pluto_asset_and_catalog(self):
  aid='bea4a183-d3aa-4893-8071-87b85385e281';holding=dict(self.holding,asset_id=aid,ticker='FCX')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  instrument={'asset_id':aid,'ticker':'FCX','name':'Freeport-McMoran Inc.','exchange':'NYSE','currency':'USD','type':'CS','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  catalog={'received_at':self.now.isoformat(),'rows':[{'Code':'FCX','Name':'Freeport-McMoran Copper & Gold Inc','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US35671D8570'}]}
  choices={'choices':[{'symbol':'FCX.US','exchange':'US','currency':'USD','isin':'US35671D8570'},{'symbol':'FCX.MX','exchange':'MX','currency':'MXN','isin':None}]}
  with app.connect() as c:before=c.execute('SELECT watch_id FROM hw_sessions').fetchone()['watch_id']
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('eodhd_us_reference.get_reference',return_value=catalog):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();request=json.loads(row['request']);self.assertEqual(row['watch_id'],before);self.assertEqual(request['provider_symbol'],'FCX.US')
   self.assertTrue(engine.valid_cxe_evidence(c,1,request,self.now))
   c.execute('INSERT INTO hw_exchange_status(exchange,received,is_open,next_attempt) VALUES(?,?,?,?)',('US',self.now.isoformat(),0,self.now.timestamp()+300))
   view=engine.view(c,row,self.now);self.assertEqual(view['display_status'],'MARKED LUKKET (ORDINÆR HANDEL)');self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['data_status']['price'])
  from hotwatch_warmup import refresh
  end=self.now.replace(second=0,microsecond=0)
  bars=[{'bar_open_at':(end-timedelta(minutes=34-i)).isoformat(),'open':'100','high':'102','low':'99','close':'101','volume':'20'} for i in range(34)]
  class Feed:
   def intraday(self,symbol,interval,start,end):return {'status':'OK','bars':bars}
  job=dict(row);job['request_data']=request;self.assertEqual(refresh(app.connect,job,self.now,Feed()),'OK')
  with app.connect() as c:
   actual=c.execute('SELECT * FROM hw_sessions WHERE id=?',(row['id'],)).fetchone();view=engine.view(c,actual,self.now)
   self.assertEqual(view['data_status']['analysis_warmup']['state'],'WARMUP COMPLETE');self.assertEqual(view['signal'],'NO_DATA');self.assertIsNone(view['latest_calculation'])
 def test_tsm_adr_recovers_from_us_catalog_and_preserves_adr_evidence(self):
  holding=dict(self.holding,ticker='TSM')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  instrument={'asset_id':'synthetic-asset','ticker':'TSM','name':'Taiwan Semiconductor Manufacturing Company Ltd.','exchange':'NYSE','currency':'USD','type':'ADRC','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  reference={'created_at':self.now.isoformat(),'rows':[{'symbol':'TSFAd','name':'Taiwan Semiconductor Manufacturing Co Ltd','isin':'US8740391003','currency':'EUR','instrument_type':'EQTY','mic':'XFRA'}]}
  catalog={'received_at':self.now.isoformat(),'rows':[{'Code':'TSM','Name':'Taiwan Semiconductor Manufacturing','Country':'USA','Exchange':'NYSE','Currency':'USD','Type':'Common Stock','Isin':'US8740391003'}]}
  choices={'choices':[{'symbol':'TSM.US','exchange':'US','currency':'USD','isin':'US8740391003'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',side_effect=AssertionError('US listing must not depend on Cboe')),patch('eodhd_us_reference.get_reference',return_value=catalog):
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),1)
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();request=json.loads(row['request']);self.assertEqual(request['provider_symbol'],'TSM.US')
   evidence=json.loads(c.execute('SELECT payload FROM hw_cxe_feed_evidence').fetchone()['payload']);self.assertEqual(evidence['pluto_type'],'ADRC');self.assertEqual(evidence['catalog_type'],'Common Stock');self.assertIn('ADR',evidence['type_note'])
  current=engine.item(app.connect,1,row['watch_id'],False)['session']['data_status']
  self.assertTrue(current['instrument_match_verified']);self.assertEqual(current['identity_verification'],'verified');self.assertFalse(current['quote_feed_verified'])
  reused=service.verified_existing_feed(app.connect,1,{'asset_id':'synthetic-asset','ticker':'TSM','currency':'USD'},self.now)
  self.assertEqual(reused['provider_symbol'],'TSM.US')
  self.assertIsNone(service.verified_existing_feed(app.connect,1,{'asset_id':'synthetic-asset','ticker':'TSM','currency':'EUR'},self.now))
  with app.connect() as c:
   original=c.execute('SELECT payload FROM hw_cxe_feed_evidence').fetchone()['payload'];legacy=json.loads(original)
   legacy.update(basis='pluto_asset_us_catalog_cxe_security_isin',reference_source='https://accounteu.cboe.com/cxe/market_data/symbol_listing/csv/',reference_created_at=(self.now-timedelta(days=5)).isoformat(),cxe_symbols=['TSFAd'])
   c.execute('UPDATE hw_cxe_feed_evidence SET payload=?',(json.dumps(legacy),))
  self.assertTrue(engine.item(app.connect,1,row['watch_id'],False)['session']['data_status']['instrument_match_verified'])
  with app.connect() as c:c.execute('UPDATE hw_cxe_feed_evidence SET payload=?',(original,))
  from test_hotwatch_engine import tick
  sample=tick(self.now,1,held=True);sample.update(source='eodhd',ticker='TSM',asset_id='synthetic-asset',currency='USD',venue='EODHD:US',market_status='UNKNOWN',feed_type='synthetic EODHD quote',bid=None,ask=None)
  engine.ingest(app.connect,1,row['watch_id'],False,sample,self.now)
  status=engine.sync(app.connect,1,False,summary_only=True)['open_sessions'][0]
  self.assertTrue(status['instrument_match_verified']);self.assertTrue(status['quote_feed_verified']);self.assertEqual(status['instrument_match_evidence']['pluto_type'],'ADRC')
  self.assertEqual(status['status'],'DEGRADED')
  calculation=engine.item(app.connect,1,row['watch_id'],False)['session']['latest_calculation']
  self.assertEqual(calculation['signal'],'NO_DATA');self.assertIn('MARKET_STATUS_UNKNOWN',calculation['reason_codes'])
 def test_existing_novob_provisional_is_rechecked_without_losing_history(self):
  holding=dict(self.holding,ticker='NOVOB')
  with app.connect() as c:c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps({'positions_complete':True,'observed':self.now.isoformat(),'positions':[holding]}),))
  instrument={'asset_id':'synthetic-asset','ticker':'NOVOB','name':'Novo Nordisk A/S','exchange':'CHIX','currency':'DKK','type':'CS','isin':None}
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=lambda *_:instrument,now=self.now),'LINKED')
  with app.connect() as c:
   row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request']);req.update(provider='eodhd',provider_symbol='NOVO-B.CO')
   c.execute('UPDATE hw_sessions SET request=? WHERE id=?',(json.dumps(req),row['id']))
   c.execute('INSERT INTO hw_provisional_feed_links VALUES(?,?,?,?)',(row['id'],'NOVO-B.CO','{}',self.now.isoformat()))
   c.execute('INSERT INTO hw_feed_recovery VALUES(?,?,?,?)',(row['id'],self.now.timestamp()+21600,'PLUTO_ISIN_MISSING',self.now.isoformat()))
  reference={'created_at':self.now.isoformat(),'rows':[{'symbol':'NOVOBc','primary_ticker':'NOVOB','name':'Novo Nordisk A/S','isin':'DK0062498333','currency':'DKK','instrument_type':'EQTY','mic':'XCSE'}]}
  choices={'choices':[{'symbol':'NOVO-B.CO','exchange':'CO','currency':'DKK','isin':'DK0062498333'}]}
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',return_value=instrument),patch('hotwatch_adapters.search_eodhd_symbols',return_value=choices),patch('cxe_reference.get_reference',return_value=reference):
   self.assertEqual(service.verify_provisional_feeds(app.connect,self.now),1)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT watch_id FROM hw_sessions').fetchone()['watch_id'],row['watch_id'])
   self.assertEqual(c.execute('SELECT count(*) FROM hw_provisional_feed_links').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT isin FROM hw_verified_feed_links').fetchone()['isin'],'DK0062498333')
   self.assertTrue(c.execute("SELECT 1 FROM hw_events WHERE event_type='INSTRUMENT_VERIFIED'").fetchone())
 def test_recovery_respects_global_and_user_kill_switches(self):
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with patch.dict(os.environ,{'ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':'synthetic'}),patch('hotwatch_service.holding_instrument',side_effect=AssertionError('must not call provider')):
   with app.connect() as c:c.execute('UPDATE hw_system_control SET killed=1 WHERE id=1')
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
   with app.connect() as c:
    c.execute('UPDATE hw_system_control SET killed=0 WHERE id=1')
    c.execute("INSERT INTO hw_control VALUES(1,1,'test',?) ON CONFLICT(user_id) DO UPDATE SET killed=1",(self.now.isoformat(),))
   self.assertEqual(service.recover_automatic_feeds(app.connect,self.now),0)
 def test_rate_budget_retry_waits_until_next_minute_not_five_minutes(self):
  def blocked(*_):raise DataUnavailable('PROVIDER_RATE_BUDGET',429)
  self.assertEqual(self.tick(verify=self.verify,lookup=blocked),'PROVIDER_RATE_BUDGET')
  with app.connect() as c:row=c.execute('SELECT next_attempt FROM hw_holding_autowatch').fetchone()
  self.assertGreater(row['next_attempt'],self.now.timestamp());self.assertLessEqual(row['next_attempt']-self.now.timestamp(),61)
 def test_existing_budget_delay_is_shortened_safely_on_startup(self):
  with app.connect() as c:c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','PROVIDER_RATE_BUDGET',None,self.now.timestamp()+300,self.now.isoformat()))
  with patch('hotwatch_engine.utc',return_value=self.now):app.init()
  with app.connect() as c:row=c.execute('SELECT status,next_attempt FROM hw_holding_autowatch').fetchone()
  self.assertEqual(row['status'],'PROVIDER_RATE_BUDGET');self.assertGreater(row['next_attempt'],self.now.timestamp());self.assertLessEqual(row['next_attempt']-self.now.timestamp(),61)
 def test_old_identity_failures_retry_promptly_after_upgrade(self):
  with app.connect() as c:c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,'synthetic-asset','IDENTITY_UNVERIFIED',None,self.now.timestamp()+300,self.now.isoformat()))
  with patch('hotwatch_engine.utc',return_value=self.now):app.init()
  with app.connect() as c:row=c.execute('SELECT status,next_attempt FROM hw_holding_autowatch').fetchone()
  self.assertEqual(row['status'],'IDENTITY_UNVERIFIED');self.assertEqual(row['next_attempt'],self.now.timestamp()+10)
 def test_pluto_fallback_reads_exact_owned_position_and_source_time(self):
  from hotwatch_adapters import PlutoAdapter,unknown_context
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:row=c.execute('SELECT * FROM hw_sessions').fetchone();req=json.loads(row['request'])
  quote={'asset_id':'synthetic-asset','ticker':'TEST','currency':'USD','exchange':'NASDAQ','price':'100','price_time':self.now.isoformat()}
  with patch('market_data.quote',return_value=quote) as get_quote,patch.object(PlutoAdapter,'context',return_value=unknown_context()):
   sample=PlutoAdapter(app.connect,1).poll({'request_data':req})
  self.assertEqual(sample['source'],'pluto');self.assertEqual(sample['event_time'],self.now.isoformat());self.assertEqual(get_quote.call_args.args[2],{'holding_portfolio_id':self.pid,'holding_asset_id':'synthetic-asset'})
 def test_budget_blocked_broker_context_does_not_discard_timestamped_price(self):
  from hotwatch_adapters import PlutoAdapter
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_EODHD_REST_ENABLED':'1','ESCAPE_EODHD_API_KEY':''}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=self.verify,now=self.now),'LINKED')
  with app.connect() as c:req=json.loads(c.execute('SELECT request FROM hw_sessions').fetchone()['request'])
  quote={'asset_id':'synthetic-asset','ticker':'TEST','currency':'USD','exchange':'NASDAQ','price':'100','price_time':self.now.isoformat()}
  with patch('market_data.quote',return_value=quote),patch.object(PlutoAdapter,'context',side_effect=DataUnavailable('PROVIDER_RATE_BUDGET',429)):
   sample=PlutoAdapter(app.connect,1).poll({'request_data':req})
  self.assertEqual(sample['price'],'100');self.assertEqual(sample['event_time'],self.now.isoformat())
  self.assertEqual(sample['context']['status'],'unknown');self.assertEqual(sample['context']['tradability'],'unknown')
  self.assertEqual(sample['context']['diagnostic'],'PROVIDER_RATE_BUDGET')
 def test_old_snapshot_is_not_used(self):
  with app.connect() as c:
   payload={'positions_complete':True,'observed':(self.now-timedelta(minutes=6)).isoformat(),'positions':[self.holding]}
   c.execute('UPDATE portfolio_snapshots SET payload=?',(json.dumps(payload),))
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('stale snapshot'),lookup=self.lookup))
 def test_global_kill_and_disabled_setting_prevent_activation(self):
  with app.connect() as c:c.execute('UPDATE hw_system_control SET killed=1 WHERE id=1')
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('kill switch'),lookup=self.lookup))
  with app.connect() as c:c.execute('UPDATE hw_system_control SET killed=0 WHERE id=1')
  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'0'}):self.assertIsNone(service.auto_holdings_tick(app.connect,verify=lambda *_:self.fail('disabled'),lookup=self.lookup,now=self.now))
 def test_existing_watch_is_reused_and_kill_switch_respected(self):
  self.assertEqual(self.tick(verify=self.verify,lookup=self.lookup),'LINKED')
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('duplicate lookup'),lookup=self.lookup))
  with app.connect() as c:
   c.execute("INSERT INTO hw_control VALUES(1,1,'stop',?) ON CONFLICT(user_id) DO UPDATE SET killed=1",(self.now.isoformat(),))
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('kill switch'),lookup=self.lookup))
