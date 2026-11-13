"""Restricted server-side entry point for a separately approved release.

Not installed by this module. An interrupted or uncertain run leaves a private
marker and requires operator investigation; it never restores an old database.
"""
import json
import hashlib
import os
import re
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import nordicway_deploy_adapter
import nordicway_owner_approval
import nordicway_deploy_sequence
import nordicway_deploy_health
import nordicway_release_backup
import nordicway_autostart

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


def _update_marker(bridge, marker, sha, **values):
    record = _read_marker(marker, sha)
    record.update(values)
    fd, name = tempfile.mkstemp(prefix='.recovery-', dir=bridge)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as out:
            json.dump(record, out, separators=(',', ':'))
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, marker)
        _sync_dir(bridge)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read_marker(marker, sha):
    fd = os.open(marker, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 1024):
            raise ValueError('invalid_recovery')
        record = json.loads(os.read(fd, 1025))
        if (not isinstance(record, dict) or record.get('format') != 1
                or record.get('sha') != sha or set(record) - {'format', 'sha', 'backup', 'state', 'motor_enabled', 'motor_disabled'}):
            raise ValueError('invalid_recovery')
        return record
    finally:
        os.close(fd)


def _record_backup(bridge, marker, target, sha, backup):
    backup = Path(backup)
    parent = Path(target).parent / '.escape_backups'
    if (parent.is_symlink() or backup.is_symlink() or not backup.is_dir()
            or backup.parent.resolve() != parent.resolve()
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', backup.name)):
        raise ValueError('invalid_backup')
    # This is persisted before the first code file is replaced.
    _update_marker(bridge, marker, sha, backup=backup.name)


def _record_state(bridge, marker, target, sha, state):
    var = Path(target) / 'var'
    if var.is_symlink() or not var.is_dir():
        raise ValueError('invalid_motor_state')
    enabled = nordicway_autostart._present(var / 'hotwatch-autostart.enabled')
    disabled = nordicway_autostart._present(var / 'hotwatch-autostart.disabled')
    _update_marker(bridge, marker, sha, state=state, motor_enabled=enabled, motor_disabled=disabled)


def _approval_ticket(bridge, sha):
    fd = os.open(bridge / 'approval-ticket.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 512):
            raise ValueError('invalid_approval_ticket')
        data = json.loads(os.read(fd, 513))
        if (not isinstance(data, dict) or set(data) != {'sha','nonce','expires'}
                or data['sha'] != sha or type(data['expires']) is not int
                or data['expires'] < int(time.time()) or not isinstance(data['nonce'], str)
                or not re.fullmatch(r'[0-9a-f]{32}', data['nonce'])):
            raise ValueError('invalid_approval_ticket')
    finally:
        os.close(fd)


def run(sha, token, *, bridge=BRIDGE, checkout=CHECKOUT, target=TARGET,
        adapter_factory=nordicway_deploy_adapter.Adapter,
        deploy=nordicway_deploy_sequence.deploy, prepare=prepare_checkout, authorization_lock=None, owner_request=None):
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid_request')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        raise ValueError('invalid_request')
    bridge = _private_directory(bridge)
    lock_path = authorization_lock or Path(target) / 'var' / 'escape-deploy.lock'
    # Lock only the approval check and durable claim; release before the
    # existing Adapter.lock(), which otherwise would deadlock on a second fd.
    with nordicway_owner_approval.deployment_lock(lock_path):
        if owner_request is not None:
            nordicway_owner_approval.approve(bridge, lock_path, sha, owner_request, already_locked=True)
        if _approved_sha(bridge) != sha:
            raise ValueError('unapproved_release')
        _approval_ticket(bridge, sha)
        marker = _claim(bridge, sha)
        (bridge / 'approval-ticket.json').unlink()
        _sync_dir(bridge)
    result = None
    sequence_started = False
    try:
        prepare(checkout, sha)
        adapter = adapter_factory(checkout, target, sha, 1, None, None, cpanel_token=token)
        adapter.state_observer = lambda state: _record_state(bridge, marker, target, sha, state)
        adapter.backup_observer = lambda backup: _record_backup(bridge, marker, target, sha, backup)
        sequence_started = True
        result = deploy(adapter, sha)
        if ((result.status in ('ok', 'updated_stopped') and result.stage == 'complete')
                or (result.status == 'failed' and result.stage in
                    ('authorization', 'preflight', 'quota', 'stage', 'service_state'))):
            # Before the stop step no app/DB mutation has occurred. A rejected
            # preflight or quota must not require manual recovery. Failures
            # from stop onward remain blocked unless deployment completed.
            marker.unlink()
            _sync_dir(bridge)
        # Paths, tokens and exception details are deliberately not returned.
        reply = {'operation': 'deploy', 'status': result.status, 'stage': result.stage,
                'service_restored': result.service_restored,
                'recovery_required': marker.exists(), 'backup_cleanup': result.backup_cleanup}
        if result.reason is not None:
            reply['reason'] = result.reason
        return reply
    except Exception:
        # Uncertainty is not proof that no production change occurred.
        if not sequence_started:
            try:
                marker.unlink()
                _sync_dir(bridge)
            except OSError:
                pass
        return {'operation': 'deploy', 'status': 'failed', 'stage': 'runner',
                'service_restored': False, 'recovery_required': sequence_started or marker.exists(),
                'backup_cleanup': 'not_run'}


def run_request(sha, stream):
    raw = stream.read(4097)
    if not isinstance(raw, bytes) or len(raw) > 4096:
        raise ValueError('invalid_request')
    try:
        request = json.loads(raw)
    except (UnicodeError, ValueError):
        raise ValueError('invalid_request') from None
    if not isinstance(request, dict) or set(request) != {'cpanel_token', 'approval'}:
        raise ValueError('invalid_request')
    return run(sha, request['cpanel_token'], owner_request=request['approval'])


def resume(sha, *, bridge=BRIDGE, checkout=CHECKOUT, target=TARGET,
           adapter_factory=nordicway_deploy_adapter.Adapter,
           running_health=nordicway_deploy_health.wait):
    """Resume only a complete, verified install; never restore the database.

    An incomplete code replacement, missing backup, unknown original service
    state, or a failed healthcheck remains blocked for operator investigation.
    """
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid_request')
    bridge = _private_directory(bridge)
    if _approved_sha(bridge) != sha:
        raise ValueError('unapproved_release')
    marker = bridge / 'deployment-incomplete.json'
    try:
        adapter = adapter_factory(checkout, target, sha, 1, None, None)
        with adapter.lock():
            record = _read_marker(marker, sha)
            name = record.get('backup')
            if record.get('state') != 'started' or not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', name):
                raise ValueError('manual_recovery_required')
            var = Path(target) / 'var'
            if (var.is_symlink() or not var.is_dir()
                    or type(record.get('motor_enabled')) is not bool
                    or type(record.get('motor_disabled')) is not bool
                    or nordicway_autostart._present(var / 'hotwatch-autostart.enabled') != record['motor_enabled']
                    or nordicway_autostart._present(var / 'hotwatch-autostart.disabled') != record['motor_disabled']):
                raise ValueError('motor_state_changed')
            parent = Path(target).parent / '.escape_backups'
            backup = parent / name
            manifest_path = backup / 'manifest.json'
            if (parent.is_symlink() or backup.is_symlink() or not backup.is_dir()
                    or manifest_path.is_symlink() or not manifest_path.is_file()
                    or manifest_path.stat().st_size > 200000):
                raise ValueError('invalid_backup')
            manifest = json.loads(manifest_path.read_bytes())
            if not isinstance(manifest, dict) or manifest.get('format') != 1:
                raise ValueError('invalid_backup')
            expected = {'files': manifest.get('files'), 'keys': manifest.get('keys')}
            nordicway_release_backup.verify_backup(backup, expected)
            digest = hashlib.sha256()
            with (backup / 'escape.db').open('rb') as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != manifest.get('database_sha256'):
                raise ValueError('invalid_backup')
            state = adapter.service_status()
            if state == 'stopped':
                with adapter.quiescence():
                    adapter.verify_installed(sha)
                adapter.start_service()
                adapter.verify_health(sha)
            elif state == 'started':
                adapter.verify_installed(sha)
                since = datetime.fromtimestamp(marker.stat().st_mtime, timezone.utc)
                if running_health(Path(target), sha, since) is not True:
                    raise ValueError('health_unverified')
            else:
                raise ValueError('service_state_unknown')
            try:
                adapter.cleanup_backup(backup)
                cleanup = 'ok'
            except Exception:
                cleanup = 'failed'
            (bridge / 'approval-ticket.json').unlink(missing_ok=True)
            marker.unlink()
            _sync_dir(bridge)
        return {'operation': 'resume', 'status': 'ok', 'recovery_required': False, 'backup_cleanup': cleanup}
    except Exception:
        return {'operation': 'resume', 'status': 'failed', 'recovery_required': True, 'backup_cleanup': 'not_run'}
