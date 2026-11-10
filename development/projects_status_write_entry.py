#!/usr/bin/env python3
"""Disabled manual-entry prototype; do not activate without security review."""
import os
import sys

import projects_status_write_prototype as writer
import projects_status_write_runner as runner


def main():
    # Stop before reading credentials until a reviewed change enables writing.
    if writer.LIVE_WRITE_ENABLED is not True:
        raise writer.Blocked('live status writing is disabled')
    project_token = os.environ.pop('ESCAPE_PROJECTS_TOKEN', '')
    journal_token = os.environ.pop('JOURNAL_TOKEN', '')
    issue_token = os.environ.pop('ISSUE_TOKEN', '')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    return runner.run(project_token, journal_token, issue_token, run_id)


if __name__ == '__main__':
    try:
        main()
        print('VERIFIED: kontrollér Issue #4 og Projects-readback.')
    except writer.Uncertain:
        print('UNCERTAIN: stop, afstem tavle og journal, og gentag ikke automatisk.')
        sys.exit(1)
    except Exception:
        print('BLOCKED: status kunne ikke behandles; ingen rå svardata udskrives.')
        sys.exit(1)
