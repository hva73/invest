#!/usr/bin/env python3
"""Workflow failure report. This process cannot write to Projects."""
import os
import sys
import projects_status_write_audit as audit


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest':
        raise audit.AuditFailed('wrong repository')
    token = os.environ.pop('ISSUE_TOKEN', '')
    audit.report_job_failure(token, os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', ''))
    print('Workflowfejlen er dokumenteret på Issue #4.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('BLOCKED: Workflowfejlen kunne ikke dokumenteres; ingen rå data udskrives.')
        sys.exit(1)
