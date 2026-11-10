"""Unwired prototype: fail-closed one-time GitHub Contents claims.

This is NOT a Projects writer or a complete lock. It must not be wired into a
workflow until branch protection, GitHub permissions, live race behavior and
recovery have been independently tested.
"""
import base64
import hashlib
import json
import re
import urllib.error
import urllib.request


class ClaimBlocked(Exception):
    pass

JOURNAL_BRANCH = 'escape-projects-journal'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def prepare_claim(request_id, comment_id, project_id, item_id, expected, target):
    """Bind a unique request to immutable, non-secret identifiers and statuses."""
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise ClaimBlocked('invalid request ID')
    if not isinstance(comment_id, int) or isinstance(comment_id, bool) or comment_id < 1:
        raise ClaimBlocked('invalid comment ID')
    if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,120}', v) for v in (project_id, item_id)):
        raise ClaimBlocked('invalid project or item ID')
    if not project_id.startswith('PVT_') or not item_id.startswith('PVTI_'):
        raise ClaimBlocked('invalid project or item ID')
    if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9 _/-]{1,60}', v) for v in (expected, target)) or expected == target:
        raise ClaimBlocked('invalid status transition')
    name = hashlib.sha256(request_id.encode()).hexdigest()
    fields = {'request_id': request_id, 'comment_id': comment_id, 'project_id': project_id,
              'item_id': item_id, 'expected': expected, 'target': target}
    binding = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    payload = json.dumps({'schema': 1, 'request_sha256': name, 'binding_sha256': binding}, sort_keys=True).encode()
    return 'claims/' + name + '.json', payload


def claim(token, request_id, comment_id, project_id, item_id, expected, target):
    """Attempt one create-only claim; all failed or ambiguous outcomes block.

    Requires a pre-created protected journal branch and repository contents
    write permission. No retries or updates: a crash after claim needs explicit
    reconciliation and must never lead to an automatic repeated write.
    """
    if not isinstance(token, str) or not token:
        raise ClaimBlocked('journal credential missing')
    path, payload = prepare_claim(request_id, comment_id, project_id, item_id, expected, target)
    if token in payload.decode():
        raise ClaimBlocked('unsafe request payload')
    body = json.dumps({'message': 'Record Projects request claim',
                       'content': base64.b64encode(payload).decode(),
                       'branch': JOURNAL_BRANCH}).encode()
    url = 'https://api.github.com/repos/hva73/invest/contents/' + path
    req = urllib.request.Request(url, data=body, method='PUT', headers={
        'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json', 'User-Agent': 'escape-project-claim'})
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=15) as response:
            if response.status != 201:
                raise ClaimBlocked('claim outcome uncertain')
    except urllib.error.HTTPError as exc:
        if exc.code in (409, 422):
            raise ClaimBlocked('claim already exists or conflicts') from None
        raise ClaimBlocked('claim rejected or uncertain') from None
    except (OSError, ValueError):
        raise ClaimBlocked('claim outcome uncertain') from None
    return 'CLAIMED'
