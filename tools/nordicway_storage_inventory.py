"""Read metadata for the two existing ESCAPE backup/staging directories only."""
import json
import os
import re
import urllib.parse
import urllib.request

ROOTS = ('/home/nordicr4/.escape_backups', '/home/nordicr4/escape_app/opdatering')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect_denied')


def main():
    token = os.environ.get('ESCAPE_CPANEL_API_TOKEN', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        raise ValueError('credential_unavailable')
    opener = urllib.request.build_opener(NoRedirect())
    def listing(directory):
        if not any(directory == root or directory.startswith(root + '/') for root in ROOTS):
            raise ValueError('directory_out_of_scope')
        query = urllib.parse.urlencode({'dir': directory, 'show_hidden': 1})
        req = urllib.request.Request('https://cp14.nordicway.dk:2083/execute/Fileman/list_files?' + query,
            headers={'Authorization': 'cpanel nordicr4:' + token, 'Accept': 'application/json'})
        with opener.open(req, timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('inventory_too_large')
        result = json.loads(raw).get('result', {})
        if result.get('status') not in (1, '1'):
            return {'status': 'unavailable'}
        rows = result.get('data')
        if not isinstance(rows, list):
            return {'status': 'unknown_shape', 'data_type': type(rows).__name__}
        if len(rows) > 500:
            raise ValueError('inventory_too_large')
        safe = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('unknown_file_shape')
            name = row.get('file', row.get('name'))
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', name) or name in ('.', '..'):
                continue
            safe.append({key: row[key] for key in ('file', 'name', 'type', 'size', 'mtime', 'mode')
                         if key in row and isinstance(row[key], (str, int, float, bool, type(None)))})
        return {'status': 'ok', 'items': safe}
    for root in ROOTS:
        result = listing(root)
        print(json.dumps({'directory': root, **result}, sort_keys=True))
        for row in result.get('items', [])[:40]:
            name = row.get('file', row.get('name'))
            if row.get('type') == 'dir':
                print(json.dumps({'directory': root + '/' + name, **listing(root + '/' + name)}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'category': type(exc).__name__}))
        raise SystemExit(1) from None
