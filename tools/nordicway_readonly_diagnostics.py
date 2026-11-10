"""Fixed, redacted Nordicway health checks. No user-provided shell commands."""
import json,os,re,sqlite3,subprocess
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import quote

ROOT=Path('/home/nordicr4/escape_app')
STATES={'CREATED','VALIDATING','ACTIVE','DEGRADED','PAUSED','ERROR','COMPLETED','EXPIRED'}
SERVICE_STATES={'running','stopped','starting','restarting','timeout','run_once'}

def _age(value,now):
 try:
  t=datetime.fromisoformat(value.replace('Z','+00:00'))
  if t.tzinfo is None:return None
  age=(now-t.astimezone(timezone.utc)).total_seconds()
  return round(age,1) if 0<=age<31536000 else None
 except (TypeError,ValueError,AttributeError,OverflowError):return None

def _database(path,now):
 # SQLite's WAL shared memory may require filesystem writes on opening. Skip
 # WAL databases until a separately verified safe snapshot is available.
 if path.parent.is_symlink() or path.is_symlink() or not path.is_file():return {'status':'unavailable','reason':'database_missing_or_unsafe'}
 if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-journal')):return {'status':'unavailable','reason':'database_journal_present'}
 try:
  with path.open('rb') as f:header=f.read(20)
  if len(header)<20 or header[:16]!=b'SQLite format 3\x00':return {'status':'unavailable','reason':'database_header_invalid'}
  if header[18]!=1 or header[19]!=1:return {'status':'unavailable','reason':'database_journal_mode_unsupported'}
 except OSError:return {'status':'unavailable','reason':'database_read_failed'}
 connection=None
 try:
  connection=sqlite3.connect('file:'+quote(str(path),safe='/')+'?mode=ro',uri=True,timeout=1)
  connection.execute('PRAGMA query_only=ON')
  connection.execute('SELECT 1').fetchone()
  result={'status':'ok'}
  for table,label in [('hw_heartbeat','worker'),('hw_supervisor_status','supervisor')]:
   try:
    row=connection.execute('SELECT updated,status FROM '+table+' WHERE id=1').fetchone()
    state=row[1] if row and row[1] in SERVICE_STATES else 'unknown';age=_age(row[0],now) if row else None
    result[label]={'status':state,'age_seconds':age}
   except sqlite3.Error:result[label]={'status':'unavailable','age_seconds':None}
  try:
   counts=Counter()
   for state,count in connection.execute('SELECT status,COUNT(*) FROM hw_sessions WHERE is_test=0 GROUP BY status'):
    counts[state if state in STATES else 'OTHER']+=int(count)
   result['session_counts']=dict(counts)
   result['due_count']=connection.execute("SELECT COUNT(*) FROM hw_sessions WHERE is_test=0 AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND next_due<=? AND lease_until<=?",(now.timestamp(),now.timestamp())).fetchone()[0]
  except sqlite3.Error:result['session_counts']=None;result['due_count']=None
  return result
 except sqlite3.Error:return {'status':'unavailable','reason':'database_read_failed'}
 finally:
  if connection is not None:connection.close()

def _processes():
 try:
  result=subprocess.run(['/bin/ps','-u',str(os.getuid()),'-o','args='],capture_output=True,text=True,timeout=3,check=True)
  found={'supervisor':0,'worker':0,'passenger':0}
  for line in result.stdout.splitlines():
   # Consume process command lines privately; never return paths, arguments or PIDs.
   if re.search(r'(?:^|[/\s])hotwatch_supervisor\.py(?:\s|$)',line):found['supervisor']+=1
   if re.search(r'(?:^|[/\s])hotwatch_service\.py(?:\s|$)',line):found['worker']+=1
   if re.search(r'(?:^|[/\s])passenger_wsgi\.py(?:\s|$)',line):found['passenger']+=1
  return {'status':'ok','counts':found}
 except (OSError,subprocess.SubprocessError):return {'status':'unavailable'}

def inspect(root=ROOT,now=None):
 now=now or datetime.now(timezone.utc);root=Path(root)
 result={'observed_at':now.isoformat(),'scope':'read_only_aggregate','installation':{'declared_commit':None},'database':_database(root/'var/escape.db',now),'processes':_processes(),'storage':{'filesystem_free_bytes':None,'account_quota':'unknown'}}
 try:
  marker=root/'BUILD_COMMIT'
  if not marker.is_symlink() and marker.is_file() and marker.stat().st_size<=128:
   value=marker.read_text(encoding='ascii').strip()
   if re.fullmatch(r'[0-9a-f]{40}',value):result['installation']['declared_commit']=value
 except (OSError,UnicodeError):pass
 try:
  stats=os.statvfs(root);result['storage']['filesystem_free_bytes']=stats.f_bavail*stats.f_frsize
 except OSError:pass
 return result

if __name__=='__main__':
 print(json.dumps(inspect(),sort_keys=True,separators=(',',':')))
