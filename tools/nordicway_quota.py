"""Read account quota; never substitute filesystem space for account quota."""
import json
import os
import subprocess

# The process runs as the cPanel account itself; --user may try setuid and
# fail for an unprivileged user. Confirm the command on the target server.
COMMAND = ['/usr/local/cpanel/bin/cpapi2', '--output=json',
           'DiskUsage', 'fetchdiskusagewithextras']


def read_quota(runner=subprocess.run):
    try:
        proc = runner(COMMAND, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                      timeout=30, check=False)
        if proc.returncode != 0 or len(proc.stdout) > 20000000:
            raise ValueError('quota_unavailable')
        root = json.loads(proc.stdout)['cpanelresult']
        rows = root['data']
        if (root.get('module') != 'DiskUsage' or root.get('func') != 'fetchdiskusagewithextras'
                or root.get('event', {}).get('result') not in (1, '1')
                or not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)):
            raise ValueError('quota_unavailable')
        used, limit = rows[0].get('quotaused'), rows[0].get('quotalimit')
        if type(used) is not int or type(limit) is not int or used < 0 or limit <= 0:
            raise ValueError('quota_unavailable')
        return {'used_bytes': used, 'limit_bytes': limit, 'free_bytes': max(0, limit - used)}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('quota_unavailable') from None


def verify_space(path, required_bytes, runner=subprocess.run, statvfs=os.statvfs):
    if type(required_bytes) is not int or required_bytes <= 0:
        raise ValueError('invalid_space_requirement')
    quota = read_quota(runner)
    try:
        filesystem = statvfs(path)
        fs_free = filesystem.f_bavail * filesystem.f_frsize
    except OSError:
        raise ValueError('filesystem_space_unavailable') from None
    if quota['free_bytes'] < required_bytes or fs_free < required_bytes:
        raise ValueError('insufficient_space')
    return {'account_free_bytes': quota['free_bytes'], 'filesystem_free_bytes': fs_free,
            'required_bytes': required_bytes}
