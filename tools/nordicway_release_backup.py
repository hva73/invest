"""Private backup verification primitives, with no live restore entry point.

Callers must first prove web and worker quiescence. Inventories contain file
hashes and are private; do not publish them in Actions logs or Issue comments.
"""
import hashlib
import os
import re
import shutil
import sqlite3
import stat
from pathlib import Path
from urllib.parse import quote

PART = re.compile(r'[A-Za-z0-9_.-]+\Z')
KEYS = ('token.key', 'push_vapid.pem')
BACKUP_NAME = re.compile(r'(\d{8}-\d{6})-[A-Za-z0-9_-]+\Z')


def remove_older_backups(root, verified_backup):
    """Remove older known backups only after the caller verified the new one.

    Unknown entries, symlinks, same-second backups, and newer backups remain.
    This function never chooses the backup to retain from an ordering guess.
    """
    root, verified_backup = Path(root), Path(verified_backup)
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or verified_backup.parent != root):
        raise ValueError('unsafe_backup_directory')
    match = BACKUP_NAME.fullmatch(verified_backup.name)
    current = verified_backup.lstat()
    if (not match or not stat.S_ISDIR(current.st_mode)
            or current.st_uid != os.getuid()):
        raise ValueError('invalid_verified_backup')
    for candidate in root.iterdir():
        previous = BACKUP_NAME.fullmatch(candidate.name)
        if not previous or previous.group(1) >= match.group(1):
            continue
        try:
            entry = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(entry.st_mode) and entry.st_uid == os.getuid():
            shutil.rmtree(candidate)


def _offline_database(path):
    if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        return False
    if any(Path(str(path) + ext).exists() or Path(str(path) + ext).is_symlink() for ext in ('-wal', '-journal', '-shm')):
        return False
    with path.open('rb') as source:
        header = source.read(20)
    return len(header) == 20 and header[:16] == b'SQLite format 3\x00' and header[18:20] == b'\x01\x01'


def _path(root, name):
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or any(p in ('.', '..', '.git') or not PART.fullmatch(p) for p in relative.parts):
        raise ValueError('unsafe_path')
    node = root
    for part in relative.parts:
        node = node / part
        if node.is_symlink():
            raise ValueError('unsafe_path')
    if not node.resolve().is_relative_to(root.resolve()):
        raise ValueError('unsafe_path')
    return node


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(target, files):
    target = Path(target)
    if target.is_symlink() or not target.is_dir() or not isinstance(files, tuple) or not files or len(files) > 500:
        raise ValueError('unsafe_inventory')
    records = {}
    for name in files:
        if not isinstance(name, str) or name in records or name.startswith('var/'):
            raise ValueError('unsafe_inventory')
        path = _path(target, name)
        if path.exists() and not path.is_file():
            raise ValueError('unsafe_inventory')
        records[name] = _digest(path) if path.is_file() else None
    keys = {}
    for name in KEYS:
        path = _path(target, 'var/keys/' + name)
        if path.exists() and not path.is_file():
            raise ValueError('unsafe_inventory')
        keys[name] = _digest(path) if path.is_file() else None
    return {'files': records, 'keys': keys}


def verify_backup(backup, expected):
    backup = Path(backup)
    if backup.is_symlink() or not backup.is_dir() or not isinstance(expected, dict):
        raise ValueError('invalid_backup')
    for group, prefix in (('files', 'code/'), ('keys', '')):
        records = expected.get(group)
        if not isinstance(records, dict) or (group == 'files' and not records) or (group == 'keys' and set(records) != set(KEYS)):
            raise ValueError('invalid_backup')
        for name, digest in records.items():
            path = _path(backup, prefix + name)
            if digest is None:
                if path.exists(): raise ValueError('backup_mismatch')
            elif not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) or not path.is_file() or _digest(path) != digest:
                raise ValueError('backup_mismatch')
    database = _path(backup, 'escape.db')
    if not _offline_database(database):
        raise ValueError('invalid_backup_database')
    connection = None
    try:
        connection = sqlite3.connect('file:' + quote(str(database), safe='/') + '?mode=ro', uri=True, timeout=1)
        connection.execute('PRAGMA query_only=ON')
        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('invalid_backup_database')
    except sqlite3.Error:
        raise ValueError('invalid_backup_database') from None
    finally:
        if connection is not None:
            connection.close()
    return True


def database_digest(database):
    """Capture a quiesced DB baseline; caller must separately stop all writers."""
    database = Path(database)
    if not _offline_database(database):
        raise ValueError('database_not_quiescent')
    return _digest(database)


def ensure_database_unchanged(database, expected_digest):
    """Never authorize restoring an older DB over changed post-start data."""
    if not isinstance(expected_digest, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
        raise ValueError('invalid_database_baseline')
    if database_digest(database) != expected_digest:
        raise ValueError('database_changed_since_baseline')
    return True
