#!/usr/bin/env python3
"""Restricted Actions entrypoint for ESCAPE Projects status requests."""
import os
import sys
import re

import projects_status_write_prototype as writer
import projects_status_write_runner as runner


def main():
    # Stop before reading credentials until a reviewed change enables writing.
    if writer.LIVE_WRITE_ENABLED is not True:
        raise writer.Blocked('live status writing is disabled')
    raw_issue = os.environ.get('PROJECT_ISSUE_NUMBER', '')
    if not re.fullmatch(r'[1-9][0-9]{0,2}', raw_issue):
        raise writer.Blocked('invalid issue number')
    issue_number = int(raw_issue)
    if issue_number not in runner.dryrun.ALLOWED_ISSUES:
        raise writer.Blocked('issue not allowed')
    project_token = os.environ.pop('ESCAPE_PROJECTS_TOKEN', '')
    journal_token = os.environ.pop('JOURNAL_TOKEN', '')
    issue_token = os.environ.pop('ISSUE_TOKEN', '')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    return runner.run(project_token, journal_token, issue_token, run_id, issue_number)


if __name__ == '__main__':
    try:
        main()
        print('VERIFIED: kontrollér Issue og Projects-readback.')
    except writer.Uncertain:
        print('UNCERTAIN: stop, afstem tavle og journal, og gentag ikke automatisk.')
        sys.exit(1)
    except Exception:
        print('BLOCKED: status kunne ikke behandles; ingen rå svardata udskrives.')
        sys.exit(1)

