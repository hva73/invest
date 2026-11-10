"""Disabled prototype adapter for existing issue validation and replay claims.

Not an Actions entrypoint. There is no automatic trigger or credential loading.
The caller must arrange shared serialization and durable issue audit first.
"""
import os

import projects_dryrun as dryrun
import projects_replay_claim as journal
import projects_status_write_prototype as writer


def run(project_token, journal_token):
    if writer.LIVE_WRITE_ENABLED is not True:
        raise writer.Blocked('live status writing is disabled')
    if not project_token or not journal_token:
        raise writer.Blocked('missing credential')

    def validate():
        os.environ['ESCAPE_PROJECTS_TOKEN'] = project_token
        try:
            return dryrun.main()
        finally:
            os.environ.pop('ESCAPE_PROJECTS_TOKEN', None)

    def claim(context):
        request = context['request']
        journal.JOURNAL_BRANCH = 'codex/projects-replay-isolated-test'
        return journal.claim(journal_token, request['request_id'], context['comment_id'],
                             context['project_id'], context['item_id'],
                             request['expected_status'], request['desired_status'])

    initial = validate()
    return writer.execute(initial, validate, claim, writer.GraphQL(project_token))
