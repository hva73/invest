"""Provision a fixed read-only SSH guard; never install application releases.

The caller supplies the public key. The guard modules are read from an exact
Git commit in the separate checkout, and existing authorized keys are kept.
"""
import base64
import binascii
import fcntl
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

SOURCE_SHA = '533bb071739341824fa3d7f66e2f4276c8897530'
FILES = ('nordicway_server_guard.py', 'nordicway_readonly_diagnostics.py',
         'nordicway_release_preflight.py')
KEY_PATTERN = re.compile(r'ssh-ed25519 (AAAAC3NzaC1lZDI1NTE5AAAAI[A-Za-z0-9+/]{38}[A-Za-z0-9+/=]{1,8})(?: [A-Za-z0-9_.-]{1,80})?\Z')


def private_directory(path):
    if path.is_symlink():
        raise ValueError('unsafe_directory')
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    metadata = path.stat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ValueError('unsafe_directory')


def read_git_file(checkout, name):
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(checkout),
                             'show', SOURCE_SHA + ':tools/' + name],
                            capture_output=True, timeout=15, check=True,
                            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'})
    if not result.stdout or len(result.stdout) > 100000:
        raise ValueError('invalid_source')
    return result.stdout


def provision(home, checkout, python, public_key):
    home, checkout, python = Path(home), Path(checkout), Path(python)
    match = KEY_PATTERN.fullmatch(public_key.strip())
    if not match or not python.is_absolute() or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(python)) or not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError('invalid_setup')
    try:
        wire = base64.b64decode(match.group(1), validate=True)
        if len(wire) != 51 or wire[:15] != b'\x00\x00\x00\x0bssh-ed25519' or wire[15:19] != b'\x00\x00\x00\x20':
            raise ValueError('invalid_setup')
    except (binascii.Error, ValueError):
        raise ValueError('invalid_setup') from None
    # Fetch all Git objects before any change to server files.
    sources = {name: read_git_file(checkout, name) for name in FILES}
    bridge, ssh_dir = home / '.escape_bridge', home / '.ssh'
    private_directory(bridge)
    private_directory(ssh_dir)
    for name, data in sources.items():
        path = bridge / name
        if path.is_symlink():
            raise ValueError('unsafe_file')
        if path.exists():
            if not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077 or path.read_bytes() != data:
                raise ValueError('existing_guard_differs')
        else:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
    authorized = ssh_dir / 'authorized_keys'
    if authorized.is_symlink():
        raise ValueError('unsafe_authorized_keys')
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(authorized, flags, 0o600)
    with os.fdopen(fd, 'r+', encoding='utf-8') as file:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        metadata = os.fstat(file.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError('unsafe_authorized_keys')
        existing = file.read()
        entry = 'restrict,command="' + str(python) + ' -I -S ' + str(bridge / FILES[0]) + '" ' + public_key.strip()
        matches = [line for line in existing.splitlines() if match.group(1) in line]
        if matches:
            if matches != [entry]:
                raise ValueError('key_already_authorized_differently')
            return 'already_configured'
        file.write(('\n' if existing and not existing.endswith('\n') else '') + entry + '\n')
        file.flush()
        os.fsync(file.fileno())
    return 'configured'


if __name__ == '__main__':
    # The key is public and is read from standard input. The private key must
    # never be copied here or passed to this program.
    try:
        key = sys.stdin.read(512)
        result = provision(Path.home(), '/home/nordicr4/escape_deploy/invest',
                           '/home/nordicr4/virtualenv/escape_app/3.11/bin/python', key)
        print('Read-only guard: ' + result)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit('Provisioning stopped: verify checkout, source files, SSH permissions and existing keys.') from None
