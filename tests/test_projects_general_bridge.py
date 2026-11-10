import copy
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_dryrun as dryrun
import projects_replay_claim as journal
import projects_status_write_prototype as writer
import projects_status_write_audit as audit
from tests.test_projects_status_write_prototype import CONTEXT, board
from tests.test_projects_status_write_audit import Response
from tests.test_projects_dryrun import comment


class GeneralBridgeTest(unittest.TestCase):
    def test_writer_default_is_enabled_in_fresh_process(self):
        root = Path(__file__).resolve().parents[1]
        check = 'import sys; sys.path.insert(0, "development"); import projects_status_write_prototype as writer; assert writer.LIVE_WRITE_ENABLED is True'
        result = subprocess.run([sys.executable, '-c', check], cwd=root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_validator_reads_comments_and_project_item_for_target_issue(self):
        row = comment()
        issue = {'id': 'PVTI_test', 'isArchived': False,
                 'content': {'number': 5, 'repository': {'nameWithOwner': 'hva73/invest'}},
                 'fieldValueByName': {'name': 'In progress'}}
        project = {'id': 'PVT_test', 'number': 1, 'closed': False,
                   'fields': {'pageInfo': {'hasNextPage': False}, 'nodes': [{'name': 'Status', 'options': [{'name': 'In progress'}, {'name': 'Backlog'}]}]},
                   'items': {'pageInfo': {'hasNextPage': False}, 'nodes': [issue]}}
        unchanged = {'data': {'node': {'id': 'comment-node', 'body': row['body'], 'lastEditedAt': None}}}
        result = {'data': {'user': {'login': 'hva73', 'projectV2': project}}}
        env = {'GITHUB_ACTOR_ID': str(dryrun.OWNER_ID), 'GITHUB_TRIGGERING_ACTOR': 'hva73',
               'GITHUB_REPOSITORY': 'hva73/invest', 'GITHUB_REF': 'refs/heads/codex/escape-development',
               'REQUEST_COMMENT_ID': '1', 'ESCAPE_PROJECTS_TOKEN': 'fake'}
        with patch.dict(os.environ, env, clear=True), patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = [io.BytesIO(json.dumps(x).encode()) for x in ([row], unchanged, result, [row], unchanged)]
            validated = dryrun.main(issue_number=5)
            calls = factory.return_value.open.call_args_list
        self.assertEqual(validated['issue_number'], 5)
        self.assertIn('/issues/5/comments?', calls[0].args[0].full_url)
        self.assertIn('/issues/5/comments?', calls[3].args[0].full_url)

    def test_all_allowed_issues_match_actual_issue_before_mutation(self):
        for issue_number in [1, *range(3, 17)]:
            context = copy.deepcopy(CONTEXT)
            context['issue_number'] = issue_number
            state = board()
            state['node']['content']['number'] = issue_number
            after = copy.deepcopy(state)
            after['node']['fieldValueByName']['name'] = 'Backlog'
            graph = Mock(side_effect=[state, state, {'updateProjectV2ItemFieldValue': {'projectV2Item': {'id': 'PVTI_test'}}}, after])
            with self.subTest(issue=issue_number), patch.object(writer, 'LIVE_WRITE_ENABLED', True):
                self.assertEqual(writer.execute(context, Mock(return_value=context), Mock(return_value='CLAIMED'), graph), 'VERIFIED')

    def test_unlisted_or_mismatched_issues_never_write(self):
        for issue_number in [0, 2, 17, 4.0, True]:
            context = {**CONTEXT, 'issue_number': issue_number}
            graph = Mock()
            with self.subTest(issue=issue_number), patch.object(writer, 'LIVE_WRITE_ENABLED', True), self.assertRaises(writer.Blocked):
                writer.execute(context, Mock(return_value=context), Mock(return_value='CLAIMED'), graph)
            graph.assert_not_called()
        context = {**CONTEXT, 'issue_number': 5}
        graph = Mock(return_value=board())
        with patch.object(writer, 'LIVE_WRITE_ENABLED', True), self.assertRaises(writer.Blocked):
            writer.execute(context, Mock(return_value=context), Mock(return_value='CLAIMED'), graph)
        self.assertNotIn(writer.WRITE, [call.args[0] for call in graph.call_args_list])

    def test_issue_three_cannot_be_marked_done(self):
        context = copy.deepcopy(CONTEXT)
        context['issue_number'] = 3
        for status in ('Done', 'Færdig', 'Klar til installation'):
            context['request']['desired_status'] = status
            graph = Mock()
            with self.subTest(status=status), patch.object(writer, 'LIVE_WRITE_ENABLED', True), self.assertRaises(writer.Blocked):
                writer.execute(context, Mock(return_value=context), Mock(return_value='CLAIMED'), graph)
            graph.assert_not_called()

    def test_audit_is_written_to_original_issue_only(self):
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = [Response([]), Response({}, 201)]
            self.assertEqual(audit.post('fake', 'a' * 32, 'verified', '123', issue_number=16), 'RECORDED')
            self.assertTrue(factory.return_value.open.call_args.args[0].full_url.endswith('/issues/16/comments'))
        with self.assertRaises(audit.AuditFailed):
            audit.post('fake', 'a' * 32, 'verified', '123', issue_number=2)

    def test_danish_statuses_are_safe_in_parser_and_claim_binding(self):
        body = dryrun.PREFIX + '{"request_id":"' + 'a' * 32 + '","expected_status":"I gang","desired_status":"Færdig"}'
        self.assertEqual(dryrun.parse_request(body)['desired_status'], 'Færdig')
        path, _ = journal.prepare_claim('a' * 32, 123, 'PVT_test', 'PVTI_test', 'I gang', 'Færdig')
        self.assertTrue(path.startswith('claims/'))
        self.assertIsNone(dryrun.parse_request(body.replace('Færdig', 'Færdig\\nInjected')))


if __name__ == '__main__': unittest.main()
