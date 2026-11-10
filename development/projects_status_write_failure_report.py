#!/usr/bin/env python3
"""Workflow failure report. This process cannot write to Projects."""
import os
import sys
import re
import projects_status_write_audit as audit


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest':
        raise audit.AuditFailed('wrong repository')
    raw_issue = os.environ.get('PROJECT_ISSUE_NUMBER', '')
    if not re.fullmatch(r'[1-9][0-9]{0,2}', raw_issue):
        raise audit.AuditFailed('invalid issue number')
    issue_number = int(raw_issue)
    if issue_number not in audit.ALLOWED_ISSUES:
        raise audit.AuditFailed('issue not allowed')
    token = os.environ.pop('ISSUE_TOKEN', '')
    audit.report_job_failure(token, os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', ''), issue_number=issue_number)
    print('Workflowfejlen er dokumenteret på Issue.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('BLOCKED: Workflowfejlen kunne ikke dokumenteres; ingen rå data udskrives.')
        sys.exit(1)

