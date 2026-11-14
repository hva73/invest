"""One-time owner preparation for the exact first release; no deploy is run.

The old SHA-checked token-only runner remains in place.  This helper is not an
SSH entry point.  Running it authorizes only the exact release supplied by the owner.
"""
import argparse
import fcntl
import re
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

INSTALLED = '483a4b55ce4381e42ffb828125c9bcc0807cc8ba'
OLD_BRIDGE = 'c1b6db6ca1ded2f3a81601608bdfa455145798f2'
ROOT = Path('/home/nordicr4')
MODULES = ('nordicway_autostart.py','nordicway_deploy_adapter.py','nordicway_deploy_guard.py',
           'nordicway_deploy_health.py','nordicway_deploy_runner.py','nordicway_deploy_sequence.py',
           'nordicway_quiescence.py','nordicway_readonly_diagnostics.py','nordicway_release_backup.py',
           'nordicway_release_preflight.py','nordicway_release_service.py','nordicway_release_stage.py',
           'nordicway_uapi_probe.py','nordicway_uapi_quota.py','nordicway_writer_check.py')


def private_file(path, limit=1000000):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077
                or st.st_nlink != 1 or st.st_size > limit):
            raise ValueError('unsafe_private_file')
        data = os.read(fd, limit + 1)
        if len(data) > limit: raise ValueError('unsafe_private_file')
        return data
    finally:
        os.close(fd)


