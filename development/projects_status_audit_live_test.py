#!/usr/bin/env python3
"""Synthetic issue-audit test; no Projects credentials or mutations."""
import os
import sys

import projects_status_write_audit as audit


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest':
        raise audit.AuditFailed('wrong repository')
    token = os.environ.pop('ISSUE_TOKEN', '')
    run = os.environ.get('GITHUB_RUN_ID', '')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
    if audit.report_job_failure(token, run, attempt, simulated=True) != 'RECORDED':
        raise audit.AuditFailed('failure audit test uncertain')
    if audit.report_job_failure(token, run, attempt, simulated=True) != 'RECORDED':
        raise audit.AuditFailed('duplicate check uncertain')
    print('PASS: simuleret workflowfejl dokumenteret; gentagelse gav ikke dublet.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('BLOCKED: audit-testen kunne ikke fuldføres; ingen rå data udskrives.')
        sys.exit(1)
