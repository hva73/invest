"""Automatic holding watches use synthetic owned snapshots and no provider calls."""
import hashlib,json,os,sqlite3,tempfile,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,hotwatch_engine as engine,hotwatch_service as service
from hotwatch_adapters import reserve,DataUnavailable
import test_trade_service as fixtures

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

class HoldingAutowatchPerformance(unittest.TestCase):
 def test_idle_linked_scan_statement_budget(self):
  self._check_idle_linked_scan_statement_budget(concurrent=False)

 def test_repeated_unrelated_commits_do_not_starve_next_tenant(self):
  self._check_idle_linked_scan_statement_budget(concurrent=True)

 def _check_idle_linked_scan_statement_budget(self,concurrent):
  now=datetime(2026,11,25,12,tzinfo=timezone.utc)
  at=now.isoformat()
  aid='shared-idle'
  payload=json.dumps({'positions_complete':True,'observed':at,'positions':[
   {'kind':'holding','asset_id':aid,'quantity':'1'}]})
  for count in (1,10,100):
   with self.subTest(users=count),tempfile.TemporaryDirectory() as temp,patch.object(app,'DB',temp+'/db'):
    app.init()
    expected=[]
    with app.connect() as c:
     if concurrent:c.execute("INSERT INTO users(id,username,active) VALUES(?,'unrelated',0)",(count+1,))
     for uid in range(1,count+1):
      pid=2*uid
      watch=f'paused-{uid}'
      c.execute('INSERT INTO users(id,username,active) VALUES(?,?,1)',(uid,f'user-{uid}'))
      c.execute("INSERT INTO portfolios(id,user_id,name,source,updated) VALUES(?,?,'Test','pluto',?)",(pid,uid,now.timestamp()))
      c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(pid,uid,at,payload,at))
      request=json.dumps({'asset_id':aid,'portfolio_ids':[pid],'watch_mode':'exit'})
      c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                   VALUES(?,?,0,?,'test holding','PAUSED',?,'synthetic','{}','{}',?,?,0)""",(uid,watch,aid,request,at,at))
      attempt=(uid,pid,aid,'LINKED',watch,0,at)
      c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',attempt)
      expected.append(attempt)
    statements=[];reads={};decoded=[]
    execute=app.DatabaseConnection.execute
    def count_rows(cursor,values):
     row=sqlite3.Row(cursor,values)
     if 'kind' in row.keys():decoded.append((row['kind'],cursor.connection.in_transaction))
     return row
    def traced_connect():
     connection=app.connect()
     connection.set_trace_callback(statements.append)
     connection.row_factory=count_rows
     return connection
    def race(connection,sql,*args):
     cursor=execute(connection,sql,*args)
     if concurrent and 'CROSS JOIN hw_holding_autowatch' in sql:
      rows=cursor.fetchall()
      uid=args[0][0]
      reads[uid]=reads.get(uid,0)+1
      self.assertLessEqual(reads[uid],2)
      with app.connect() as writer:
       writer.execute('UPDATE users SET username=? WHERE id=?',(f'unrelated-{uid}-{reads[uid]}',count+1))
      return rows
     return cursor
    with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1'}),patch.object(app.DatabaseConnection,'execute',race):
     self.assertIsNone(service.auto_holdings_tick(traced_connect,verify=lambda *_:self.fail('Unexpected activation'),now=now))
    self.assertEqual(len(statements),2+(3 if concurrent else 2)*count)
    self.assertTrue(all(sql.lstrip().upper().startswith(('SELECT','WITH','PRAGMA DATA_VERSION')) for sql in statements))
    passes=2 if concurrent else 1
    if concurrent:self.assertEqual(reads,dict.fromkeys(range(1,count+1),passes))
    self.assertEqual(decoded,[('session',False),('attempt',False)]*count*passes)
    with app.connect() as c:
     self.assertEqual([tuple(row) for row in c.execute('SELECT * FROM hw_holding_autowatch ORDER BY user_id')],expected)
     self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE status='PAUSED'").fetchone()[0],count)

 def test_scoped_reads_and_decisions_for_1_10_and_100_users(self):
  now=datetime(2026,11,25,12,tzinfo=timezone.utc)
  at=now.isoformat()
  closed_at=(now-timedelta(hours=1)).isoformat()
  future=now.timestamp()+600
  assets=[f'shared-{i:02}' for i in range(26)]
  positions=[{'kind':'holding','asset_id':aid,'quantity':'1'} for aid in assets]
  for count in (1,10,100):
   with self.subTest(users=count),tempfile.TemporaryDirectory() as temp,patch.object(app,'DB',temp+'/db'):
    app.init()
    killed=set(range(7,count,7))
    expected={}
    with app.connect() as c:
     for uid in range(1,count+1):
      pid=uid*2
      c.execute('INSERT INTO users(id,username,active) VALUES(?,?,1)',(uid,f'user-{uid}'))
      if uid in killed:c.execute('INSERT INTO hw_control VALUES(?,1,?,?)',(uid,at,'test'))
      for portfolio,holdings in ((pid,positions[:1]+positions),(pid+1,positions[:1])):
       c.execute("INSERT INTO portfolios(id,user_id,name,source,updated) VALUES(?,?,?,'pluto',?)",(portfolio,uid,'Test',now.timestamp()))
       payload=json.dumps({'positions_complete':True,'observed':at,'positions':holdings})
       c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(portfolio,uid,at,payload,at))
      paused=f'paused-{uid}'
      stopped=f'stopped-{uid}'
      for aid,wid,status in ((assets[0],paused,'PAUSED'),(assets[1],stopped,'COMPLETED'),(assets[22],f'closed-{uid}','COMPLETED')):
       request=json.dumps({'asset_id':aid,'portfolio_ids':[pid],'watch_mode':'exit'})
       c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                    VALUES(?,?,0,?,'test holding',?,?,'synthetic','{}','{}',?,?,0)""",
                 (uid,wid,aid,status,request,at,at))
      for portfolio,aid in [(pid,aid) for aid in assets[1:]]+[(pid+1,assets[0])]:
       status,watch_id=('LINKED',stopped) if aid==assets[1] else ('POSITION_CLOSED',f'closed-{uid}')
       retry=0 if uid==count and aid in assets[22:] else future
       c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(uid,portfolio,aid,status,watch_id,retry,closed_at))
       if uid not in killed and aid==assets[1]:status,retry='STOPPED',now.timestamp()+300
       expected[uid,portfolio,aid]=(status,watch_id,retry)
      if uid not in killed:expected[uid,pid,assets[0]]=('LINKED',paused,now.timestamp()+300)
    # Trace the scan connection separately from the locked activation revalidation.
    scan_sql=[];connections=[];verified=[]
    def traced_connect():
     connection=app.connect()
     if not connections:connection.set_trace_callback(scan_sql.append)
     connections.append(True)
     return connection
    def verify(_,uid,holding):
     verified.append((uid,holding['asset_id']))
     return {'asset_id':holding['asset_id'],'ticker':'TEST','exchange':'NASDAQ','currency':'USD'}
    with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_CAPACITY':'200','ESCAPE_HW_EODHD_REST_ENABLED':'0'}):
     self.assertEqual(service.auto_holdings_tick(traced_connect,verify=verify,now=now),'LINKED')
    self.assertEqual(verified,[(count,assets[22])])
    reads=[sql for sql in scan_sql if sql.lstrip().upper().startswith(('SELECT','WITH'))]
    # The last user activates within the first multi-position batch.
    # Other enabled users also scan the remaining assets and second portfolio.
    enabled=count-len(killed)
    batches=4*(enabled-1)+3
    history_reads=[sql for sql in reads if "SELECT 'history'" in sql]
    self.assertEqual(len(reads)-len(history_reads),1+len(killed)+batches)
    self.assertEqual(len(history_reads),26*(enabled-1)+22)
    self.assertEqual(scan_sql.count('PRAGMA data_version'),2)
    self.assertEqual(sum('hw_holding_autowatch' in sql for sql in reads),len(killed)+batches)
    self.assertEqual(sum('INSERT INTO hw_holding_autowatch' in sql and "'LINKED'" in sql for sql in scan_sql),count-len(killed))
    identity=f'{count}|{count*2}|{assets[22]}|{closed_at}'
    watch='hw-holding-'+hashlib.sha256(identity.encode()).hexdigest()[:28]
    expected[count,count*2,assets[22]]=('LINKED',watch,now.timestamp()+300)
    with app.connect() as c:
     actual={(r[0],r[1],r[2]):tuple(r)[3:] for r in c.execute('SELECT user_id,portfolio_id,asset_id,status,watch_id,next_attempt FROM hw_holding_autowatch')}
     self.assertEqual(actual,expected)
     created=c.execute("SELECT user_id,watch_id,request FROM hw_sessions WHERE purpose='automatic holding watch'").fetchall()
     self.assertEqual([(row['user_id'],row['watch_id']) for row in created],[(count,watch)])
     request=json.loads(created[0]['request'])
     self.assertEqual((request['watch_mode'],request['portfolio_ids']),('exit',[count*2]))
     self.assertEqual(c.execute("SELECT count(*) FROM hw_sessions WHERE status='PAUSED'").fetchone()[0],count)

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
 def _check_early_activation_history(self,link_first,already_linked=0,extra_history=0):
  at=self.now.isoformat();aid=self.holding['asset_id']
  closed_at=(self.now-timedelta(hours=1)).isoformat()
  later=[dict(self.holding,asset_id=f'later-{index}') for index in range(24)]
  target=later[already_linked] if link_first else self.holding
  linked_assets={holding['asset_id'] for holding in later[:already_linked]}
  if link_first:self.verify=lambda _,uid,holding:dict(self.instrument,asset_id=holding['asset_id'])
  with app.connect() as c:
   payload=json.dumps({'positions_complete':True,'observed':at,'positions':[self.holding]+later})
   c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(payload,self.pid))
   for holding in [self.holding]+later:
    asset=holding['asset_id']
    status='PAUSED' if (link_first and asset==aid) or asset in linked_assets else 'COMPLETED'
    if asset in linked_assets:
     c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',
               (1,self.pid,asset,'LINKED',asset,0,at))
    elif not (link_first and asset==aid):c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',
              (1,self.pid,asset,'POSITION_CLOSED',asset,0,closed_at))
    request=json.dumps({'asset_id':asset,'portfolio_ids':[self.pid],'watch_mode':'exit'})
    c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                 VALUES(1,?,0,?,'manual holding',?,?,'synthetic','{}','{}',?,?,0)""",
              (asset,asset,status,request,at,at))
    if status=='COMPLETED':
     c.executemany("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                      VALUES(1,?,0,?,'manual holding','COMPLETED',?,'synthetic','{}','{}',?,?,0)""",
                   [(f'{asset}-history-{index}',asset,request,at,at) for index in range(extra_history)])

  read_assets={'sessions':[],'attempts':[],'history':[]};connections=[];scan_sql=[]
  writer_steps=0
  def count_rows(cursor,values):
   row=sqlite3.Row(cursor,values)
   if 'kind' in row.keys() and row['kind']=='session':read_assets['sessions'].append((row['asset_id'],cursor.connection.in_transaction))
   if 'kind' in row.keys() and row['kind']=='attempt':read_assets['attempts'].append((row['asset_id'],cursor.connection.in_transaction))
   if 'kind' in row.keys() and row['kind']=='history':read_assets['history'].append(row['watch_id'])
   return row
  def traced_connect():
   connection=app.connect()
   if not connections:
    connection.row_factory=count_rows
    connection.set_trace_callback(scan_sql.append)
    if extra_history:
     def count_writer_steps():
      nonlocal writer_steps
      writer_steps+=int(connection.in_transaction)
      return 0
     connection.set_progress_handler(count_writer_steps,1)
   connections.append(True)
   return connection

  with patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_CAPACITY':'40','ESCAPE_HW_EODHD_REST_ENABLED':'0'}):
   self.assertEqual(service.auto_holdings_tick(traced_connect,verify=self.verify,now=self.now),'LINKED')
  target_aid=target['asset_id']
  expected_sessions=([(aid,False)] if link_first else [])+[(h['asset_id'],True) for h in later[:already_linked]]
  expected_attempts=([h['asset_id'] for h in later] if already_linked==2 else
                     [h['asset_id'] for h in later[:already_linked]]+[target_aid])
  self.assertEqual(read_assets['sessions'],expected_sessions)
  self.assertCountEqual(read_assets['attempts'],[(asset,link_first) for asset in expected_attempts])
  self.assertEqual(read_assets['history'],[])
  history_reads=[sql for sql in scan_sql if "SELECT 'history'" in sql]
  self.assertEqual(len(history_reads),1)
  self.assertEqual(sum(sql.lstrip().upper().startswith(('SELECT','WITH')) for sql in scan_sql),3+int(link_first)+already_linked)
  if extra_history:
   # A full scan of the seeded history would exceed this even at one VM
   # instruction per row. The bound includes the batched retry reads and writes.
   self.assertGreater(writer_steps,0)
   self.assertLess(writer_steps,extra_history*(len(later)-already_linked))
  identity=f'1|{self.pid}|{target_aid}|{closed_at}'
  watch='hw-holding-'+hashlib.sha256(identity.encode()).hexdigest()[:28]
  with app.connect() as c:
   expected={target_aid:watch}
   if link_first:expected[aid]=aid
   expected.update((asset,asset) for asset in linked_assets)
   self.assertEqual(dict(c.execute("SELECT asset_id,watch_id FROM hw_holding_autowatch WHERE status='LINKED'").fetchall()),expected)
   self.assertEqual(c.execute("SELECT count(*) FROM hw_holding_autowatch WHERE status='POSITION_CLOSED'").fetchone()[0],len(later)-int(link_first)-already_linked)

 def test_first_holding_activation_does_not_load_later_history(self):
  self._check_early_activation_history(link_first=False)

 def test_second_holding_activation_after_link_does_not_load_later_history(self):
  self._check_early_activation_history(link_first=True)

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

 def test_concurrent_stop_invalidates_idle_holding_batch(self):
  self._check_concurrent_stop_in_idle_holding_batch()

 def test_concurrent_stop_during_idle_holding_batch_refresh(self):
  self._check_concurrent_stop_in_idle_holding_batch(refresh=True)

 def _check_concurrent_stop_in_idle_holding_batch(self,refresh=False):
  at=self.now.isoformat()
  assets=[f'holding-{index}' for index in range(5)]
  with app.connect() as c:
   payload=json.dumps({'positions_complete':True,'observed':at,'positions':[
    dict(self.holding,asset_id=aid) for aid in assets]})
   c.execute('UPDATE portfolio_snapshots SET payload=? WHERE portfolio_id=?',(payload,self.pid))
   for aid in assets:
    request=json.dumps({'asset_id':aid,'portfolio_ids':[self.pid],'watch_mode':'exit'})
    c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
     VALUES(1,?,0,?,'manual holding','PAUSED',?,'synthetic','{}','{}',?,?,0)""",(aid,aid,request,at,at))
    c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',
              (1,self.pid,aid,'LINKED',aid,0,at))
  execute=app.DatabaseConnection.execute
  committed=False
  with app.connect() as writer:
   def commit_unrelated_during_scan(connection,sql,*args):
    nonlocal committed
    cursor=execute(connection,sql,*args)
    if 'CROSS JOIN hw_holding_autowatch' in sql:
     rows=cursor.fetchall()
     if not committed and {key[1] for key in json.loads(args[0][4])}==set(assets[3:]):
      writer.execute("INSERT INTO users(id,username,active) VALUES(2,'unrelated',1)")
      writer.commit()
      writer.execute('BEGIN IMMEDIATE')
      execute(connection,'PRAGMA busy_timeout=0')
      committed=True
     return rows
    return cursor
   with patch.object(app.DatabaseConnection,'execute',commit_unrelated_during_scan):
    self.assertIsNone(self.tick(verify=lambda *_:self.fail('No activation expected')))
   self.assertTrue(committed)
   writer.rollback()
  stopped=False;invalidated=False
  def stop_after_batch_reads(connection,sql,*args):
   nonlocal stopped,invalidated
   cursor=execute(connection,sql,*args)
   if 'CROSS JOIN hw_holding_autowatch' not in sql or stopped:return cursor
   batch={key[1] for key in json.loads(args[0][4])}
   if batch!=(set(assets[3:]) if not invalidated else {assets[2]}):return cursor
   rows=cursor.fetchall()
   self.assertFalse(connection.in_transaction)
   with app.connect() as other:
    if refresh and not invalidated:
     other.execute("UPDATE users SET username='unrelated-refresh' WHERE id=2")
     invalidated=True
    else:
     other.execute("UPDATE hw_sessions SET status='COMPLETED' WHERE user_id=1 AND watch_id=?",(assets[-1],))
     stopped=True
   return rows
  with patch.object(app.DatabaseConnection,'execute',stop_after_batch_reads):
   self.assertIsNone(self.tick(verify=lambda *_:self.fail('No activation expected')))
  self.assertTrue(stopped)
  with app.connect() as c:
   self.assertEqual([tuple(row) for row in c.execute(
    'SELECT asset_id,status,watch_id,next_attempt FROM hw_holding_autowatch ORDER BY asset_id')],
    [(aid,'LINKED',aid,0) for aid in assets[:-1]]+
    [(assets[-1],'STOPPED',assets[-1],self.now.timestamp()+300)])
   self.assertEqual(dict(c.execute('SELECT watch_id,status FROM hw_sessions').fetchall()),
                    {**dict.fromkeys(assets[:-1],'PAUSED'),assets[-1]:'COMPLETED'})
  # With no intervening commit, the same scan stays read-only.
  with app.connect() as other:
   other.execute('BEGIN IMMEDIATE')
   self.assertIsNone(self.tick(verify=lambda *_:self.fail('No activation expected')))

 def test_repeated_unrelated_commits_allow_next_tenant_activation(self):
  at=self.now.isoformat();aid=self.holding['asset_id']
  with app.connect() as c:
   c.execute("INSERT INTO users(id,username,active) VALUES(2,'second',1)")
   pid2=c.execute("INSERT INTO portfolios(user_id,name,source,updated) VALUES(2,'Second','pluto',?)",(self.now.timestamp(),)).lastrowid
   payload=json.dumps({'positions_complete':True,'observed':at,'positions':[self.holding]})
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(pid2,2,at,payload,at))
   request=json.dumps({'asset_id':aid,'portfolio_ids':[self.pid],'watch_mode':'exit'})
   c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
    VALUES(1,'first-idle',0,?,'manual holding','PAUSED',?,'synthetic','{}','{}',?,?,0)""",(aid,request,at,at))
   c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,aid,'LINKED','first-idle',0,at))
  execute=app.DatabaseConnection.execute;commits=0
  def race(connection,sql,*args):
   nonlocal commits
   cursor=execute(connection,sql,*args)
   if 'FROM json_each(?) k CROSS JOIN hw_holding_autowatch' in sql and args and args[0][0]==1 and not connection.in_transaction:
    rows=cursor.fetchall()
    commits+=1
    self.assertLessEqual(commits,2,'idle tenant retried without bound')
    with app.connect() as other:
     other.execute("UPDATE users SET username=? WHERE id=2",(f'second-{commits}',))
    return rows
   return cursor
  verified=[]
  def verify(_,uid,holding):
   verified.append(uid)
   return self.instrument
  with patch.object(app.DatabaseConnection,'execute',race),patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1','ESCAPE_HW_CAPACITY':'40','ESCAPE_HW_EODHD_REST_ENABLED':'0'}):
   self.assertEqual(service.auto_holdings_tick(app.connect,verify=verify,now=self.now),'LINKED')
  self.assertEqual(commits,2)
  self.assertEqual(verified,[2])

 def test_concurrent_attempt_change_revalidates_idle_link(self):
  at=self.now.isoformat();aid=self.holding['asset_id']
  request=json.dumps({'asset_id':aid,'portfolio_ids':[self.pid],'watch_mode':'exit'})
  with app.connect() as c:
   c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
    VALUES(1,'paused',0,?,'manual holding','PAUSED',?,'synthetic','{}','{}',?,?,0)""",(aid,request,at,at))
   c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,aid,'LINKED','paused',0,at))
  execute=app.DatabaseConnection.execute;raced=False
  def close_attempt_after_read(connection,sql,*args):
   nonlocal raced
   cursor=execute(connection,sql,*args)
   if raced or 'CROSS JOIN hw_holding_autowatch' not in sql:return cursor
   rows=cursor.fetchall()
   with app.connect() as writer:
    writer.execute("UPDATE hw_holding_autowatch SET status='POSITION_CLOSED' WHERE user_id=1 AND portfolio_id=? AND asset_id=?",(self.pid,aid))
   raced=True
   return rows
  with patch.object(app.DatabaseConnection,'execute',close_attempt_after_read):
   self.assertIsNone(self.tick(verify=lambda *_:self.fail('Expected to reuse the paused session')))
  self.assertTrue(raced)
  with app.connect() as c:
   self.assertEqual(tuple(c.execute('SELECT status,watch_id,next_attempt FROM hw_holding_autowatch').fetchone()),
                    ('LINKED','paused',self.now.timestamp()+300))

 def test_concurrent_link_refresh_releases_unused_writer_before_next_tenant(self):
  at=self.now.isoformat();aid=self.holding['asset_id']
  with app.connect() as c:
   c.execute("INSERT INTO users(id,username,active) VALUES(2,'second',1)")
   pid2=c.execute("INSERT INTO portfolios(user_id,name,source,updated) VALUES(2,'Second','pluto',?)",(self.now.timestamp(),)).lastrowid
   data=json.dumps({'positions_complete':True,'observed':at,'positions':[self.holding]})
   c.execute('INSERT INTO portfolio_snapshots VALUES(?,?,?,?,NULL,?)',(pid2,2,at,data,at))
   for uid,pid,wid in ((1,self.pid,'first-watch'),(2,pid2,'second-watch')):
    request=json.dumps({'asset_id':aid,'portfolio_ids':[pid],'watch_mode':'exit'})
    c.execute("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
     VALUES(?,?,0,?,'manual holding','PAUSED',?,'synthetic','{}','{}',?,?,0)""",(uid,wid,aid,request,at,at))
   c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(2,pid2,aid,'LINKED','second-watch',self.now.timestamp()+300,at))
  execute=app.DatabaseConnection.execute;raced=False;checked=False
  def racing(connection,sql,*args):
   nonlocal raced,checked
   if sql=='BEGIN IMMEDIATE' and not raced:
    raced=True
    with app.connect() as other:
     other.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',(1,self.pid,aid,'LINKED','first-watch',self.now.timestamp()+300,at))
   if 'CROSS JOIN hw_holding_autowatch' in sql and args[0][0]==2:
    checked=True
    self.assertFalse(connection.in_transaction)
    other=app.connect()
    try:
     other.execute('PRAGMA busy_timeout=0')
     other.execute('BEGIN IMMEDIATE')
     other.rollback()
    finally:other.close()
   return execute(connection,sql,*args)
  with patch.object(app.DatabaseConnection,'execute',racing),patch.dict(os.environ,{'ESCAPE_HW_HOLDINGS_AUTOWATCH':'1'}):
   self.assertIsNone(service.auto_holdings_tick(app.connect,verify=lambda *_:self.fail('No activation expected'),now=self.now))
  self.assertTrue(raced and checked)
  with app.connect() as c:
   self.assertEqual(c.execute("SELECT count(*) FROM hw_holding_autowatch WHERE status='LINKED'").fetchone()[0],2)

 def test_third_holding_activation_after_link_does_not_load_later_history(self):
  self._check_early_activation_history(link_first=True,already_linked=1)

 def test_fourth_holding_activation_does_not_decode_completed_history_under_writer_lock(self):
  self._check_early_activation_history(link_first=True,already_linked=2,extra_history=200)

 def test_completed_watch_for_current_closed_generation_prevents_reactivation(self):
  at=self.now.isoformat();aid=self.holding['asset_id']
  closed_at=(self.now-timedelta(hours=1)).isoformat()
  identity=f'1|{self.pid}|{aid}|{closed_at}'
  watch='hw-holding-'+hashlib.sha256(identity.encode()).hexdigest()[:28]
  request=json.dumps({'asset_id':aid,'portfolio_ids':[self.pid],'watch_mode':'exit'})
  with app.connect() as c:
   c.execute('INSERT INTO hw_holding_autowatch VALUES(?,?,?,?,?,?,?)',
             (1,self.pid,aid,'POSITION_CLOSED','old-watch',0,closed_at))
   c.executemany("""INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due)
                    VALUES(1,?,0,?,'manual holding','COMPLETED',?,'synthetic','{}','{}',?,?,0)""",
                 [(wid,aid,request,at,at) for wid in ('old-watch',watch)])
  self.assertIsNone(self.tick(verify=lambda *_:self.fail('The current generation is stopped')))
  with app.connect() as c:
   self.assertEqual(tuple(c.execute('SELECT status,watch_id FROM hw_holding_autowatch').fetchone()),('STOPPED',watch))

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
