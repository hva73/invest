#!/usr/bin/env python3
"""Controlled Actions test only: reads Projects, writes test journal, never Projects."""
import os
import sys

import projects_dryrun as dryrun
import projects_replay_claim as replay


def main():
    journal_token = os.environ.pop('JOURNAL_TOKEN', '')
    project_token = os.environ.get('ESCAPE_PROJECTS_TOKEN', '')
    if not journal_token or not project_token:
        raise dryrun.Blocked('Testens credentials mangler.')
    first = dryrun.main()
    replay.JOURNAL_BRANCH = 'codex/projects-replay-isolated-test'
    request = first['request']
    replay.claim(journal_token, request['request_id'], first['comment_id'],
                 first['project_id'], first['item_id'], request['expected_status'], request['desired_status'])
    os.environ['ESCAPE_PROJECTS_TOKEN'] = project_token
    second = dryrun.main()
    if first != second:
        raise dryrun.Blocked('Kort eller anmodning ændrede sig under testen.')
    print('PASS: testjournal oprettet én gang, og kort og anmodning genlæst.')
    print('Kun test: Projects-skrivning forbliver blokeret; journalbeskyttelse er ikke verificeret.')


if __name__ == '__main__':
    try:
        main()
    except (dryrun.Blocked, replay.ClaimBlocked):
        print('BLOCKED: Validering, replay eller kontrol efter registrering fejlede.')
        sys.exit(1)
    except Exception:
        print('BLOCKED: Ukendt resultat; ingen rå svardata udskrives.')
        sys.exit(1)
