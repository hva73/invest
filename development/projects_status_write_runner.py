"""Connect trusted issue validation, journal claims and status audit.

The Actions workflow provides shared serialization and required credentials.
"""
import os

import projects_dryrun as dryrun
import projects_replay_claim as journal
import projects_status_write_prototype as writer
import projects_status_write_audit as audit

WRITE_PREFIX = 'ESCAPE_PROJECTS_WRITE_V1 '


def run(project_token, journal_token, issue_token, run_id, issue_number=4):
    if writer.LIVE_WRITE_ENABLED is not True:
        raise writer.Blocked('live status writing is disabled')
    if not project_token or not journal_token or not issue_token:
        raise writer.Blocked('missing credential')
    if type(issue_number) is not int or issue_number not in dryrun.ALLOWED_ISSUES:
        raise writer.Blocked('issue not allowed')

    def validate():
        os.environ['ESCAPE_PROJECTS_TOKEN'] = project_token
        try:
            return dryrun.main(prefix=WRITE_PREFIX, issue_number=issue_number)
        finally:
            os.environ.pop('ESCAPE_PROJECTS_TOKEN', None)

    def claim(context):
        request = context['request']
        journal.JOURNAL_BRANCH = 'codex/projects-replay-isolated-test'
        return journal.claim(journal_token, request['request_id'], context['comment_id'],
                             context['project_id'], context['item_id'],
                             request['expected_status'], request['desired_status'])

    initial = validate()
    def record(outcome):
        try:
            if audit.post(issue_token, initial['request']['request_id'], outcome, run_id, issue_number=issue_number) != 'RECORDED':
                raise audit.AuditFailed('unexpected audit outcome')
        except Exception:
            raise writer.Uncertain('audit outcome uncertain; reconcile, do not retry') from None
    try:
        result = writer.execute(initial, validate, claim, writer.GraphQL(project_token))
    except writer.Uncertain:
        record('uncertain')
        raise
    except (writer.Blocked, dryrun.Blocked, journal.ClaimBlocked):
        record('blocked')
        raise
    except Exception:
        record('uncertain')
        raise writer.Uncertain('unexpected outcome; do not retry') from None
    if result != 'VERIFIED':
        record('uncertain')
        raise writer.Uncertain('unknown write result; do not retry')
    record('verified')
    return result

