"""Temporarily stop HOT WATCH using its existing marker and lock protocol.

Call only after web service has been stopped and will not be started until this
context exits. No cron or unrelated SQLite writer detection is implied.
"""
import fcntl
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import nordicway_autostart


@contextmanager
def stopped_motor(var, timeout=30, runner=subprocess.run):
    var = Path(var)
    with nordicway_autostart.preserve(var):
        disabled = var / 'hotwatch-autostart.disabled'
        fd = os.open(disabled, os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        deadline = time.monotonic() + timeout
        while True:
            locks = []
            available = False
            try:
                for name in ('supervisor', 'worker'):
                    lock_fd = os.open(var / ('hotwatch-' + name + '.lock'),
                                      os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                    locks.append(lock_fd)
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = runner(['/bin/ps', '-u', str(os.getuid()), '-o', 'args='],
                                capture_output=True, text=True, timeout=5, check=True)
                pattern = r'(?:^|[/\s])hotwatch_(?:supervisor|service)\.py(?:\s|$)'
                available = not any(re.search(pattern, line) for line in result.stdout.splitlines())
            except BlockingIOError:
                available = False
            finally:
                for lock_fd in reversed(locks):
                    os.close(lock_fd)
            if available:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('motor_not_stopped')
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        # Do not retain the lock: apply_update acquires the same locks itself.
        # The disable marker remains present until after the updater returns.
        yield
