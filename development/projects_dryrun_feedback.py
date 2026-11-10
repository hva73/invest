#!/usr/bin/env python3
"""Publish a fixed dry-run result to issue #4; never writes Projects."""
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = 'https://api.github.com/repos/hva73/invest/issues/4/comments'


class Blocked(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest':
        raise Blocked('forkert repository')
    run = os.environ.get('GITHUB_RUN_ID', '')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
    result = os.environ.get('DRYRUN_RESULT', '')
    token = os.environ.pop('FEEDBACK_TOKEN', '')
    if not re.fullmatch(r'[1-9][0-9]{0,19}', run) or not re.fullmatch(r'[1-9][0-9]{0,5}', attempt) or result not in ('success', 'failure', 'cancelled') or not token:
        raise Blocked('ugyldig testkontekst')
    marker = f'<!-- escape-projects-dryrun-result:{run}:{attempt} -->'
    opener = urllib.request.build_opener(NoRedirect())
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'Content-Type': 'application/json', 'User-Agent': 'escape-projects-feedback'}
    for page in range(1, 101):
        req = urllib.request.Request(f'{BASE}?per_page=100&page={page}', headers=headers)
        with opener.open(req, timeout=15) as response:
            comments = json.load(response)
        if not isinstance(comments, list):
            raise Blocked('kommentarer kunne ikke læses')
        if any(marker in c['body'] for c in comments if isinstance(c, dict)
               and isinstance(c.get('body'), str) and (c.get('user') or {}).get('id') == 41898282):
            print('Resultatet er allerede dokumenteret.')
            return
        if len(comments) < 100:
            break
    else:
        raise Blocked('kommentarlisten er ufuldstændig')
    label = {'success': 'BESTÅET', 'failure': 'BLOKERET / FEJL', 'cancelled': 'AFBRUDT'}[result]
    body = (f'{marker}\n**Projects dry-run: {label}**\n\n'
            f'[Se Actions-kørsel](https://github.com/hva73/invest/actions/runs/{run}/attempts/{attempt}). '
            'Dette er en simulering; ingen Projects-status er ændret. '
            'Ved fejl eller blokering: kontrollér jobloggen før nyt forsøg.')
    req = urllib.request.Request(BASE, data=json.dumps({'body': body}).encode(), method='POST', headers=headers)
    with opener.open(req, timeout=15) as response:
        if response.status != 201:
            raise Blocked('kommentarens resultat er usikkert')
    print('Dry-run-resultatet er dokumenteret på Issue #4.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('BLOCKED: Resultatet kunne ikke dokumenteres; ingen rå svardata udskrives.')
        sys.exit(1)
