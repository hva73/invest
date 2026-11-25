"""Owner-run installer for a pinned private bridge, not an app deployment.
All four known modules are patched narrowly, with rollback copies and the
existing gate closed throughout. Existing app approval is untouched.
"""
import argparse, ast, fcntl, hashlib, json, os, re, stat, subprocess, tempfile
from pathlib import Path

HOME=Path("/home/nordicr4")
BRIDGE=HOME/".escape_deploy_bridge"
APP=HOME/"escape_app"
CHECKOUT=HOME/"escape_deploy/invest"
RELEASE="3cc0c7bec83c529b2c3bb1011e5fcd7011f6ee65"
INSTALLED="3349c36641b2b8c0edafbe445ba68cba7c7b1bcf"
HASHES={
 "apply_update.py":"0004cd12af2e25b8a9197d1927f18c5b831adeef308167c4dafc9345a54fd04d",
 "nordicway_deploy_adapter.py":"65d1d5d5178d3afe5092f7e61ae39cc5aabb29948ed34def395ef8d883161ad3",
 "nordicway_deploy_runner.py":"5cce220109537cc8602c3fa380d58353f91ba559e3ae9e9156aa2b96f212abe7",
 "nordicway_release_backup.py":"d8e0e93273cc9241b4b28a2cb148115c46d3b8bd3bc4563548858831457a76b",
 "nordicway_deploy_sequence.py":"4dcb28d2768b5c5d3e14f155ba77a76f317d71cf1d79aeb220b79b3efc4c5d05",
}
HELPER="nordicway_phase_backup.py"

def sha(b):return hashlib.sha256(b).hexdigest()
def read(p,private=True):
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        s=os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_nlink!=1 or s.st_size>500000 or s.st_mode&0o022 or (private and s.st_mode&0o077):
            raise ValueError("unsafe_bridge_file")
        data=os.read(fd,500001)
        if len(data)!=s.st_size: raise ValueError("file_changed")
        return data
    finally:os.close(fd)

def sync(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def write(p,data):
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())

def replace(s,old,new):
    if s.count(old)!=1: raise ValueError("unexpected_bridge_source")
    return s.replace(old,new,1)

def replace_method(s,name,new):
    tree=ast.parse(s)
    cls=[x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=="Adapter"]
    if len(cls)!=1:raise ValueError("unexpected_adapter_class")
    nodes=[x for x in cls[0].body if isinstance(x,ast.FunctionDef) and x.name==name]
    if len(nodes)!=1:raise ValueError("unexpected_adapter_method")
    n=nodes[0];lines=s.splitlines(keepends=True)
    return "".join(lines[:n.lineno-1])+new.rstrip()+"\n"+"".join(lines[n.end_lineno:])

