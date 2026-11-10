import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import io
import json
import contextlib

spec = importlib.util.spec_from_file_location('projects_dryrun', Path(__file__).resolve().parents[1] / 'development' / 'projects_dryrun.py')
dry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dry)


def comment(identifier=1, author=351122234, edited=False, request_id='a' * 32, expected='In progress', desired='Backlog'):
    import json
    return {'id': identifier, 'user': {'id': author}, 'author_association': 'OWNER', 'performed_via_github_app': {'id': 1144995},
            'created_at': 'time', 'updated_at': 'changed' if edited else 'time',
            'body': dry.PREFIX + json.dumps({'request_id': request_id, 'expected_status': expected, 'desired_status': desired})}


class DryRun(unittest.TestCase):
    def test_valid_request(self):
        self.assertEqual(dry.validate_request([comment()], 1, 'In progress', ['In progress', 'Backlog'])['desired_status'], 'Backlog')

    def test_rejects_wrong_author_edited_missing_and_duplicates(self):
        for rows in ([comment(author=4)], [comment(edited=True)], [], [comment(), comment(identifier=2)]):
            with self.subTest(rows=rows), self.assertRaises(dry.Blocked):
                dry.validate_request(rows, 1, 'In progress', ['In progress', 'Backlog'])

    def test_rejects_wrong_or_missing_github_app(self):
        for app in ({'id': 1}, None):
            row = comment()
            row['performed_via_github_app'] = app
            with self.subTest(app=app), self.assertRaises(dry.Blocked):
                dry.validate_request([row], 1, 'In progress', ['In progress', 'Backlog'])

    def test_rejects_stale_invalid_and_same_status(self):
        for row, current, options in [(comment(), 'Review', ['In progress', 'Backlog', 'Review']), (comment(), 'In progress', ['In progress']), (comment(desired='In progress'), 'In progress', ['In progress'])]:
            with self.subTest(row=row), self.assertRaises(dry.Blocked):
                dry.validate_request([row], 1, current, options)

    def test_rejects_duplicate_json_keys_and_extra_fields(self):
        self.assertIsNone(dry.parse_request(dry.PREFIX + '{"request_id":"' + 'a' * 32 + '","request_id":"' + 'b' * 32 + '","expected_status":"X","desired_status":"Y"}'))
        self.assertIsNone(dry.parse_request(dry.PREFIX + '{"request_id":"' + 'a' * 32 + '","expected_status":"X","desired_status":"Y","extra":true}'))

    def test_full_flow_reads_and_never_writes(self):
        issue = {'id': 'PVTI_test', 'isArchived': False, 'content': {'number': 4, 'repository': {'nameWithOwner': 'hva73/invest'}}, 'fieldValueByName': {'name': 'In progress'}}
        project = {'number': 1, 'closed': False, 'fields': {'pageInfo': {'hasNextPage': False}, 'nodes': [{'name': 'Status', 'options': [{'name': 'In progress'}, {'name': 'Backlog'}]}]}, 'items': {'pageInfo': {'hasNextPage': False}, 'nodes': [issue]}}
        response = {'data': {'user': {'login': 'hva73', 'projectV2': project}}}
        opener = Mock()
        opener.open.side_effect = [io.BytesIO(json.dumps(x).encode()) for x in ([comment()], response, [comment()])]
        env = {'GITHUB_ACTOR_ID': str(dry.OWNER_ID), 'GITHUB_TRIGGERING_ACTOR': 'hva73', 'GITHUB_REPOSITORY': 'hva73/invest', 'GITHUB_REF': 'refs/heads/codex/escape-development', 'REQUEST_COMMENT_ID': '1', 'ESCAPE_PROJECTS_TOKEN': 'mock-secret-value'}
        output = io.StringIO()
        with patch.dict('os.environ', env, clear=True), patch('urllib.request.build_opener', return_value=opener), contextlib.redirect_stdout(output):
            dry.main()
        self.assertEqual([c.args[0].get_method() for c in opener.open.call_args_list], ['GET', 'POST', 'GET'])
        graph = opener.open.call_args_list[1].args[0].data.decode()
        self.assertNotIn('mutation', graph.lower())
        self.assertIn('Replay mellem kørsler er IKKE beskyttet', output.getvalue())
        self.assertNotIn('mock-secret-value', output.getvalue())

    def test_dispatch_actor_rejected_before_network(self):
        with patch.dict('os.environ', {'GITHUB_ACTOR_ID': '1'}, clear=True), patch('urllib.request.build_opener') as opener:
            with self.assertRaises(dry.Blocked):
                dry.main()
            opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
