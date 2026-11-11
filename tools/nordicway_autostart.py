"""Preserve HOT WATCH autostart markers around the existing updater.

Call only while web and worker are stopped and deployment is serialized.
This helper does not stop, start, or deploy the application.
"""
import os
import stat
from contextlib import contextmanager
from pathlib import Path

NAMES = ('hotwatch-autostart.enabled', 'hotwatch-autostart.disabled')


def _present(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('unexpected_autostart_marker')
    return True


@contextmanager
def preserve(var):
    var = Path(var)
    if var.is_symlink() or not var.is_dir():
        raise ValueError('unexpected_autostart_directory')
    paths = [var / name for name in NAMES]
    before = [_present(path) for path in paths]
    try:
        yield
    finally:
        # Inspect both paths before changing either, so a symlink or directory
        # introduced during the update cannot lead us to modify another file.
        current = [_present(path) for path in paths]
        for path, was_present, is_present in zip(paths, before, current):
            if was_present and not is_present:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             getattr(os, 'O_NOFOLLOW', 0), 0o600)
                os.close(fd)
            elif not was_present and is_present:
                path.unlink()
