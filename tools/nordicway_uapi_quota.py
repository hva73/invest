"""Conservative UAPI quota conversion; not wired to live deployment.

Units and freshness must be verified against the hosting provider before use.
"""
import re
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
