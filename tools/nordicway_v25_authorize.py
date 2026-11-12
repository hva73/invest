#!/usr/bin/env python3
"""Authorize the reviewed v2.5 SHA on the existing private deploy bridge."""
import fcntl
import os
import stat
import subprocess
import tempfile
from pathlib import Path

CANDIDATE = '483a4b55ce4381e42ffb828125c9bcc0807cc8ba'
INSTALLED = '39a609ebdc315e818e0ef991764e8defb301f9e2'
BRIDGE_SHA = 'c1b6db6ca1ded2f3a81601608bdfa455145798f2'
MODULES = ('nordicway_autostart.py', 'nordicway_deploy_adapter.py',
           'nordicway_deploy_guard.py', 'nordicway_deploy_health.py',
           'nordicway_deploy_runner.py', 'nordicway_deploy_sequence.py',
           'nordicway_quiescence.py', 'nordicway_readonly_diagnostics.py',
           'nordicway_release_backup.py', 'nordicway_release_preflight.py',
           'nordicway_release_service.py', 'nordicway_release_stage.py',
           'nordicway_uapi_probe.py', 'nordicway_uapi_quota.py',
           'nordicway_writer_check.py', 'apply_update.py')


def read_regular(path, private=False, limit=1_000_000):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_size > limit
                or (private and info.st_mode & 0o077)):
            raise ValueError('unsafe_file')
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise ValueError('unsafe_file')
        return data
    finally:
        os.close(fd)


def authorize(home, git_blob):
    home = Path(home)
    bridge, app = home / '.escape_deploy_bridge', home / 'escape_app'
    info = bridge.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe_bridge')
    lock_path = app / 'var/escape-deploy.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('unsafe_lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.path.lexists(bridge / 'deployment-incomplete.json'):
            raise ValueError('recovery_required')
        if read_regular(app / 'BUILD_COMMIT', limit=128).strip() != INSTALLED.encode():
            raise ValueError('installed_version_changed')
        if read_regular(bridge / 'deploy-enabled', private=True, limit=4) != b'1\n':
            raise ValueError('deploy_disabled_or_unsafe')
        for name in MODULES:
            source = name if name == 'apply_update.py' else 'tools/' + name
            if read_regular(bridge / name, private=True) != git_blob(BRIDGE_SHA, source):
                raise ValueError('bridge_mismatch')
        # A pre-existing approval, if any, must be a private regular file.
        target = bridge / 'approved-sha'
        if os.path.lexists(target):
            read_regular(target, private=True, limit=128)
        if os.path.lexists(bridge / 'deployment-incomplete.json'):
            raise ValueError('recovery_required')
        tmp_fd, tmp_name = tempfile.mkstemp(prefix='.approval-', dir=bridge)
        try:
            with os.fdopen(tmp_fd, 'wb') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write((CANDIDATE + '\n').encode('ascii'))
                output.flush()
                os.fsync(output.fileno())
            os.replace(tmp_name, target)
            directory_fd = os.open(bridge, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        if read_regular(target, private=True, limit=128).strip() != CANDIDATE.encode():
            raise ValueError('approval_unverified')
        if os.path.lexists(bridge / 'deployment-incomplete.json'):
            raise ValueError('recovery_required')
        return CANDIDATE
    finally:
        os.close(fd)


def main():
    home = Path('/home/nordicr4')
    repo = home / 'escape_deploy/invest'
    env = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'}
    def blob(sha, path):
        return subprocess.check_output(['/usr/bin/git', '-C', str(repo), 'show', sha + ':' + path],
                                       env=env, stderr=subprocess.DEVNULL, timeout=20)
    subprocess.run(['/usr/bin/git', '-C', str(repo), 'cat-file', '-e', CANDIDATE + '^{commit}'],
                   env=env, stderr=subprocess.DEVNULL, timeout=20, check=True)
    print('Godkendt release:', authorize(home, blob))
    print('Bridge og app verificeret; klar til ét kontrolleret forsøg')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        codes = {'unsafe_bridge', 'unsafe_file', 'unsafe_lock', 'recovery_required',
                 'installed_version_changed', 'deploy_disabled_or_unsafe',
                 'bridge_mismatch', 'approval_unverified'}
        reason = str(exc) if isinstance(exc, ValueError) and str(exc) in codes else type(exc).__name__
        raise SystemExit('STOP: ' + reason) from None
