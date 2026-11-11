"""Conservative checks for local writers while the web app is stopped.

This cannot prove absence of future writers or writes from another host.
The updater separately takes its exclusive SQLite lock before copying data.
"""
import os
import re
import subprocess
from pathlib import Path


def no_cron(runner=subprocess.run):
    try:
        result = runner(['crontab', '-l'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return 'no crontab for' in result.stderr.lower()
        for line in result.stdout.splitlines():
            value = line.strip()
            if value and not value.startswith('#') and not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*\s*=.*', value):
                # No active cron entries are assumed safe without inspection.
                return False
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def database_user_failure(database, proc=Path('/proc'), uid=None, self_pid=None):
    database = Path(database)
    uid = os.getuid() if uid is None else uid
    self_pid = os.getpid() if self_pid is None else self_pid
    identities = set()
    try:
        if database.is_symlink() or not database.is_file():
            return 'database_unavailable'
        for suffix in ('', '-wal', '-shm', '-journal'):
            path = Path(str(database) + suffix)
            if path.is_symlink():
                return 'database_unavailable'
            if path.exists():
                info = path.stat()
                identities.add((info.st_dev, info.st_ino))
        if not identities:
            return 'database_unavailable'
        for process in proc.iterdir():
            if not process.name.isdigit() or int(process.name) == self_pid:
                continue
            try:
                if process.stat().st_uid != uid:
                    continue
                cmd = (process / 'cmdline').read_bytes().replace(b'\0', b' ')
                # Passenger process title can contain the app path rather than
                # the wsgi file; inspect privately, return only a boolean.
                if (b'passenger_wsgi.py' in cmd or
                    (b'Passenger' in cmd and b'escape_app' in cmd)):
                    return 'passenger_active'
                for fd in (process / 'fd').iterdir():
                    try:
                        info = fd.stat()
                    except FileNotFoundError:
                        continue
                    if (info.st_dev, info.st_ino) in identities:
                        return 'database_in_use'
            except FileNotFoundError:
                # Only ignore a process that actually disappeared.
                if process.exists():
                    return 'process_inspection_unavailable'
                continue
            except (OSError, PermissionError):
                return 'process_inspection_unavailable'
        return None
    except OSError:
        return 'process_inspection_unavailable'


def no_open_database_users(database, proc=Path('/proc'), uid=None, self_pid=None):
    return database_user_failure(database, proc, uid, self_pid) is None


def failure_reason(database):
    """Report only the failed gate; never expose cron or process contents."""
    if not no_cron():
        return 'cron_unverified'
    return database_user_failure(database)


def verify(database):
    return failure_reason(database) is None
