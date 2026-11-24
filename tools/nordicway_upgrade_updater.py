"""Local, owner-run, pinned private bridge updater repair for #232.
Never install the application, modify the DB, alter approved-sha, or weaken quota.
The existing deploy gate is held closed while replacing exactly one module.
"""
import ast
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

RELEASE_SHA="3cc0c7bec83c529b2c3bb1011e5fcd7011f6ee65"
CURRENT_BUILD="3349c36641b2b8c0edafbe445ba68cba7c7b1bcf"
OLD_UPDATER="5dd0e22270f8d65d955af032a9f3809edfa73a3926b216b928377e13aa7d50eb"
ADAPTER_HASH="65d1d5d5178d3afe5092f7e61ae39cc5aabb29948ed34def395ef8d883161ad3"
NEW_BLOB="c507247a7264c05154155ac5966de35200adf160"
ADDED={"docs/POLYMARKET_INTELLIGENCE.md","polymarket_intelligence.py","scripts/polymarket_discovery.py","scripts/polymarket_smoke.py"}
BRIDGE=Path("/home/nordicr4/.escape_deploy_bridge")
APP=Path("/home/nordicr4/escape_app")
CHECKOUT=Path("/home/nordicr4/escape_deploy/invest")

def digest(data):
    return hashlib.sha256(data).hexdigest()

def git_blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode("ascii")+b"\0"+data).hexdigest()

def read_file(path,limit=200000,private=True):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
                or info.st_size>limit or info.st_mode&0o022 or (private and info.st_mode&0o077)):
            raise ValueError("unsafe_file")
        data=os.read(fd,limit+1)
        if len(data)!=info.st_size:
            raise ValueError("file_changed")
        return data
    finally:
        os.close(fd)

def private_dir(path):
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError("unsafe_bridge")

def manifest(data):
    tree=ast.parse(data.decode("utf-8"))
    entries=[n.value for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=="FILES"]
    if len(entries)!=1:raise ValueError("invalid_manifest")
    result=ast.literal_eval(entries[0])
    if not isinstance(result,tuple) or not result or any(type(x)is not str for x in result) or len(set(result))!=len(result):
        raise ValueError("invalid_manifest")
    return result

def candidate_source(checkout):
    if checkout.is_symlink() or not checkout.is_dir():
        raise ValueError("unsafe_checkout")
    result=subprocess.run(["git","-c","core.hooksPath=/dev/null","-C",str(checkout),"show",RELEASE_SHA+":apply_update.py"],
                          capture_output=True,check=True,timeout=20,env={**os.environ,"GIT_OPTIONAL_LOCKS":"0","GIT_TERMINAL_PROMPT":"0"})
    return result.stdout

def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def write_new(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())

def check_state(bridge,app,new):
    private_dir(bridge)
    if os.path.lexists(bridge/"deployment-incomplete.json") or os.path.lexists(bridge/"deploy-enabled.updater-held"):
        raise ValueError("recovery_or_upgrade_in_progress")
    if read_file(bridge/"approved-sha",64).strip().decode("ascii")!=RELEASE_SHA:
        raise ValueError("approval_changed")
    if read_file(app/"BUILD_COMMIT",128,private=False).strip().decode("ascii")!=CURRENT_BUILD:
        raise ValueError("installed_release_changed")
    if read_file(bridge/"deploy-enabled",4)!=b"1\n":
        raise ValueError("deploy_gate_unexpected")
    old=read_file(bridge/"apply_update.py")
    if digest(old)!=OLD_UPDATER or digest(read_file(bridge/"nordicway_deploy_adapter.py"))!=ADAPTER_HASH:
        raise ValueError("bridge_source_changed")
    if git_blob(new)!=NEW_BLOB:
        raise ValueError("candidate_blob_mismatch")
    compile(new,"apply_update.py","exec")
    prev,nxt=manifest(old),manifest(new)
    if set(nxt)-set(prev)!=ADDED or tuple(x for x in nxt if x not in ADDED)!=prev:
        raise ValueError("unexpected_manifest_delta")
    return old,prev,nxt

def upgrade(bridge,app,new):
    bridge,app=Path(bridge),Path(app)
    old,prev,nxt=check_state(bridge,app,new)
    var=app/"var"
    info=var.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:
        raise ValueError("unsafe_lock_directory")
    fd=os.open(var/"escape-deploy.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077:
            raise ValueError("unsafe_lock")
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old,prev,nxt=check_state(bridge,app,new)
        gate=bridge/"deploy-enabled"
        held=bridge/"deploy-enabled.updater-held"
        # Preserve the exact gate file; a failure leaves it closed, not bypassed.
        os.replace(gate,held);sync_dir(bridge)
        if os.path.lexists(bridge/"deployment-incomplete.json"):
            raise ValueError("concurrent_deploy")
        with tempfile.TemporaryDirectory(prefix=".updater-stage-",dir=bridge) as temp:
            stage=Path(temp)/"apply_update.py"
            write_new(stage,new)
            if read_file(stage)!=new:raise ValueError("stage_mismatch")
            backup_root=bridge/"bridge-backups"
            if not backup_root.exists():backup_root.mkdir(mode=0o700)
            private_dir(backup_root)
            backup=Path(tempfile.mkdtemp(prefix="updater-",dir=backup_root))
            write_new(backup/"apply_update.py",old);sync_dir(backup);sync_dir(backup_root)
            if read_file(backup/"apply_update.py")!=old:raise ValueError("backup_mismatch")
            if (os.path.lexists(gate) or os.path.lexists(bridge/"deployment-incomplete.json")
                    or read_file(bridge/"apply_update.py")!=old):
                raise ValueError("concurrent_change")
            os.replace(stage,bridge/"apply_update.py");sync_dir(bridge)
        if (read_file(bridge/"apply_update.py")!=new or digest(read_file(bridge/"nordicway_deploy_adapter.py"))!=ADAPTER_HASH
                or read_file(bridge/"approved-sha",64).strip().decode("ascii")!=RELEASE_SHA
                or read_file(app/"BUILD_COMMIT",128,private=False).strip().decode("ascii")!=CURRENT_BUILD
                or os.path.lexists(gate) or os.path.lexists(bridge/"deployment-incomplete.json")
                or read_file(held,4)!=b"1\n"):
            raise ValueError("postcheck_failed_gate_held")
        os.replace(held,gate);sync_dir(bridge)
        return {"status":"updater_verified","old_manifest":len(prev),"new_manifest":len(nxt),"release_sha":RELEASE_SHA,"quota_gate":"unchanged","application":"unchanged"}
    finally:
        os.close(fd)

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--sha",required=True);p.add_argument("--apply",action="store_true")
    args=p.parse_args()
    if args.sha!=RELEASE_SHA:p.error("exact pinned SHA required")
    try:
        data=candidate_source(CHECKOUT)
        if args.apply:
            result=upgrade(BRIDGE,APP,data)
        else:
            _,old,new=check_state(BRIDGE,APP,data)
            result={"status":"check_only","old_manifest":len(old),"new_manifest":len(new),"quota_gate":"unchanged"}
        print(json.dumps(result,sort_keys=True))
    except Exception as exc:
        code=str(exc) if isinstance(exc,ValueError) and str(exc).replace("_","").isalpha() else type(exc).__name__
        print(json.dumps({"status":"blocked","reason":code,"deployment":"not_attempted"},sort_keys=True))
        raise SystemExit(1) from None
