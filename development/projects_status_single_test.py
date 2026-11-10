#!/usr/bin/env python3
"""One approved test only: Issue #4, Backlog -> In progress.

The normal writer remains disabled. This process enables it only after
validating the exact approved request, comment identity and current status.
No deployment, trading or automatic rollback.
"""
import os
import sys
import projects_dryrun as dryrun
import projects_status_write_prototype as writer
import projects_status_write_runner as runner

REQUEST_ID = '8f104c1ecc5e456d99f54572e6e17d87'
EXPECTED = {'request_id': REQUEST_ID, 'expected_status': 'Backlog', 'desired_status': 'In progress'}


def main():
    if (os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest'
            or os.environ.get('GITHUB_REF') != 'refs/heads/codex/escape-development'
            or os.environ.get('GITHUB_EVENT_NAME') != 'issue_comment'
            or os.environ.get('GITHUB_ACTOR_ID') != str(dryrun.OWNER_ID)
            or os.environ.get('GITHUB_RUN_ATTEMPT') != '1'):
        raise writer.Blocked('invalid one-shot context')
    token = os.environ.get('ESCAPE_PROJECTS_TOKEN', '')
    if not token:
        raise writer.Blocked('missing project credential')
    context = dryrun.main(prefix=runner.WRITE_PREFIX)
    if context.get('request') != EXPECTED or context.get('status') != 'Backlog':
        raise writer.Blocked('request is not the approved transition')
    os.environ['ESCAPE_PROJECTS_TOKEN'] = token
    try:
        writer.LIVE_WRITE_ENABLED = True
        return runner.run(token, os.environ.get('JOURNAL_TOKEN', ''),
                          os.environ.get('ISSUE_TOKEN', ''), os.environ.get('GITHUB_RUN_ID', ''))
    finally:
        writer.LIVE_WRITE_ENABLED = False
        os.environ.pop('ESCAPE_PROJECTS_TOKEN', None)


if __name__ == '__main__':
    try:
        if main() != 'VERIFIED':
            raise writer.Uncertain('unverified result')
        print('VERIFIED: godkendt overgang er genlæst; se Issue #4.')
    except writer.Uncertain:
        print('UNCERTAIN: stop og afstem tavle, journal og Issue før nyt forsøg.')
        sys.exit(1)
    except Exception:
        print('BLOCKED: testen blev ikke fuldført; ingen rå svardata udskrives.')
        sys.exit(1)

