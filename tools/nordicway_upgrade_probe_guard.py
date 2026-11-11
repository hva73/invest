"""One-time upgrade of the existing deploy guard to the reviewed write probe.

This does not change SSH authorized_keys, the read-only guard or application data.
The full deploy gate must not already be enabled.
"""
import hashlib
import os
import stat
import tempfile
import urllib.request
from pathlib import Path

GUARD_URL = 'https://raw.githubusercontent.com/hva73/invest/9b7df3dfadbafabd581fda787ec930ee4f826c25/tools/nordicway_deploy_guard.py'
OLD_SHA256 = 'bbd75eada2851a8be8756d1f2ef41c45ecfe8fc60234f0a2e9894a136e0b6b29'
NEW_SHA256 = '0f60040c9ed3c8fbf9f3f5d29b74ab1f875b8b3373adf106810f7953ad6ea20d'
BRIDGE = Path('/home/nordicr4/.escape_deploy_bridge')


def upgrade(bridge, data):
    bridge = Path(bridge)
    info = bridge.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise ValueError('unsafe_bridge')
    if os.path.lexists(bridge / 'deploy-enabled'):
        raise ValueError('deployment_must_be_disabled')
    if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != NEW_SHA256:
        raise ValueError('replacement_hash_mismatch')
    compile(data, 'nordicway_deploy_guard.py', 'exec')
    target = bridge / 'nordicway_deploy_guard.py'
    info = target.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        raise ValueError('unsafe_guard')
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    if before == NEW_SHA256:
        return 'already_installed'
    if before != OLD_SHA256:
        raise ValueError('existing_guard_hash_mismatch')
    fd, name = tempfile.mkstemp(prefix='.guard-', dir=bridge)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if os.path.lexists(bridge / 'deploy-enabled'):
            raise ValueError('deployment_must_be_disabled')
        os.replace(name, target)
        directory = os.open(bridge, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if hashlib.sha256(target.read_bytes()).hexdigest() != NEW_SHA256:
            raise ValueError('installed_guard_hash_mismatch')
        return 'installed'
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    with urllib.request.urlopen(GUARD_URL, timeout=20) as response:
        data = response.read(100001)
    if len(data) > 100000:
        raise ValueError('guard_too_large')
    outcome = upgrade(BRIDGE, data)
    print('Guard: ' + outcome)
    print('Før SHA-256: ' + (OLD_SHA256 if outcome == 'installed' else NEW_SHA256))
    print('SHA-256: ' + NEW_SHA256)


if __name__ == '__main__':
    main()