def git_file(repo, commit, name):
    r = subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',
                        '-C',str(repo),'show',commit+':'+name],capture_output=True,check=True,
                       timeout=15,env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0'})
    if not r.stdout or len(r.stdout) > 1000000: raise ValueError('source_unavailable')
    return r.stdout


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def atomic(parent, name, data):
    fd, path = tempfile.mkstemp(prefix='.first-release-', dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(path, parent / name)
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.lexists(path): os.unlink(path)


def proc_visibility(proc):
    """Reject known hidepid settings; host visibility still needs live proof."""
    lines = (proc / 'self/mountinfo').read_text().splitlines()
    fd=os.open(proc,os.O_RDONLY|os.O_DIRECTORY)
    try:
        fdinfo=(proc/'self/fdinfo'/str(fd)).read_text()
    finally:
        os.close(fd)
    mount_id=re.search(r'^mnt_id:\s*(\d+)',fdinfo,re.MULTILINE)
    mounts = [line for line in lines if ' - proc ' in line and mount_id
              and line.split()[0] == mount_id.group(1) and line.split()[4] == str(proc)]
    if len(mounts) != 1:
        raise ValueError('process_visibility_unverified')
    options = mounts[0].split(' - ', 1)[0].split()[5:]
    options += mounts[0].split(' - ', 1)[1].split()[2:]
    options = ','.join(options).split(',')
    if any(option.startswith('hidepid=') and option != 'hidepid=0' for option in options):
        raise ValueError('process_visibility_unverified')


def _missing_or_gone(entry):
    try:
        entry.stat()
    except FileNotFoundError:
        return True
    except OSError:
        raise ValueError('process_inspection_unavailable') from None
    return False


def no_guard_process(guard, proc=Path('/proc')):
    # Forced command is python -I -S followed by the exact guard path.
    # Read actual UID from status; proc inode owner may be root for non-dumpable processes.
    if proc == Path('/proc'):
        proc_visibility(proc)
    needle = os.fsencode(str(guard))
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid(): continue
        try:
            status = (entry / 'status').read_text()
            uid = re.search(r'^Uid:\s*(\d+)', status, re.MULTILINE)
            state = re.search(r'^State:\s*([A-Z])', status, re.MULTILINE)
            if not uid or not state: raise ValueError('process_inspection_unavailable')
            if int(uid.group(1)) != os.getuid() or state.group(1) == 'Z': continue
            raw = (entry / 'cmdline').read_bytes()
            if not raw: raise ValueError('process_inspection_unavailable')
        except FileNotFoundError:
            if _missing_or_gone(entry): continue
            raise ValueError('process_inspection_unavailable') from None
        except OSError:
            raise ValueError('process_inspection_unavailable') from None
        if needle in raw.split(b'\0'): return False
    return True


def prepare(root, release, updater_blob, release_updater, requirements, old_modules, *, inspect=no_guard_process):
    if not re.fullmatch(r'[0-9a-f]{40}', release) or not re.fullmatch(r'[0-9a-f]{40}', updater_blob):
        raise ValueError('invalid_release')
    root=Path(root); bridge=root/'.escape_deploy_bridge'; app=root/'escape_app'; var=app/'var'
    for p in (bridge, app, var):
        if p.is_symlink() or not p.is_dir(): raise ValueError('unsafe_path')
    st=bridge.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077: raise ValueError('unsafe_bridge')
    build=app/'BUILD_COMMIT'; req=app/'requirements.txt'
    if build.is_symlink() or build.read_text().strip() != INSTALLED: raise ValueError('installed_version_changed')
    if req.is_symlink() or not req.is_file() or req.read_bytes() != requirements: raise ValueError('requirements_changed')
    if blob(release_updater) != updater_blob: raise ValueError('candidate_mismatch')
    compile(release_updater, 'apply_update.py', 'exec')
    if set(old_modules) != set(MODULES) | {'apply_update.py'}: raise ValueError('source_unavailable')
    for name, expected in old_modules.items():
        if private_file(bridge/name) != expected: raise ValueError('bridge_changed')
    if private_file(bridge/'deploy-enabled',4) != b'1\n': raise ValueError('gate_not_enabled')
    private_file(bridge/'approved-sha', 41)
    # Check visibility before touching gate/claim, then repeat while claimed.
    if not inspect(bridge/'nordicway_deploy_guard.py'): raise ValueError('guard_in_flight')
    lock = os.open(var/'escape-deploy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    marker = bridge/'deployment-incomplete.json'; claimed=False; gate_closed=False
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Claim first, before closing the gate: a request arriving here sees
        # the claim and fails without changing the application. A crash after
        # claim is always visible, even before the gate has been removed.
        try:
            fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError:
            raise ValueError('recovery_required') from None
        claimed=True
        with os.fdopen(fd,'w',encoding='ascii') as out:
            json.dump({'format':1,'sha':release},out,separators=(',',':'));out.write('\n');out.flush();os.fsync(out.fileno())
        directory=os.open(bridge,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
        os.unlink(bridge/'deploy-enabled'); gate_closed=True
        directory=os.open(bridge,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
        if not inspect(bridge/'nordicway_deploy_guard.py'): raise ValueError('guard_in_flight')
        if (app/'BUILD_COMMIT').read_text().strip() != INSTALLED: raise ValueError('installed_version_changed')
        for name, expected in old_modules.items():
            if private_file(bridge/name) != expected: raise ValueError('bridge_changed')
        backup = bridge/'first-release-updater-backup'
        fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as out:
            out.write(old_modules['apply_update.py']);out.flush();os.fsync(out.fileno())
        atomic(bridge,'apply_update.py',release_updater)
        atomic(bridge,'approved-sha',(release+'\n').encode('ascii'))
        if private_file(bridge/'apply_update.py') != release_updater or private_file(bridge/'approved-sha',41).strip() != release.encode():
            raise ValueError('readback_failed')
        # A request arriving while the gate opens sees our claim and fails
        # safely. If reopening fails or the process dies, the claim remains.
        atomic(bridge,'deploy-enabled',b'1\n');gate_closed=False
        if private_file(bridge/'deploy-enabled',4) != b'1\n': raise ValueError('gate_readback_failed')
        os.unlink(marker);claimed=False
        directory=os.open(bridge,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
        return {'status':'prepared','release':release}
    finally:
        # Before completion, an owned claim remains even if the gate was
        # reopened. Once the claim is removed, the updater, SHA and gate have
        # all been verified; directory-fsync failure is reported separately.
        os.close(lock)


def failure_status(root, reason):
    bridge=Path(root)/'.escape_deploy_bridge'
    return {'status':'stopped','reason':reason,
            'gate_present':os.path.lexists(bridge/'deploy-enabled'),
            'recovery_present':os.path.lexists(bridge/'deployment-incomplete.json')}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--release', required=True)
    parser.add_argument('--updater-blob', required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}',args.release) or not re.fullmatch(r'[0-9a-f]{40}',args.updater_blob):
        raise ValueError('invalid_release')
    repo=ROOT/'escape_deploy/invest'
    if repo.is_symlink() or not repo.is_dir(): raise ValueError('checkout_unavailable')
    modules={name:git_file(repo,OLD_BRIDGE, 'apply_update.py' if name=='apply_update.py' else 'tools/'+name)
             for name in (*MODULES,'apply_update.py')}
    result=prepare(ROOT,args.release,args.updater_blob,git_file(repo,args.release,'apply_update.py'),git_file(repo,args.release,'requirements.txt'),modules)
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        # Avoid printing paths, data, subprocess output or secrets.
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else 'preparation_failed'
        print(json.dumps(failure_status(ROOT,reason),sort_keys=True))
        raise SystemExit(1) from None