def patch(old,helper):
    result={}
    s=old["apply_update.py"].decode()
    s=replace(s,"from pathlib import Path","from pathlib import Path\nimport nordicway_phase_backup as phase")
    s=replace(s,"def apply(source,target,*,verify_backup=None):","def apply(source,target,*,verify_backup=None,compressed_plan=None):")
    s=replace(s,"        with locked_database_snapshot(database, backup/'escape.db'):",'''        snapshot_context = (locked_database_snapshot(database, backup/'escape.db') if compressed_plan is None else
                            phase.snapshot(database, backup/'escape.db.gz', compressed_plan['archive_cap'], compressed_plan['db_bytes']))
        with snapshot_context as compressed_meta:''')
    s=replace(s,"inventory={'format':1,'database_sha256':_hash_file(backup/'escape.db'),'files':{},'keys':{}}",
              "inventory={'format':1,'files':{},'keys':{}}\n            inventory.update({'database_sha256':_hash_file(backup/'escape.db')} if compressed_meta is None else compressed_meta)")
    result["apply_update.py"]=s.encode()
    s=old["nordicway_release_backup.py"].decode()
    s=replace(s,"from urllib.parse import quote","from urllib.parse import quote\nimport nordicway_phase_backup as phase")
    s=replace(s,"    database = _path(backup, 'escape.db')","    if phase.verify_compressed(backup):\n        return True\n    database = _path(backup, 'escape.db')")
    result["nordicway_release_backup.py"]=s.encode()
    s=old["nordicway_deploy_adapter.py"].decode()
    s=replace(s,"import apply_update","import apply_update\nimport nordicway_phase_backup as phase")
    s=replace_method(s,"check_quota",'''    def check_quota(self):
        # An explicit quota reader is a test/injected compatibility path only.
        # Production uses the existing authenticated quota source and 20GB cap.
        if self.quota_reader is not None:
            required=max(self.required_bytes,estimate_required_bytes(self.checkout,self.target))
            result=self.quota_reader(self.target,required)
            if (not isinstance(result,dict) or result.get('required_bytes')!=required
                    or type(result.get('account_free_lower_bytes')) is not int
                    or type(result.get('filesystem_free_bytes')) is not int
                    or min(result['account_free_lower_bytes'],result['filesystem_free_bytes'])<required):
                raise ValueError('quota_unavailable')
            return result
        plan=phase.phase_budget(self.checkout,self.target,self.cpanel_token,
                               nordicway_release_preflight.manifest(self.checkout))
        if phase.available(self.target,self.cpanel_token)<max(self.required_bytes,plan['required_bytes']):
            raise ValueError('insufficient_phase_space')
        self.phase_plan=plan
        return plan''')
    s=replace(s,"    def backup_and_apply(self, release):\n        names = apply_update.FILES",
              "    def backup_and_apply(self, release):\n        self.check_quota()\n        names = apply_update.FILES")
    s=replace(s,"                if self.backup_observer is not None:\n                    self.backup_observer(backup)",
              "                if getattr(self,'phase_plan',None) is not None:\n                    phase.restart_check(self.target,self.cpanel_token,self.phase_plan['restart_reserve'])\n                if self.backup_observer is not None:\n                    self.backup_observer(backup)")
    # Keep the original backup callback, recovery marker and autostart handling.
    s=replace(s,"        with nordicway_autostart.preserve(self.target / 'var'):\n            return apply_update.apply(release['path'], self.target,\n                                      verify_backup=verify_before_replace)",
              """        with nordicway_autostart.preserve(self.target / 'var'):
            try:
                plan=getattr(self,'phase_plan',None)
                if plan is None:
                    return apply_update.apply(release['path'],self.target,verify_backup=verify_before_replace)
                return apply_update.apply(release['path'],self.target,verify_backup=verify_before_replace,compressed_plan=plan)
            except phase.SnapshotFailure as exc:
                raise BackupVerificationFailure('compressed_snapshot_failed') from exc""")
    # Check after staged code replacement, before service start. No such
    # check is needed for normal recovery of an unchanged old app.
    s=replace(s,"    def verify_installed(self, sha):\n        report",
              "    def verify_installed(self, sha):\n        if getattr(self,'phase_plan',None) is not None:\n            phase.restart_check(self.target,self.cpanel_token,self.phase_plan['restart_reserve'])\n        report")
    result["nordicway_deploy_adapter.py"]=s.encode()
    s=old["nordicway_deploy_runner.py"].decode()
    s=replace(s,"import nordicway_release_backup","import nordicway_release_backup\nimport nordicway_phase_backup as phase")
    s=replace(s,'''            digest = hashlib.sha256()
            with (backup / 'escape.db').open('rb') as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != manifest.get('database_sha256'):
                raise ValueError('invalid_backup')''','''            if not phase.verify_compressed(backup):
                digest = hashlib.sha256()
                with (backup / 'escape.db').open('rb') as file:
                    for chunk in iter(lambda: file.read(1024 * 1024), b''):
                        digest.update(chunk)
                if digest.hexdigest() != manifest.get('database_sha256'):
                    raise ValueError('invalid_backup')''')
    s=replace(s,"            if state == 'stopped':\n                with adapter.quiescence():",
              "            if state == 'stopped':\n                if manifest.get('database_encoding')=='gzip':\n                    phase.restart_check(target)\n                with adapter.quiescence():")
    result["nordicway_deploy_runner.py"]=s.encode()
    result[HELPER]=helper
    for name,data in result.items():compile(data,name,"exec")
    return result

