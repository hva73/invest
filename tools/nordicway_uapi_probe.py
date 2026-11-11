"""Read-only cPanel quota shape probe; does not authorize deployment."""
import json
import os
import re
import sys
import ssl
import socket
from decimal import Decimal, InvalidOperation
import urllib.error
import urllib.request

URL = 'https://cp14.nordicway.dk:2083/execute/StatsBar/get_stats?display=diskusage'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect_denied')


def probe(token, opener=None):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        return {'status': 'invalid_credential'}
    try:
        opener = opener or urllib.request.build_opener(NoRedirect())
        request = urllib.request.Request(URL, headers={'Authorization': 'cpanel nordicr4:' + token,
                                                        'Accept': 'application/json'})
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise ValueError('http_error')
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('response_too_large')
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return {'status': 'non_json_response'}
        if not isinstance(payload, dict):
            return {'status': 'unexpected_top_level'}
        result = payload.get('result', payload)
        if not isinstance(result, dict):
            return {'status': 'unexpected_result'}
        if result.get('status') not in (1, '1'):
            return {'status': 'api_rejected'}
        rows = result.get('data')
        if not isinstance(rows, list):
            return {'status': 'missing_data_list'}
        matches = [row for row in rows if isinstance(row, dict) and
                   (row.get('name') == 'diskusage' or row.get('id') == 'diskusage')]
        if len(matches) != 1:
            return {'status': 'diskusage_not_unique', 'rows': len(rows)}
        row = matches[0]
        def shape(value):
            if not isinstance(value, str): return 'non_string'
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value): return 'number'
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?\s*(?:B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)', value, re.I): return 'number_with_unit'
            if value.lower() == 'unlimited': return 'unlimited'
            return 'other'
        def band(value):
            try:
                n = Decimal(value)
                if not n.is_finite() or n < 0: return 'unknown'
                if n < 100: return 'under_100'
                if n < 100000: return '100_to_99999'
                return '100000_or_more'
            except (InvalidOperation, TypeError, ValueError): return 'unknown'
        def near(value, low, high):
            try:
                n = Decimal(value)
                return n.is_finite() and Decimal(low) <= n <= Decimal(high)
            except (InvalidOperation, TypeError, ValueError): return False
        unit = row.get('units')
        safe_unit = unit if unit in ('B','KB','MB','GB','TB','KiB','MiB','GiB','TiB') else 'other'
        return {'status': 'ok', 'fields': {key: type(row.get(key)).__name__
                for key in ('count', 'max', '_count', '_max', 'units', 'normalized')},
                'shapes': {key: shape(row.get(key)) for key in ('count','max','_count','_max')},
                'magnitude': {key: band(row.get(key)) for key in ('_count','_max')},
                'prior_display_compatible': (safe_unit == 'MB' and near(row.get('_max'), 10000, 10500) and near(row.get('_count'), 6500, 9500)),
                'unit': safe_unit, 'normalized': row.get('normalized') if row.get('normalized') in (0,1) else 'unknown'}
    except urllib.error.HTTPError as exc:
        return {'status': 'http_error', 'code': exc.code}
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLError):
            return {'status': 'tls_error'}
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return {'status': 'timeout'}
        return {'status': 'connection_error'}
    except (TimeoutError, socket.timeout):
        return {'status': 'timeout'}
    except ssl.SSLError:
        return {'status': 'tls_error'}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'status': 'invalid_response'}


if __name__ == '__main__':
    result = probe(os.environ.get('ESCAPE_CPANEL_API_TOKEN', ''))
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result['status'] == 'ok' else 1)
