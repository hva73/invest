"""Verify a short-lived release approval from a separately protected secret."""
import fcntl
from contextlib import contextmanager, nullcontext
import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

MAX_LIFETIME = 300
SHA = re.compile(r'[0-9a-f]{40}\Z')
NONCE = re.compile(r'[0-9a-f]{32}\Z')
MAC = re.compile(r'[0-9a-f]{64}\Z')


def message(sha, nonce, expires):
    return f'escape-owner-approval-v1\n{sha}\n{nonce}\n{expires}\n'.encode('ascii')


@contextmanager
def deployment_lock(lock_path):
    """Serialize approval and the runner's approval check/marker claim."""
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('unsafe_lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def approve(bridge, lock_path, sha, request, now=None, *, already_locked=False):
    """Atomically approve exactly one SHA. Requires an owner-protected secret."""
    bridge = Path(bridge)
    now = int(time.time()) if now is None else now
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError('invalid_request')
    if not isinstance(request, dict) or set(request) != {'nonce', 'expires', 'mac'}:
        raise ValueError('invalid_request')
    nonce, expires, mac = request['nonce'], request['expires'], request['mac']
    if (not isinstance(nonce, str) or not NONCE.fullmatch(nonce) or
        type(expires) is not int or type(now) is not int or expires < now or expires > now + MAX_LIFETIME or
        not isinstance(mac, str) or not MAC.fullmatch(mac)):
        raise ValueError('invalid_request')
    info = bridge.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe_bridge')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(bridge / 'owner-approval-key', flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size != 32):
            raise ValueError('unsafe_key')
        key = os.read(fd, 33)
    finally:
        os.close(fd)
    if len(key) != 32 or not hmac.compare_digest(hmac.new(key, message(sha, nonce, expires), hashlib.sha256).hexdigest(), mac):
        raise ValueError('invalid_signature')
    with (nullcontext() if already_locked else deployment_lock(lock_path)):
        if os.path.lexists(bridge / 'deployment-incomplete.json'):
            raise ValueError('recovery_required')
        approval = bridge / 'approved-sha'
        if os.path.lexists(approval):
            fd = os.open(approval, flags)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                    raise ValueError('unsafe_approval')
            finally:
                os.close(fd)
        # One nonce is claimed before authorization. A crash may require a new
        # approval, but never permits replay of a previously used credential.
        claim = bridge / ('approval-used-' + nonce)
        claim_fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.fsync(claim_fd)
        finally:
            os.close(claim_fd)
        # Persist the directory entry before any authorization can be exposed;
        # fsync on the new file alone does not make its name crash-durable.
        directory = os.open(bridge, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        tmp_fd, name = tempfile.mkstemp(prefix='.approval-', dir=bridge)
        try:
            with os.fdopen(tmp_fd, 'wb') as out:
                os.fchmod(out.fileno(), 0o600)
                out.write((sha + '\n').encode('ascii'))
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, approval)
            # Ticket is consumed only after the deploy marker is durable.
            ticket_fd, ticket_name = tempfile.mkstemp(prefix='.ticket-', dir=bridge)
            try:
                with os.fdopen(ticket_fd, 'w', encoding='ascii') as ticket:
                    os.fchmod(ticket.fileno(), 0o600)
                    json.dump({'sha': sha, 'nonce': nonce, 'expires': expires}, ticket, separators=(',', ':'))
                    ticket.flush()
                    os.fsync(ticket.fileno())
                os.replace(ticket_name, bridge / 'approval-ticket.json')
            finally:
                if os.path.exists(ticket_name):
                    os.unlink(ticket_name)
            directory = os.open(bridge, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return {'status': 'ok', 'operation': 'approve', 'sha': sha}
