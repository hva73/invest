#!/usr/bin/env python3
"""Synthetic issue-audit test; no Projects credentials or mutations."""
import os
import sys
import uuid

import projects_status_write_audit as audit


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest':
        raise audit.AuditFailed('wrong repository')
    token = os.environ.pop('ISSUE_TOKEN', '')
    run = os.environ.get('GITHUB_RUN_ID', '')
    request = uuid.uuid4().hex
    for outcome in ('verified', 'blocked', 'uncertain'):
        if audit.post(token, request, outcome, run, simulated=True) != 'RECORDED':
            raise audit.AuditFailed('audit test uncertain')
    # Repeating one result must not add a duplicate comment.
    if audit.post(token, request, 'blocked', run, simulated=True) != 'RECORDED':
        raise audit.AuditFailed('duplicate check uncertain')
    print('PASS: tre tydeligt mærkede audit-simulationer og en gentagelse behandlet.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('BLOCKED: audit-testen kunne ikke fuldføres; ingen rå data udskrives.')
        sys.exit(1)
