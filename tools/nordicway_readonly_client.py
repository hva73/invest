"""Fixed, opt-in read-only SSH transport. No arbitrary commands or live activation."""
import json,os,re,selectors,subprocess,tempfile,time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from nordicway_hostkey import verify

HOST='nordicr4@cp14.nordicway.dk'
SCRIPT=Path(__file__).with_name('nordicway_readonly_diagnostics.py')
STATES={'running','stopped','starting','restarting','timeout','run_once','unknown','unavailable'}
SESSION_STATES={'CREATED','VALIDATING','ACTIVE','DEGRADED','PAUSED','ERROR','COMPLETED','EXPIRED','OTHER'}
REASONS={'database_missing_or_unsafe','database_journal_present','database_header_invalid','database_journal_mode_unsupported','database_read_failed'}

def number(value,maximum=10**18):
 return value if type(value) is int and 0<=value<=maximum else None

def sanitize(raw):
 if not isinstance(raw,dict) or raw.get('scope')!='read_only_aggregate':raise ValueError('invalid_report')
 timestamp=raw.get('observed_at')
 try:
  if not isinstance(timestamp,str) or len(timestamp)>40 or datetime.fromisoformat(timestamp.replace('Z','+00:00')).utcoffset() is None:raise ValueError()
 except (ValueError,OverflowError):raise ValueError('invalid_report') from None
 result={'observed_at':timestamp,'scope':'read_only_aggregate'}
 installation=raw.get('installation');commit=installation.get('declared_commit') if isinstance(installation,dict) else None
 result['installation']={'declared_commit':commit if isinstance(commit,str) and re.fullmatch(r'[0-9a-f]{40}',commit) else None}
 database=raw.get('database');database=database if isinstance(database,dict) else {}
 status=database.get('status');status=status if status in ('ok','unavailable') else 'unavailable'
 d={'status':status}
 if status=='unavailable':
  reason=database.get('reason');d['reason']=reason if reason in REASONS else 'database_read_failed'
 else:
  for label in ('worker','supervisor'):
   item=database.get(label);item=item if isinstance(item,dict) else {};state=item.get('status');age=item.get('age_seconds')
   d[label]={'status':state if state in STATES else 'unknown','age_seconds':age if type(age) in (int,float) and 0<=age<31536000 else None}
  counts=database.get('session_counts');d['session_counts']={k:number(v,1000000) for k,v in counts.items() if k in SESSION_STATES and number(v,1000000) is not None} if isinstance(counts,dict) else None
  d['due_count']=number(database.get('due_count'),1000000)
 result['database']=d
 processes=raw.get('processes');processes=processes if isinstance(processes,dict) else {};counts=processes.get('counts');counts=counts if isinstance(counts,dict) else {}
 result['processes']={'status':'ok' if processes.get('status')=='ok' else 'unavailable','counts':{k:number(counts.get(k),1000) for k in ('supervisor','worker','passenger')}}
 storage=raw.get('storage');storage=storage if isinstance(storage,dict) else {}
 result['storage']={'filesystem_free_bytes':number(storage.get('filesystem_free_bytes')),'account_quota':'unknown'}
 return result

def _run_limited(command,*,input,capture_output,timeout,env):
 """Bound remote stdout and runtime; never surface SSH stderr or arguments."""
 process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env)
 selector=selectors.DefaultSelector();output=bytearray();pending=memoryview(input);deadline=time.monotonic()+timeout
 try:
  os.set_blocking(process.stdin.fileno(),False);os.set_blocking(process.stdout.fileno(),False)
  selector.register(process.stdin,selectors.EVENT_WRITE,'input');selector.register(process.stdout,selectors.EVENT_READ,'output')
  while selector.get_map():
   remaining=deadline-time.monotonic()
   if remaining<=0:raise subprocess.TimeoutExpired('ssh',timeout)
   for key,_ in selector.select(remaining):
    if key.data=='input':
     try:written=os.write(key.fileobj.fileno(),pending[:4096]) if pending else 0
     except BrokenPipeError:written=0;pending=memoryview(b'')
     if written:pending=pending[written:]
     if not pending:selector.unregister(key.fileobj);key.fileobj.close()
    else:
     chunk=os.read(key.fileobj.fileno(),8192)
     if not chunk:selector.unregister(key.fileobj);key.fileobj.close();continue
     output.extend(chunk)
     if len(output)>100000:raise ValueError('oversized_report')
  remaining=deadline-time.monotonic()
  if remaining<=0:raise subprocess.TimeoutExpired('ssh',timeout)
  return SimpleNamespace(returncode=process.wait(timeout=remaining),stdout=bytes(output))
 finally:
  selector.close()
  if process.poll() is None:process.kill();process.wait()
  if process.stdin and not process.stdin.closed:process.stdin.close()
  if process.stdout and not process.stdout.closed:process.stdout.close()

def run(env=None,runner=None):
 env=os.environ if env is None else env
 runner=_run_limited if runner is None else runner
 if env.get('NORDICWAY_READONLY_AUTHORIZED')!='1':return {'status':'blocked','reason':'diagnostics_not_authorized'}
 try:known=verify(env.get('NORDICWAY_KNOWN_HOST',''),env.get('NORDICWAY_VERIFIED_FINGERPRINT',''))
 except ValueError:return {'status':'blocked','reason':'host_key_unverified'}
 if not env.get('SSH_AUTH_SOCK'):return {'status':'blocked','reason':'ssh_agent_unavailable'}
 try:
  script=SCRIPT.read_bytes()
  if not script or len(script)>100000:return {'status':'blocked','reason':'diagnostics_script_invalid'}
  with tempfile.TemporaryDirectory(prefix='escape-hostkey-') as tmp:
   hosts=Path(tmp)/'known_hosts';hosts.write_text(known,encoding='ascii');hosts.chmod(0o600)
   command=['ssh','-F','/dev/null','-T','-p','33','-o','BatchMode=yes','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(hosts),'-o','GlobalKnownHostsFile=/dev/null','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','-o','ConnectTimeout=10',HOST,'python3 -']
   result=runner(command,input=script,capture_output=True,timeout=30,env=env)
  if result.returncode!=0 or len(result.stdout)>100000:return {'status':'failed','reason':'ssh_or_report_failed'}
  return {'status':'ok','report':sanitize(json.loads(result.stdout))}
 except (OSError,subprocess.SubprocessError,ValueError,TypeError,UnicodeError):return {'status':'failed','reason':'ssh_or_report_failed'}

if __name__=='__main__':
 result=run();print(json.dumps(result,sort_keys=True,separators=(',',':')))
 raise SystemExit(0 if result['status']=='ok' else 1)
