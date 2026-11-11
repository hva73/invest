"""Bounded readback after restart. Not connected to the SSH guard."""
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import nordicway_readonly_diagnostics

HEALTH_URL = 'https://escape.nordic-response.dk/api/health'


def web_health(sha):
    request = urllib.request.Request(HEALTH_URL, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=8) as response:
        if response.status != 200 or response.geturl() != HEALTH_URL:
            return False
        data = response.read(4097)
    if len(data) > 4096:
        return False
    payload = json.loads(data)
    return (isinstance(payload, dict) and payload.get('status') == 'ok'
            and payload.get('database') is True and payload.get('build_commit') == sha)


def verify(root, sha, started_at, *, web=web_health, inspect=nordicway_readonly_diagnostics.inspect,
           now=lambda: datetime.now(timezone.utc)):
    if (not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha)
            or not isinstance(started_at, datetime) or started_at.tzinfo is None):
        return False
    root = Path(root)
    marker = root / 'BUILD_COMMIT'
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 128:
        return False
    if marker.read_text(encoding='ascii').strip() != sha or web(sha) is not True:
        return False
    report = inspect(root=root, now=now())
    db = report.get('database', {})
    if db.get('status') != 'ok':
        return False
    enabled = root / 'var' / 'hotwatch-autostart.enabled'
    disabled = root / 'var' / 'hotwatch-autostart.disabled'
    if (enabled.is_symlink() or disabled.is_symlink()
            or (enabled.exists() and not enabled.is_file())
            or (disabled.exists() and not disabled.is_file())):
        return False
    if enabled.is_file() and not disabled.exists():
        elapsed = (now() - started_at.astimezone(timezone.utc)).total_seconds()
        if elapsed < 0:
            return False
        for name in ('worker', 'supervisor'):
            item = db.get(name, {})
            age = item.get('age_seconds')
            if item.get('status') != 'running' or type(age) not in (int, float) or not 0 <= age <= min(60, elapsed):
                return False
    return True


def wait(root, sha, started_at, timeout=90, *, verify_fn=verify, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while True:
        try:
            if verify_fn(root, sha, started_at):
                return True
        except (OSError, ValueError, TypeError, urllib.error.URLError):
            pass
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        sleep(min(2, remaining))
