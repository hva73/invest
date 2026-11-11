"""Provision a separate ping-only deploy identity; never reads a private key.

Do not execute on the real server before source and active SSH key path review.
"""
import base64
import binascii
import fcntl
import hashlib
import os
import re
import stat
import sys
from pathlib import Path


def _private_dir(path):
    if path.is_symlink():
        raise ValueError('unsafe_directory')
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe_directory')


def _public_key(text):
    if not isinstance(text, str) or len(text) > 512:
        raise ValueError('invalid_key')
    parts = text.strip().split()
    if len(parts) not in (2, 3) or parts[0] != 'ssh-ed25519':
        raise ValueError('invalid_key')
    if len(parts) == 3 and not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', parts[2]):
        raise ValueError('invalid_key')
    try:
        raw = base64.b64decode(parts[1], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('invalid_key') from None
    if len(raw) != 51 or raw[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise ValueError('invalid_key')
    return parts[1], ' '.join(parts)


def provision(home, python, public_key, guard_bytes, expected_sha256):
    key, public_key = _public_key(public_key)
    home, python = Path(home), Path(python)
    if (not python.is_absolute() or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(python))
            or not python.is_file() or not os.access(python, os.X_OK)
            or not isinstance(guard_bytes, bytes) or len(guard_bytes) > 100000
            or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256 or '')
            or hashlib.sha256(guard_bytes).hexdigest() != expected_sha256):
        raise ValueError('invalid_setup')
    bridge, ssh = home / '.escape_deploy_bridge', home / '.ssh'
    _private_dir(bridge)
    _private_dir(ssh)
    destination = bridge / 'nordicway_deploy_guard.py'
    if destination.is_symlink():
        raise ValueError('unsafe_guard')
    if destination.exists():
        info = destination.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or destination.read_bytes() != guard_bytes:
            raise ValueError('existing_guard_differs')
    else:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(guard_bytes)
            output.flush()
            os.fsync(output.fileno())
    authorized = ssh / 'authorized_keys'
    if authorized.is_symlink():
        raise ValueError('unsafe_authorized_keys')
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(authorized, flags, 0o600)
    with os.fdopen(fd, 'r+', encoding='utf-8') as output:
        fcntl.flock(output.fileno(), fcntl.LOCK_EX)
        info = os.fstat(output.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('unsafe_authorized_keys')
        existing = output.read()
        entry = 'restrict,command="' + str(python) + ' -I -S ' + str(destination) + '" ' + public_key
        matching = [line for line in existing.splitlines() if key in line]
        if matching:
            if matching != [entry]:
                raise ValueError('key_already_authorized_differently')
            return 'already_configured'
        output.write(('\n' if existing and not existing.endswith('\n') else '') + entry + '\n')
        output.flush()
        os.fsync(output.fileno())
    return 'configured'


if __name__ == '__main__':
    # Only a public key is read from stdin; the user's private key never enters
    # this program. Guard contents must match the reviewed ping-only version.
    try:
        source = Path(__file__).resolve().parent / 'nordicway_deploy_guard.py'
        if source.is_symlink() or not source.is_file():
            raise ValueError('guard_unavailable')
        outcome = provision(Path('/home/nordicr4'),
                            '/home/nordicr4/virtualenv/escape_app/3.11/bin/python',
                            sys.stdin.read(513), source.read_bytes(),
                            'bbd75eada2851a8be8756d1f2ef41c45ecfe8fc60234f0a2e9894a136e0b6b29')
        print('Deploy SSH ping identity: ' + outcome)
    except (OSError, ValueError):
        raise SystemExit('Provisioning stopped; check key, existing keys and guard files.') from None
