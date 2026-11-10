"""Issue #4 audit for the disabled writer prototype; never writes Projects."""
import json
import re
import urllib.request

URL = 'https://api.github.com/repos/hva73/invest/issues/4/comments'


class AuditFailed(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post(token, request_id, outcome, run_id, simulated=False):
    if (not isinstance(token, str) or not token or not isinstance(request_id, str)
            or not re.fullmatch(r'[a-f0-9]{32}', request_id)
            or outcome not in ('verified', 'blocked', 'uncertain')
            or not isinstance(run_id, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', run_id)
            or not isinstance(simulated, bool)):
        raise AuditFailed('invalid audit context')
    marker = f'<!-- escape-project-status:{"test:" if simulated else ""}{request_id}:{outcome} -->'
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'Content-Type': 'application/json', 'User-Agent': 'escape-projects-audit'}
    opener = urllib.request.build_opener(NoRedirect())
    try:
        for page in range(1, 101):
            req = urllib.request.Request(f'{URL}?per_page=100&page={page}', headers=headers)
            with opener.open(req, timeout=15) as response:
                comments = json.load(response)
            if not isinstance(comments, list):
                raise AuditFailed('incomplete issue comments')
            if any(marker in c['body'] for c in comments if isinstance(c, dict)
                   and isinstance(c.get('body'), str) and (c.get('user') or {}).get('id') == 41898282):
                return 'RECORDED'
            if len(comments) < 100:
                break
        else:
            raise AuditFailed('incomplete issue comments')
        labels = {'verified': 'Statusændring verificeret med readback.',
                  'blocked': 'Anmodningen blev blokeret før en bekræftet statusændring.',
                  'uncertain': 'Udfaldet er usikkert; stop og afstem tavle og journal før nyt forsøg.'}
        if simulated:
            label = {'verified': 'simuleret verificeret', 'blocked': 'simuleret blokeret', 'uncertain': 'simuleret usikkert'}[outcome]
            body = f'{marker}\n**Projects audit-test: {label}.** Ingen Projects-status er ændret.\n\n[Se Actions-kørsel](https://github.com/hva73/invest/actions/runs/{run_id}).'
        else:
            body = f'{marker}\n**Projects:** {labels[outcome]}\n\n[Se Actions-kørsel](https://github.com/hva73/invest/actions/runs/{run_id}).'
        req = urllib.request.Request(URL, method='POST', data=json.dumps({'body': body}).encode(), headers=headers)
        with opener.open(req, timeout=15) as response:
            if response.status != 201:
                raise AuditFailed('audit outcome uncertain')
        return 'RECORDED'
    except AuditFailed:
        raise
    except Exception:
        raise AuditFailed('audit outcome uncertain') from None
