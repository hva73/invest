"""Build a pinned updater input. This module does not deploy or restart.

The caller must enforce service quiescence, current quota, authorization and
recovery before invoking an updater. No command-line entry point is provided.
"""
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

import nordicway_release_preflight as preflight

APPROVED_SHA = '8ed0e6d41b24db18b8687729b344133ae5fb28fd'
MAX_BYTES = 250_000_000


def stage(checkout, target, sha, *, approved_sha=None):
    # approved_sha must come from a trusted policy, never directly from SSH input.
    # The existing fixed approved release is retained for older callers.
    allowed = APPROVED_SHA if approved_sha is None else approved_sha
    if (not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha)
            or not isinstance(allowed, str) or not re.fullmatch(r'[0-9a-f]{40}', allowed)
            or sha != allowed):
        raise ValueError('unapproved_release')
    checkout, target = Path(checkout), Path(target)
    report = preflight.inspect(checkout, target, sha)
    if report.get('status') != 'blocked' or 'reason' in report:
        raise ValueError('preflight_failed')
    # The manifest must itself be the one committed at the approved SHA.
    updater = checkout / 'apply_update.py'
    manifest_blob = preflight._git_blob(checkout, sha, 'apply_update.py')
    if len(manifest_blob) > 1_000_000 or updater.is_symlink() or not updater.is_file() or updater.stat().st_size > 1_000_000 or updater.read_bytes() != manifest_blob:
        raise ValueError('manifest_mismatch')
    names = preflight.parse_manifest(manifest_blob.decode('utf-8'))
    if 'BUILD_COMMIT' not in names:
        raise ValueError('missing_version_marker')
    updates = target / 'opdatering'
    if updates.is_symlink() or not updates.is_dir() or not updates.resolve().is_relative_to(target.resolve()):
        raise ValueError('unsafe_staging_directory')
    directory = Path(tempfile.mkdtemp(prefix='.escape-release-', dir=updates))
    digest = hashlib.sha256()
    total = 0
    try:
        for name in names:
            data = (sha + '\n').encode('ascii') if name == 'BUILD_COMMIT' else preflight._git_blob(checkout, sha, name)
            total += len(data)
            if len(data) > 50_000_000 or total > MAX_BYTES:
                raise ValueError('manifest_too_large')
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
            digest.update(name.encode('utf-8') + b'\0' + hashlib.sha256(data).digest())
        return {'path': directory, 'sha': sha, 'file_count': len(names),
                'total_bytes': total, 'staged_manifest_sha256': digest.hexdigest()}
    except Exception:
        shutil.rmtree(directory)
        raise
