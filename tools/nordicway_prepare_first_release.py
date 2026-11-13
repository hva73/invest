"""One-time owner preparation for the exact first release; no deploy is run.

The old SHA-checked token-only runner remains in place.  This helper is not an
SSH entry point.  Running it constitutes owner authorization of RELEASE.
"""
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

RELEASE = '819a444668c5aff4a992fcee73666837264869f4'
INSTALLED = '483a4b55ce4381e42ffb828125c9bcc0807cc8ba'
OLD_BRIDGE = 'c1b6db6ca1ded2f3a81601608bdfa455145798f2'
UPDATER_BLOB = '8d64d275d14be29d12f2d8630c3435dd164afd0c'
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


def no_guard_process(guard, proc=Path('/proc')):
    # Forced command is python -I -S followed by the exact guard path.
    # Inspect all visible processes owned by the account; uncertainty blocks.
    needle = os.fsencode(str(guard))
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid(): continue
        try:
            if entry.stat().st_uid != os.getuid(): continue
            argv = (entry / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError('process_inspection_unavailable') from None
        if needle in argv: return False
    return True


def prepare(root, release_updater, requirements, old_modules, *, inspect=no_guard_process):
    root=Path(root); bridge=root/'.escape_deploy_bridge'; app=root/'escape_app'; var=app/'var'
    for p in (bridge, app, var):
        if p.is_symlink() or not p.is_dir(): raise ValueError('unsafe_path')
    st=bridge.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077: raise ValueError('unsafe_bridge')
    build=app/'BUILD_COMMIT'; req=app/'requirements.txt'
    if build.is_symlink() or build.read_text().strip() != INSTALLED: raise ValueError('installed_version_changed')
    if req.is_symlink() or not req.is_file() or req.read_bytes() != requirements: raise ValueError('requirements_changed')
    if blob(release_updater) != UPDATER_BLOB: raise ValueError('candidate_mismatch')
    compile(release_updater, 'apply_update.py', 'exec')
    if set(old_modules) != set(MODULES) | {'apply_update.py'}: raise ValueError('source_unavailable')
    for name, expected in old_modules.items():
        if private_file(bridge/name) != expected: raise ValueError('bridge_changed')
    if private_file(bridge/'deploy-enabled',4) != b'1\n': raise ValueError('gate_not_enabled')
    private_file(bridge/'approved-sha', 41)
    lock = os.open(var/'escape-deploy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    marker = bridge/'deployment-incomplete.json'; claimed=False; gate_closed=False
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Close the gate before claiming. A pre-existing claim blocks us; our
        # own exclusive marker blocks an already admitted runner from claiming.
        if os.path.lexists(marker): raise ValueError('recovery_required')
        os.unlink(bridge/'deploy-enabled'); gate_closed=True
        fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        claimed=True
        with os.fdopen(fd,'w',encoding='ascii') as out:
            json.dump({'format':1,'sha':RELEASE},out,separators=(',',':'));out.write('\n');out.flush();os.fsync(out.fileno())
        if not inspect(bridge/'nordicway_deploy_guard.py'): raise ValueError('guard_in_flight')
        if (app/'BUILD_COMMIT').read_text().strip() != INSTALLED: raise ValueError('installed_version_changed')
        for name, expected in old_modules.items():
            if private_file(bridge/name) != expected: raise ValueError('bridge_changed')
        backup = bridge/'first-release-updater-backup'
        fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as out:
            out.write(old_modules['apply_update.py']);out.flush();os.fsync(out.fileno())
        atomic(bridge,'apply_update.py',release_updater)
        atomic(bridge,'approved-sha',(RELEASE+'\n').encode('ascii'))
        if private_file(bridge/'apply_update.py') != release_updater or private_file(bridge/'approved-sha',41).strip() != RELEASE.encode():
            raise ValueError('readback_failed')
        os.unlink(marker);claimed=False
        atomic(bridge,'deploy-enabled',b'1\n');gate_closed=False
        return {'status':'prepared','release':RELEASE}
    finally:
        # After any uncertainty the gate remains closed and an owned claim is
        # deliberately left for investigation; never delete an existing claim.
        os.close(lock)


def main():
    repo=ROOT/'escape_deploy/invest'
    if repo.is_symlink() or not repo.is_dir(): raise ValueError('checkout_unavailable')
    modules={name:git_file(repo,OLD_BRIDGE, 'apply_update.py' if name=='apply_update.py' else 'tools/'+name)
             for name in (*MODULES,'apply_update.py')}
    result=prepare(ROOT,git_file(repo,RELEASE,'apply_update.py'),git_file(repo,RELEASE,'requirements.txt'),modules)
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        # Avoid printing paths, data, subprocess output or secrets.
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else 'preparation_failed'
        raise SystemExit('First release preparation stopped: '+reason) from None
