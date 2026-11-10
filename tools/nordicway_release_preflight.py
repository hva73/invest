"""Read-only release preparation; it never installs, migrates or restarts."""
import ast,hashlib,json,os,re,subprocess
from pathlib import Path

CHECKOUT=Path('/home/nordicr4/escape_deploy/invest')
TARGET=Path('/home/nordicr4/escape_app')
SAFE_PART=re.compile(r'[A-Za-z0-9_.-]+\Z')

def _git(checkout,*args):
 env={**os.environ,'GIT_OPTIONAL_LOCKS':'0','GIT_TERMINAL_PROMPT':'0'}
 result=subprocess.run(['git','-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',str(checkout),*args],capture_output=True,text=True,timeout=10,check=False,env=env)
 if result.returncode!=0:raise ValueError('checkout_unavailable')
 return result.stdout.strip()

def _git_blob(checkout,sha,name):
 env={**os.environ,'GIT_OPTIONAL_LOCKS':'0','GIT_TERMINAL_PROMPT':'0'}
 result=subprocess.run(['git','-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',str(checkout),'show',sha+':'+name],capture_output=True,timeout=10,check=False,env=env)
 if result.returncode!=0:raise ValueError('manifest_untracked_file')
 return result.stdout

def manifest(checkout):
 source=checkout/'apply_update.py'
 if source.is_symlink() or not source.is_file():raise ValueError('manifest_unavailable')
 tree=ast.parse(source.read_text(encoding='utf-8'))
 nodes=[node.value for node in tree.body if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='FILES']
 if len(nodes)!=1:raise ValueError('manifest_invalid')
 try:files=ast.literal_eval(nodes[0])
 except (ValueError,TypeError,SyntaxError):raise ValueError('manifest_invalid') from None
 if not isinstance(files,tuple) or not files or len(files)>500 or len(files)!=len(set(files)):raise ValueError('manifest_invalid')
 for name in files:
  if not isinstance(name,str) or len(name)>240:raise ValueError('manifest_invalid')
  path=Path(name)
  if path.is_absolute() or not path.parts or any(part in ('.','..','.git','var') or not SAFE_PART.fullmatch(part) for part in path.parts):raise ValueError('manifest_invalid')
 return files

def inspect(checkout,target,sha):
 if not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{40}',sha):return {'status':'blocked','reason':'invalid_sha'}
 checkout=Path(checkout);target=Path(target)
 try:
  if checkout.is_symlink() or target.is_symlink() or not checkout.is_dir() or not target.is_dir():raise ValueError('unsafe_paths')
  if _git(checkout,'rev-parse','--verify','HEAD^{commit}')!=sha:raise ValueError('checkout_sha_mismatch')
  if _git(checkout,'status','--porcelain=v1','--untracked-files=all'):raise ValueError('checkout_not_clean')
  names=manifest(checkout);root=checkout.resolve();target_root=target.resolve();digest=hashlib.sha256();total=0;installed_matches=0
  for name in names:
   relative=Path(name);node=checkout
   for part in relative.parts:
    node=node/part
    if node.is_symlink():raise ValueError('manifest_symlink')
   if not node.is_file() or not node.resolve().is_relative_to(root):raise ValueError('manifest_missing_file')
   if node.stat().st_size>50_000_000 or total+node.stat().st_size>250_000_000:raise ValueError('manifest_too_large')
   data=node.read_bytes()
   if data!=_git_blob(checkout,sha,name):raise ValueError('manifest_file_mismatch')
   total+=len(data);digest.update(name.encode()+b'\0'+hashlib.sha256(data).digest())
   installed=target
   unsafe=False
   for part in relative.parts:
    installed=installed/part
    if installed.is_symlink():unsafe=True;break
   if not unsafe and installed.is_file() and installed.resolve().is_relative_to(target_root) and installed.stat().st_size<=50_000_000:
    expected=(sha+'\n').encode('ascii') if name=='BUILD_COMMIT' else data
    if installed.read_bytes()==expected:installed_matches+=1
  var=target/'var';db=var/'escape.db'
  if var.is_symlink() or db.is_symlink() or not db.is_file() or not db.resolve().is_relative_to(target.resolve()):raise ValueError('database_unavailable')
  fs=os.statvfs(target);free=fs.f_bavail*fs.f_frsize
  return {'status':'blocked','requested_sha':sha,'manifest_files':len(names),'manifest_sha256':digest.hexdigest(),'installed_files_matching':installed_matches,'installed_files_checked':len(names),'runtime_version':'unknown','source_bytes':total,'database_bytes':db.stat().st_size,'filesystem_free_bytes':free,'account_quota':'unknown','blockers':['release_gate_not_implemented','account_quota_unknown','passenger_quiesce_unverified','restore_and_restart_unverified']}
 except (OSError,ValueError,TypeError,SyntaxError,subprocess.SubprocessError) as error:
  reason=str(error) if isinstance(error,ValueError) and re.fullmatch(r'[a-z_]+',str(error)) else 'preflight_failed'
  return {'status':'blocked','reason':reason}

if __name__=='__main__':
 # The approved SHA is an opaque value, not a shell fragment. This script is
 # deliberately read-only and cannot authorize or perform a release.
 print(json.dumps(inspect(CHECKOUT,TARGET,os.environ.get('ESCAPE_RELEASE_SHA','')),sort_keys=True,separators=(',',':')))
