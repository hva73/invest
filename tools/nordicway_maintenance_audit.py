"""Daily maintenance audit using the existing restricted cPanel transport.

No production database writes, no backup deletion, no FTP account creation.
The report is an independent daily quota and retention inventory; actual
destructive retention remains tied to a verified release backup.
"""
import json
import os
import re
from datetime import datetime, timezone

import nordicway_release_retention as retention
import nordicway_uapi_quota as quota

ARCHIVE = re.compile(r'retained-(\d{8}-\d{6}-[A-Za-z0-9_-]+)\.tar\.gz\Z')
STAGE = re.compile(r'\.escape-release-[A-Za-z0-9_-]+\Z')


def inventory(uapi, directory):
    rows = uapi('list_files', {'dir': directory, 'show_hidden': 1})
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('invalid_inventory')
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid_inventory')
        name = row.get('file')
        if name in ('.', '..'):
            continue
        if not isinstance(name, str) or not name or '/' in name or '\\' in name or name in result:
            raise ValueError('invalid_inventory')
        result[name] = row
    return result


def file_bytes(row):
    value = row.get('size')
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,18}', value):
        value = int(value)
    if type(value) is not int or not 0 <= value <= 10**18:
        raise ValueError('invalid_size')
    return value


def inspect(uapi, quota_reader):
    capacity = quota_reader()
    fields = ('used_upper_bytes', 'limit_lower_bytes', 'free_lower_bytes')
    if not isinstance(capacity, dict) or any(type(capacity.get(k)) is not int or capacity[k] < 0 for k in fields):
        raise ValueError('quota_unavailable')
    if capacity['limit_lower_bytes'] - capacity['used_upper_bytes'] != capacity['free_lower_bytes']:
        raise ValueError('quota_unavailable')
    db = inventory(uapi, retention.APP + '/var').get('escape.db', {})
    if db.get('type') != 'file':
        raise ValueError('database_unavailable')
    db_bytes = file_bytes(db)
    if db_bytes <= 512:
        raise ValueError('database_unavailable')
    backups = inventory(uapi, retention.ROOT)
    stages = inventory(uapi, retention.APP + '/opdatering')
    raw = [name for name,row in backups.items() if retention.BACKUP_NAME.fullmatch(name) and row.get('type') == 'dir']
    archives = [row for name,row in backups.items() if ARCHIVE.fullmatch(name) and row.get('type') == 'file']
    raw_bytes = 0
    for name in raw:
        saved = inventory(uapi, retention.ROOT + '/' + name).get('escape.db', {})
        if saved.get('type') != 'file':
            raise ValueError('invalid_backup_inventory')
        raw_bytes += file_bytes(saved)
    archive_bytes = sum(file_bytes(row) for row in archives)
    minimum = 2 * db_bytes + max(256 * 1024 * 1024, (2 * db_bytes + 9) // 10)
    return {'status': 'ok', 'scope': 'read_only', 'observed_at': datetime.now(timezone.utc).isoformat(),
            **{k: capacity[k] for k in fields}, 'database_bytes': db_bytes,
            'raw_backups': len(raw), 'raw_backup_database_bytes': raw_bytes,
            'compressed_backups': len(archives), 'compressed_backup_bytes': archive_bytes,
            'recognized_stages': sum(bool(STAGE.fullmatch(n)) and row.get('type') == 'dir' for n,row in stages.items()),
            'database_only_reserve_floor_bytes': minimum,
            'database_only_reserve_gap_bytes': capacity['free_lower_bytes'] - minimum,
            'retention_attention': bool(raw or len(archives) > 1),
            'reserve_is_full_deploy_preflight': False}


def main():
    try:
        uapi, _, _ = retention.transport_api()
        report = inspect(uapi, lambda: quota.read(os.environ.get('ESCAPE_CPANEL_API_TOKEN', '')))
        print(json.dumps(report, sort_keys=True))
        return 1 if report['database_only_reserve_gap_bytes'] < 0 or report['retention_attention'] else 0
    except Exception:
        print('{"status":"failed","reason":"maintenance_inventory_unavailable"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
