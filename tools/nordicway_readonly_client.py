"""Fixed, opt-in read-only SSH transport. No arbitrary commands or live activation."""
import json,os,re,selectors,subprocess,tempfile,time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from nordicway_hostkey import verify

HOST='nordicr4@cp14.nordicway.dk'
PROTOCOL='escape-readonly-v1'
STATES={'running','stopped','starting','restarting','timeout','run_once','unknown','unavailable'}
SESSION_STATES={'CREATED','VALIDATING','ACTIVE','DEGRADED','PAUSED','ERROR','COMPLETED','EXPIRED','OTHER'}
REASONS={'database_missing_or_unsafe','database_journal_present','database_header_invalid','database_journal_mode_unsupported','database_read_failed'}
PREFLIGHT_REASONS={'invalid_sha','unsafe_paths','checkout_unavailable','checkout_sha_mismatch','checkout_not_clean','manifest_unavailable','manifest_invalid','manifest_symlink','manifest_missing_file','manifest_untracked_file','manifest_file_mismatch','manifest_too_large','database_unavailable','preflight_failed'}
PREFLIGHT_BLOCKERS={'owner_approval_not_confirmed','account_quota_unknown','passenger_quiesce_unverified','restore_and_restart_unverified'}

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

def sanitize_preflight(raw,sha):
 if not isinstance(raw,dict) or raw.get('status')!='blocked':raise ValueError('invalid_report')
 if 'reason' in raw:
  reason=raw['reason']
  return {'status':'blocked','reason':reason if reason in PREFLIGHT_REASONS else 'preflight_failed'}
 if raw.get('requested_sha')!=sha or not isinstance(raw.get('manifest_sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',raw['manifest_sha256']):raise ValueError('invalid_report')
 blockers=raw.get('blockers')
 if not isinstance(blockers,list) or set(blockers)!=PREFLIGHT_BLOCKERS:raise ValueError('invalid_report')
 fields=('manifest_files','source_bytes','database_bytes','filesystem_free_bytes')
 counts={field:number(raw.get(field)) for field in fields}
 if any(value is None for value in counts.values()):raise ValueError('invalid_report')
 return {'status':'blocked','requested_sha':sha,'manifest_sha256':raw['manifest_sha256'],**counts,'account_quota':'unknown','blockers':sorted(PREFLIGHT_BLOCKERS)}

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
 if env.get('NORDICWAY_RESTRICTED_KEY_VERIFIED')!='1':return {'status':'blocked','reason':'server_key_restrictions_unverified'}
 try:known=verify(env.get('NORDICWAY_KNOWN_HOST',''),env.get('NORDICWAY_VERIFIED_FINGERPRINT',''))
 except ValueError:return {'status':'blocked','reason':'host_key_unverified'}
 if not env.get('SSH_AUTH_SOCK'):return {'status':'blocked','reason':'ssh_agent_unavailable'}
 operation=env.get('NORDICWAY_OPERATION','diagnostics');sha=env.get('NORDICWAY_RELEASE_SHA','')
 if operation not in ('diagnostics','release_preflight') or not isinstance(sha,str) or (operation=='release_preflight' and not re.fullmatch(r'[0-9a-f]{40}',sha)) or (operation=='diagnostics' and sha):return {'status':'blocked','reason':'invalid_operation'}
 try:
  remote_command=PROTOCOL+' diagnostics' if operation=='diagnostics' else PROTOCOL+' preflight '+sha
  with tempfile.TemporaryDirectory(prefix='escape-hostkey-') as tmp:
   hosts=Path(tmp)/'known_hosts';hosts.write_text(known,encoding='ascii');hosts.chmod(0o600)
   command=['ssh','-F','/dev/null','-T','-p','33','-o','BatchMode=yes','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(hosts),'-o','GlobalKnownHostsFile=/dev/null','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','-o','ConnectTimeout=10',HOST,remote_command]
   result=runner(command,input=b'',capture_output=True,timeout=30,env=env)
  if result.returncode!=0 or len(result.stdout)>100000:return {'status':'failed','reason':'ssh_or_report_failed'}
  parsed=json.loads(result.stdout)
  if not isinstance(parsed,dict) or parsed.get('protocol')!=PROTOCOL or parsed.get('operation')!=operation:raise ValueError('invalid_report')
  report=parsed.get('report')
  return {'status':'ok','report':sanitize(report) if operation=='diagnostics' else sanitize_preflight(report,sha)}
 except (OSError,subprocess.SubprocessError,ValueError,TypeError,UnicodeError):return {'status':'failed','reason':'ssh_or_report_failed'}

if __name__=='__main__':
 result=run();print(json.dumps(result,sort_keys=True,separators=(',',':')))
 raise SystemExit(0 if result['status']=='ok' else 1)
