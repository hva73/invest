#!/usr/bin/env python3
"""Disposable live test of a deleted claim. Never touches the Projects board."""
import json
import os
import sys
import urllib.request
import uuid

import projects_replay_claim as replay

BRANCH = 'codex/replay-history-disposable'


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest':
        raise RuntimeError('wrong repository')
    token = os.environ.pop('JOURNAL_TOKEN', '')
    if not token:
        raise RuntimeError('missing credential')
    replay.JOURNAL_BRANCH = BRANCH
    args = (uuid.uuid4().hex, 123, 'PVT_disposable', 'PVTI_disposable', 'Backlog', 'In progress')
    path, _ = replay.prepare_claim(*args)
    replay.claim(token, *args)

    opener = urllib.request.build_opener(replay.NoRedirect())
    url = 'https://api.github.com/repos/hva73/invest/contents/' + path
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'Content-Type': 'application/json', 'User-Agent': 'escape-replay-test'}
    req = urllib.request.Request(url + '?ref=codex%2Freplay-history-disposable', headers=headers)
    with opener.open(req, timeout=15) as response:
        item = json.load(response)
    sha = item.get('sha')
    if not isinstance(sha, str) or len(sha) != 40 or item.get('path') != path:
        raise RuntimeError('claim readback failed')
    delete = urllib.request.Request(url, method='DELETE', headers=headers,
        data=json.dumps({'message': 'Remove disposable replay claim', 'sha': sha, 'branch': BRANCH}).encode())
    with opener.open(delete, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError('test deletion uncertain')
    try:
        replay.claim(token, *args)
    except replay.ClaimBlocked as error:
        if str(error) != 'request has journal history or history is uncertain':
            raise RuntimeError('unexpected rejection') from None
        print('PASS: slettet testpost blev afvist via GitHub-historik.')
        return
    raise RuntimeError('replay of deleted claim was incorrectly accepted')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('BLOCKED: Test mislykkedes eller udfaldet er usikkert; ingen rå svardata udskrives.')
        sys.exit(1)
