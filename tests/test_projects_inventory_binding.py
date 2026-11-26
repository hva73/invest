"""Offline regression of the existing read-only Projects inventory job."""
import contextlib
import io
import json
import os
from pathlib import Path
import textwrap
import unittest
from unittest.mock import patch


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/escape-projects-inventory.yml'
TOKEN = 'synthetic-inventory-secret'


def item(number, item_id=None, field_id='PVTSSF_status', status='Backlog', repo='hva73/invest'):
    return {'id': item_id or f'PVTI_{number}', 'isArchived': False,
            'content': {'number': number, 'repository': {'nameWithOwner': repo}},
            'fieldValueByName': {'name': status, 'field': {'id': field_id, 'name': 'Status'}}}


def page(items, cursor=None, project_id='PVT_project'):
    return {'data': {'user': {'login': 'hva73', 'projectV2': {
        'id': project_id, 'number': 1, 'closed': False,
        'items': {'nodes': items, 'pageInfo': {'hasNextPage': cursor is not None, 'endCursor': cursor}}}}}}


class InventoryBindingTests(unittest.TestCase):
    def execute(self, *pages):
        source = WORKFLOW.read_text().split("python3 - <<'PY'\n", 1)[1].rsplit('          PY\n', 1)[0]
        program = compile(textwrap.dedent(source), str(WORKFLOW), 'exec')
        output, requests = io.StringIO(), []
        responses = iter(pages)

        def respond(request, timeout):
            body = json.loads(request.data)
            self.assertEqual(request.full_url, 'https://api.github.com/graphql')
            self.assertTrue(body['query'].strip().startswith('query('))
            self.assertNotIn('mutation', body['query'])
            requests.append(body['variables']['cursor'])
            return io.BytesIO(json.dumps(next(responses)).encode())

        code = 0
        with patch.dict(os.environ, {'ESCAPE_PROJECTS_TOKEN': TOKEN}), \
             patch('urllib.request.OpenerDirector.open', side_effect=respond), \
             contextlib.redirect_stdout(output):
            try:
                exec(program, {})
            except SystemExit as error:
                code = error.code
        result = output.getvalue()
        self.assertNotIn(TOKEN, result)
        return code, result, requests

    def test_paginated_binding_preserves_existing_status_lines(self):
        code, out, requests = self.execute(page([item(225), item(268, repo='other/repo')], 'next'),
                                           page([item(273, status='In progress')]))
        self.assertEqual(code, 0)
        self.assertEqual(requests, [None, 'next'])
        self.assertIn('ISSUE 225: ACTIVE, status: Backlog\n', out)
        self.assertIn('BINDING 225: project=PVT_project item=PVTI_225 status_field=PVTSSF_status\n', out)
        self.assertIn('ISSUE 273: ACTIVE, status: In progress\n', out)
        self.assertNotIn('BINDING 268:', out)
        self.assertIn('PASS:', out)

    def assert_blocked(self, *pages):
        code, out, _ = self.execute(*pages)
        self.assertEqual(code, 1)
        self.assertIn('BLOCKED:', out)
        self.assertNotIn('PASS:', out)
        self.assertNotIn('BINDING ', out)

    def test_project_changes_across_pages(self):
        self.assert_blocked(page([item(225)], 'next'), page([item(273)], project_id='PVT_other'))

    def test_field_changes_across_items(self):
        self.assert_blocked(page([item(225), item(273, field_id='PVTSSF_other')]))

    def test_duplicate_issue(self):
        self.assert_blocked(page([item(225), item(225, item_id='PVTI_duplicate')]))

    def test_missing_field_identity(self):
        self.assert_blocked(page([item(225), item(273, field_id=None)]))

    def test_rejects_credential_and_unsafe_item_id(self):
        self.assert_blocked(page([item(225, item_id='PVTI_' + TOKEN)]))
        self.assert_blocked(page([item(225, item_id='PVTI_bad\nlog')]))

    def test_partial_graphql_error(self):
        self.assert_blocked({'errors': [{'message': 'partial'}], **page([item(225)])})


if __name__ == '__main__':
    unittest.main()
