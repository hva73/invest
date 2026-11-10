#!/usr/bin/env python3
"""Test branch rules only on a fixed disposable ref, never on the journal."""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = 'https://api.github.com/repos/hva73/invest'
BRANCH = 'codex/replay-protection-disposable'
REF = 'refs/heads/' + BRANCH
RULESET = 26966131


class Blocked(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest':
        raise Blocked('Forkert repository.')
    token = os.environ.pop('RULE_TEST_TOKEN', '')
    if not token:
        raise Blocked('Testtoken mangler.')
    opener = urllib.request.build_opener(NoRedirect())

    def call(path, method='GET', body=None):
        req = urllib.request.Request(BASE + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'escape-disposable-rule-test'})
        try:
            with opener.open(req, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.load(error)
            except (ValueError, OSError):
                raise Blocked('GitHub returnerede et usikkert svar.') from None

    status, rules = call('/rulesets/' + str(RULESET))
    refs = ((rules.get('conditions') or {}).get('ref_name') or {}) if isinstance(rules, dict) else {}
    types = {r.get('type') for r in rules.get('rules', [])} if isinstance(rules, dict) else set()
    checks = {'ruleset': status == 200 and rules.get('id') == RULESET,
              'active': rules.get('enforcement') == 'active',
              'target': REF in refs.get('include', []) and refs.get('exclude') == [],
              'rules': {'deletion', 'non_fast_forward'} <= types,
              'test_identity_no_bypass': rules.get('current_user_can_bypass') == 'never'}
    if not all(checks.values()):
        raise Blocked('Beskyttelse kunne ikke verificeres: ' + ', '.join(k for k, v in checks.items() if not v))

    status, data = call('/git/ref/heads/' + BRANCH)
    head = (data.get('object') or {}).get('sha') if isinstance(data, dict) else None
    if status != 200 or not isinstance(head, str) or len(head) != 40:
        raise Blocked('Testgrenens aktuelle commit mangler.')
    status, commit = call('/git/commits/' + head)
    parents = commit.get('parents', []) if isinstance(commit, dict) else []
    parent = parents[0].get('sha') if len(parents) == 1 else None
    if status != 200 or not isinstance(parent, str) or len(parent) != 40:
        raise Blocked('Testgrenens forgænger kunne ikke verificeres.')

    def rejected(status, body):
        # Do not mistake missing permissions or an unrelated validation error for rule enforcement.
        message = str(body.get('message', '')) if isinstance(body, dict) else ''
        if status not in (403, 409, 422) or not any(x in message.lower() for x in ('ruleset', 'protected branch', 'repository rule', 'gh013', 'gh006')):
            raise Blocked('Forsøget blev ikke utvetydigt afvist af en grenregel.')

    code, body = call('/git/refs/heads/' + BRANCH, 'DELETE')
    if 200 <= code < 300:
        raise Blocked('Testgrenen blev uventet slettet; stop.')
    rejected(code, body)
    code, data = call('/git/ref/heads/' + BRANCH)
    if code != 200 or (data.get('object') or {}).get('sha') != head:
        raise Blocked('Testgrenen ændrede sig under forsøget.')
    code, body = call('/git/refs/heads/' + BRANCH, 'PATCH', {'sha': parent, 'force': True})
    if 200 <= code < 300:
        raise Blocked('Force-push på testgrenen blev uventet tilladt; stop.')
    rejected(code, body)
    code, data = call('/git/ref/heads/' + BRANCH)
    if code != 200 or (data.get('object') or {}).get('sha') != head:
        raise Blocked('Testgrenen ændrede sig under forsøget.')
    print('PASS: Sletning og non-fast-forward blev afvist; testgrenen er uændret.')


if __name__ == '__main__':
    try:
        main()
    except Blocked as error:
        print('BLOCKED: ' + str(error))
        sys.exit(1)
    except Exception:
        print('BLOCKED: Usikkert resultat; ingen rå svardata udskrives.')
        sys.exit(1)
