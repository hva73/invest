"""Conservative UAPI quota conversion; not wired to live deployment.

Units and freshness must be verified against the hosting provider before use.
"""
import re
import os
import json
import urllib.request
import urllib.error
import nordicway_uapi_probe
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR


def parse(payload):
    try:
        if not isinstance(payload, dict): raise ValueError()
        result = payload.get('result', payload)
        if not isinstance(result, dict) or result.get('status') not in (1, '1'): raise ValueError()
        rows = result.get('data')
        if not isinstance(rows, list): raise ValueError()
        matches = [x for x in rows if isinstance(x, dict) and (x.get('name') == 'diskusage' or x.get('id') == 'diskusage')]
        if len(matches) != 1: raise ValueError()
        row = matches[0]
        if row.get('units') != 'MB' or type(row.get('normalized')) is not int or row['normalized'] != 1: raise ValueError()
        values = []
        for key in ('_count', '_max'):
            value = row.get(key)
            if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,6})?', value): raise ValueError()
            number = Decimal(value)
            quantum = Decimal(1).scaleb(number.as_tuple().exponent)
            values.append((number, quantum))
        used, limit = values
        # Allow for rounding in each displayed numeric value and ambiguous MB
        # conventions. This deliberately understates free capacity.
        used_bytes = int(((used[0] + used[1]) * 1048576).to_integral_value(rounding=ROUND_CEILING))
        limit_bytes = int((max(Decimal(0), limit[0] - limit[1]) * 1000000).to_integral_value(rounding=ROUND_FLOOR))
        if limit_bytes <= 0 or used_bytes > limit_bytes: raise ValueError()
        return {'used_upper_bytes': used_bytes, 'limit_lower_bytes': limit_bytes,
                'free_lower_bytes': limit_bytes - used_bytes}
    except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation):
        raise ValueError('quota_unavailable') from None


def read(token, opener=None):
    """Fetch and parse a UAPI response without exposing token or raw data."""
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        raise ValueError('quota_unavailable')
    try:
        opener = opener or urllib.request.build_opener(nordicway_uapi_probe.NoRedirect())
        request = urllib.request.Request(nordicway_uapi_probe.URL,
                  headers={'Authorization':'cpanel nordicr4:' + token, 'Accept':'application/json'})
        with opener.open(request, timeout=15) as response:
            if response.status != 200: raise ValueError()
            raw = response.read(65537)
        if len(raw) > 65536: raise ValueError()
        return parse(json.loads(raw))
    except (OSError, ValueError, TypeError, AttributeError, urllib.error.URLError):
        raise ValueError('quota_unavailable') from None


def verify_space(path, required_bytes, token, *, opener=None, statvfs=os.statvfs):
    if type(required_bytes) is not int or required_bytes <= 0:
        raise ValueError('invalid_space_requirement')
    quota = read(token, opener)
    try:
        fs = statvfs(path)
        fs_free = fs.f_bavail * fs.f_frsize
    except OSError:
        raise ValueError('filesystem_space_unavailable') from None
    if quota['free_lower_bytes'] < required_bytes or fs_free < required_bytes:
        raise ValueError('insufficient_space')
    return {'account_free_lower_bytes':quota['free_lower_bytes'],
            'filesystem_free_bytes':fs_free, 'required_bytes':required_bytes}
