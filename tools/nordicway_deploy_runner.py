"""Restricted server-side entry point for a separately approved release.

Not installed by this module. An interrupted or uncertain run leaves a private
marker and requires operator investigation; it never restores an old database.
"""
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

import nordicway_deploy_adapter
import nordicway_deploy_sequence

HOME = Path('/home/nordicr4')
BRIDGE = HOME / '.escape_deploy_bridge'
CHECKOUT = HOME / 'escape_deploy' / 'invest'
TARGET = HOME / 'escape_app'
REPOSITORY = 'https://github.com/hva73/invest.git'


def prepare_checkout(checkout, sha, runner=subprocess.run):
    """Select the approved commit in the separate clean deployment checkout."""
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid_request')
    checkout = Path(checkout)
    if checkout.is_symlink() or not checkout.is_dir():
        raise ValueError('checkout_unavailable')
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'}
    prefix = ['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
              '-C', str(checkout)]
    def call(args, timeout=30):
        return runner(prefix + args, capture_output=True, timeout=timeout, check=False, env=env)
    status = call(['status', '--porcelain=v1', '--untracked-files=all'])
    if status.returncode != 0 or status.stdout:
        raise ValueError('checkout_not_clean')
    if call(['cat-file', '-e', sha + '^{commit}']).returncode != 0:
        fetched = call(['fetch', '--no-tags', '--no-recurse-submodules', REPOSITORY, sha], timeout=120)
        if fetched.returncode != 0 or call(['cat-file', '-e', sha + '^{commit}']).returncode != 0:
            raise ValueError('checkout_unavailable')
    if call(['checkout', '--detach', sha]).returncode != 0:
        raise ValueError('checkout_unavailable')
    head = call(['rev-parse', '--verify', 'HEAD^{commit}'])
    if head.returncode != 0 or head.stdout.strip() != sha.encode('ascii'):
        raise ValueError('checkout_unavailable')


def _private_directory(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe_bridge')
    return path


def _approved_sha(bridge):
    # Only a local owner-controlled file can authorize a SHA; the SSH command
    # itself does not create or change authorization.
    fd = os.open(bridge / 'approved-sha', os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 41):
            raise ValueError('invalid_approval')
        value = os.read(fd, 42).decode('ascii').strip()
        if not re.fullmatch(r'[0-9a-f]{40}', value):
            raise ValueError('invalid_approval')
        return value
    finally:
        os.close(fd)


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _claim(bridge, sha):
    marker = bridge / 'deployment-incomplete.json'
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='ascii') as out:
        json.dump({'format': 1, 'sha': sha}, out, separators=(',', ':'))
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    _sync_dir(bridge)
    return marker


def _record_backup(bridge, marker, target, sha, backup):
    backup = Path(backup)
    parent = Path(target).parent / '.escape_backups'
    if (parent.is_symlink() or backup.is_symlink() or not backup.is_dir()
            or backup.parent.resolve() != parent.resolve()
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', backup.name)):
        raise ValueError('invalid_backup')
    # The verified backup is recorded before the first code file is replaced.
    fd, name = tempfile.mkstemp(prefix='.recovery-', dir=bridge)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as out:
            json.dump({'format': 1, 'sha': sha, 'backup': backup.name}, out,
                      separators=(',', ':'))
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, marker)
        _sync_dir(bridge)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run(sha, token, *, bridge=BRIDGE, checkout=CHECKOUT, target=TARGET,
        adapter_factory=nordicway_deploy_adapter.Adapter,
        deploy=nordicway_deploy_sequence.deploy, prepare=prepare_checkout):
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid_request')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        raise ValueError('invalid_request')
    bridge = _private_directory(bridge)
    if _approved_sha(bridge) != sha:
        raise ValueError('unapproved_release')
    # Claim before touching service or database. O_EXCL also prevents concurrent
    # runs and blocks retries after a process crash until investigated.
    marker = _claim(bridge, sha)
    result = None
    try:
        prepare(checkout, sha)
        adapter = adapter_factory(checkout, target, sha, 1, None, None, cpanel_token=token)
        adapter.backup_observer = lambda backup: _record_backup(bridge, marker, target, sha, backup)
        result = deploy(adapter, sha)
        if result.status == 'ok' and result.stage == 'complete':
            marker.unlink()
            _sync_dir(bridge)
        # Paths, tokens and exception details are deliberately not returned.
        return {'operation': 'deploy', 'status': result.status, 'stage': result.stage,
                'service_restored': result.service_restored,
                'recovery_required': marker.exists()}
    except Exception:
        # Uncertainty is not proof that no production change occurred.
        return {'operation': 'deploy', 'status': 'failed', 'stage': 'runner',
                'service_restored': False, 'recovery_required': True}


def run_request(sha, stream):
    raw = stream.read(4097)
    if not isinstance(raw, bytes) or len(raw) > 4096:
        raise ValueError('invalid_request')
    try:
        request = json.loads(raw)
    except (UnicodeError, ValueError):
        raise ValueError('invalid_request') from None
    if not isinstance(request, dict) or set(request) != {'cpanel_token'}:
        raise ValueError('invalid_request')
    return run(sha, request['cpanel_token'])
