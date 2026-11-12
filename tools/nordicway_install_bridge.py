"""Install only the pinned restricted deployment *code* in the private bridge.

This deliberately never enables deploy, changes authorized_keys, restarts
Passenger, modifies the application, or touches its SQLite database.
Run locally from authenticated cPanel AFTER reviewing the pinned commit.
"""
import argparse
import hashlib
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

HOME = Path('/home/nordicr4')
BRIDGE = HOME / '.escape_deploy_bridge'
CHECKOUT = HOME / 'escape_deploy/invest'
OLD_GUARD_SHA256 = '0f60040c9ed3c8fbf9f3f5d29b74ab1f875b8b3373adf106810f7953ad6ea20d'
MODULES = (
    'tools/nordicway_autostart.py',
    'tools/nordicway_deploy_adapter.py',
    'tools/nordicway_deploy_guard.py',
    'tools/nordicway_deploy_health.py',
    'tools/nordicway_deploy_runner.py',
    'tools/nordicway_owner_approval.py',
    'tools/nordicway_app_release.py',
    'tools/nordicway_app_release_entry.py',
    'tools/nordicway_deploy_sequence.py',
    'tools/nordicway_quiescence.py',
    'tools/nordicway_readonly_diagnostics.py',
    'tools/nordicway_release_backup.py',
    'tools/nordicway_release_preflight.py',
    'tools/nordicway_release_service.py',
    'tools/nordicway_release_stage.py',
    'tools/nordicway_uapi_probe.py',
    'tools/nordicway_uapi_quota.py',
    'tools/nordicway_writer_check.py',
    'apply_update.py',
)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _private_dir(path):
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe_bridge_directory')


def _git(checkout, *args):
    result = subprocess.run(
        ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
         '-C', str(checkout), *args],
        capture_output=True, timeout=15, check=False,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'})
    if result.returncode:
        raise ValueError('source_unavailable')
    return result.stdout


def _sources(checkout, sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid_sha')
    checkout = Path(checkout)
    if checkout.is_symlink() or not checkout.is_dir():
        raise ValueError('unsafe_checkout')
    if _git(checkout, 'cat-file', '-t', sha).strip() != b'commit':
        raise ValueError('invalid_commit')
    files = {}
    for name in MODULES:
        data = _git(checkout, 'show', sha + ':' + name)
        if len(data) > 1_000_000 or not data:
            raise ValueError('invalid_source')
        compile(data, name, 'exec')
        destination = Path(name).name
        if destination in files:
            raise ValueError('duplicate_destination')
        files[destination] = data
    return files


def _safe_file(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        raise ValueError('unsafe_bridge_file')
    return True


def install(checkout, bridge, sha):
    """Stage all module bytes before touching any installed module.

    Guard replacement occurs last. Old files remain in a private backup
    directory for manual recovery. Deploy is *not* enabled by this action.
    """
    files = _sources(checkout, sha)
    bridge = Path(bridge)
    _private_dir(bridge)
    if os.path.lexists(bridge / 'deploy-enabled'):
        raise ValueError('deployment_must_be_disabled')
    guard = bridge / 'nordicway_deploy_guard.py'
    if not _safe_file(guard):
        raise ValueError('guard_missing')
    current_guard_hash = _digest(guard.read_bytes())
    next_guard_hash = _digest(files['nordicway_deploy_guard.py'])
    if current_guard_hash not in (OLD_GUARD_SHA256, next_guard_hash):
        raise ValueError('unexpected_guard_version')

    for name in files:
        _safe_file(bridge / name)

    with tempfile.TemporaryDirectory(prefix='.bridge-stage-', dir=bridge) as staged:
        staging = Path(staged)
        for name, data in files.items():
            fd = os.open(staging / name,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            if _digest((staging / name).read_bytes()) != _digest(data):
                raise ValueError('stage_corrupt')

        # We keep a copy of every previous module for manual recovery, including
        # the guard; nothing belonging to the application is moved or deleted.
        backups = bridge / 'bridge-backups'
        if backups.exists():
            _private_dir(backups)
        else:
            backups.mkdir(mode=0o700)
        backup_dir = Path(tempfile.mkdtemp(prefix='bridge-', dir=backups))
        backup_dir.chmod(0o700)
        for name in files:
            current = bridge / name
            if _safe_file(current):
                fd = os.open(backup_dir / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as backup:
                    backup.write(current.read_bytes())
                    backup.flush()
                    os.fsync(backup.fileno())

        if os.path.lexists(bridge / 'deploy-enabled'):
            raise ValueError('deployment_must_be_disabled')
        for name in [n for n in files if n != 'nordicway_deploy_guard.py'] + ['nordicway_deploy_guard.py']:
            os.replace(staging / name, bridge / name)
        directory = os.open(bridge, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    if os.path.lexists(bridge / 'deploy-enabled'):
        raise ValueError('deployment_must_be_disabled')
    if any(_digest((bridge / name).read_bytes()) != _digest(data) for name, data in files.items()):
        raise ValueError('installed_content_mismatch')
    return {'status': 'installed_disabled', 'file_count': len(files),
            'source_commit': sha}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sha', required=True)
    args = parser.parse_args()
    result = install(CHECKOUT, BRIDGE, args.sha)
    print('Bridge:', result['status'])
    print('Verified code modules:', result['file_count'])
    print('Source commit:', result['source_commit'])
    print('Full deployment remains disabled.')


if __name__ == '__main__':
    main()