def check(bridge,app):
    st=bridge.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:
        raise ValueError("unsafe_bridge")
    for name in ("deployment-incomplete.json","deploy-enabled.updater-held","deploy-enabled.maintenance-held","deploy-enabled.phase-held","approval-ticket.json"):
        if os.path.lexists(bridge/name):raise ValueError("active_recovery_or_approval")
    if read(bridge/"deploy-enabled")!=b"1\n" or read(bridge/"approved-sha").strip()!=RELEASE.encode():
        raise ValueError("release_gate_changed")
    if read(app/"BUILD_COMMIT",False).strip()!=INSTALLED.encode():raise ValueError("installed_release_changed")
    if os.path.lexists(bridge/HELPER):raise ValueError("phase_module_already_exists")
    old={name:read(bridge/name) for name in HASHES}
    if any(sha(old[name])!=digest for name,digest in HASHES.items()):
        raise ValueError("private_bridge_hash_mismatch")
    return old

def install(bridge,app,helper,apply):
    old=check(bridge,app)
    result=patch(old,helper)
    if not apply:
        return {"status":"preflight_pass","modules":sorted(result),"application":"unchanged"}
    lock=app/"var/escape-deploy.lock"
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1 or st.st_mode&0o077:
            raise ValueError("unsafe_deploy_lock")
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=check(bridge,app);result=patch(old,helper)
        gate=bridge/"deploy-enabled";held=bridge/"deploy-enabled.phase-held"
        os.replace(gate,held);sync(bridge)
        if os.path.lexists(bridge/"deployment-incomplete.json"):raise ValueError("concurrent_deployment")
        root=bridge/"bridge-backups"
        root.mkdir(mode=0o700,exist_ok=True)
        st=root.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:
            raise ValueError("unsafe_bridge_backup_directory")
        backup=Path(tempfile.mkdtemp(prefix="phase-",dir=root))
        for name in result:
            if name in old:write(backup/name,old[name])
        sync(backup);sync(root)
        with tempfile.TemporaryDirectory(prefix=".phase-stage-",dir=bridge) as tmp:
            stage=Path(tmp)
            for name,data in result.items():write(stage/name,data)
            for name,data in result.items():
                if os.path.lexists(bridge/"deployment-incomplete.json") or os.path.lexists(gate):
                    raise ValueError("concurrent_deployment")
                if name in old and read(bridge/name)!=old[name]:raise ValueError("bridge_changed")
                os.replace(stage/name,bridge/name)
            sync(bridge)
        if any(read(bridge/name)!=data for name,data in result.items()) or read(held)!=b"1\n" or os.path.lexists(bridge/"deployment-incomplete.json") or read(bridge/"approved-sha").strip()!=RELEASE.encode():
            raise ValueError("phase_install_verification_failed")
        os.replace(held,gate);sync(bridge)
        return {"status":"phase_bridge_installed","modules":sorted(result),"release":RELEASE,"application":"unchanged","approval":"unchanged","backup":backup.name}
    finally:os.close(fd)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--helper",required=True,type=Path)
    p.add_argument("--apply",action="store_true")
    a=p.parse_args()
    try:
        print(json.dumps(install(BRIDGE,APP,a.helper.read_bytes(),a.apply),sort_keys=True),flush=True)
    except Exception as exc:
        print(json.dumps({"status":"blocked","reason":str(exc) if isinstance(exc,ValueError) and re.fullmatch("[a-z_]{1,100}",str(exc)) else type(exc).__name__},sort_keys=True),flush=True)
        raise SystemExit(1) from None
