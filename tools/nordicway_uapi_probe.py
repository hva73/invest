"""Read-only cPanel quota shape probe; does not authorize deployment."""
import json
import os
import re
import sys
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
        result = json.loads(raw).get('result', {})
        rows = result.get('data')
        if result.get('status') != 1 or not isinstance(rows, list):
            raise ValueError('invalid_response')
        matches = [row for row in rows if isinstance(row, dict) and row.get('name') == 'diskusage']
        if len(matches) != 1:
            raise ValueError('invalid_response')
        row = matches[0]
        # No raw response, free-form messages, values or token in logs.
        return {'status': 'ok', 'fields': {key: type(row.get(key)).__name__
                for key in ('count', 'max', '_count', '_max', 'units', 'normalized')}}
    except (OSError, ValueError, TypeError, AttributeError, urllib.error.URLError):
        return {'status': 'unavailable'}


if __name__ == '__main__':
    result = probe(os.environ.get('ESCAPE_CPANEL_API_TOKEN', ''))
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result['status'] == 'ok' else 1)
