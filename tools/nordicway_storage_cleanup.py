"""Delete only owner-authorized old staging entries from a pinned metadata plan."""
import json
import os
from pathlib import Path
import re
import stat
import urllib.parse
import urllib.request
from nordicway_storage_inventory import NoRedirect

ROOT = '/home/nordicr4/escape_app/opdatering'
BACKUP = '/home/nordicr4/.escape_backups/20261113-181931-xhdz28wf'


def checked_path(row):
    name = row.get('file')
    if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', name)
            or name in ('.', '..', '.escape-release-19922l6v')
            or row.get('type') not in ('file', 'dir')
            or not isinstance(row.get('mtime'), int) or row['mtime'] > 1794595000
            or not isinstance(row.get('mode'), int)
            or not (stat.S_ISREG(row['mode']) if row['type'] == 'file' else stat.S_ISDIR(row['mode']))):
        raise ValueError('unsafe_staging_entry')
    return ROOT + '/' + name


def matches(expected, actual):
    return all(str(actual.get(k)) == str(expected.get(k)) for k in ('file', 'type', 'mode', 'size', 'mtime'))


def main():
    token = os.environ.get('ESCAPE_CPANEL_API_TOKEN', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        raise ValueError('credential_unavailable')
    opener = urllib.request.build_opener(NoRedirect())
    def call(operation, params):
        if operation not in ('list_files', 'delete_file'):
            raise ValueError('invalid_operation')
        request = urllib.request.Request('https://cp14.nordicway.dk:2083/execute/Fileman/' + operation + '?' + urllib.parse.urlencode(params),
            headers={'Authorization': 'cpanel nordicr4:' + token, 'Accept': 'application/json'})
        with opener.open(request, timeout=60) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('reply_too_large')
        payload = json.loads(raw); result = payload.get('result', payload)
        if result.get('status') not in (1, '1'):
            raise ValueError('api_rejected')
        return result.get('data')
    def listing(directory):
        data = call('list_files', {'dir': directory, 'show_hidden': 1})
        if not isinstance(data, list) or len(data) > 1000:
            raise ValueError('invalid_inventory')
        return {r['file']: r for r in data if isinstance(r, dict) and isinstance(r.get('file'), str)}
    before = listing(BACKUP)
    if (before.get('escape.db', {}).get('type') != 'file'
            or int(before['escape.db']['size']) != 2331734016
            or not {'code', 'escape.db', 'manifest.json', 'push_vapid.pem', 'token.key'}.issubset(before)):
        raise ValueError('retained_backup_changed')
    plan = json.loads(Path(__file__).with_name('nordicway_storage_cleanup_plan.json').read_text())
    if not isinstance(plan, list) or len(plan) != 55:
        raise ValueError('invalid_plan')
    for expected in plan:
        path = checked_path(expected)
        actual = listing(ROOT).get(expected['file'])
        if actual is None:
            print(json.dumps({'entry': expected['file'], 'status': 'already_absent'}), flush=True)
            continue
        if not matches(expected, actual):
            raise ValueError('staging_entry_changed')
        call('delete_file', {'path': path})
        print(json.dumps({'entry': expected['file'], 'status': 'deleted'}), flush=True)
    remaining = listing(ROOT)
    if any(row['file'] in remaining for row in plan):
        raise ValueError('cleanup_not_verified')
    after = listing(BACKUP)
    if any(not matches(row, after.get(name, {})) for name, row in before.items()):
        raise ValueError('retained_backup_changed')
    print(json.dumps({'status': 'verified', 'planned_entries': len(plan), 'remaining_staging_entries': len(remaining), 'retained_backup_unchanged': True}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'category': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
