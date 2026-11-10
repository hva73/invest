import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_status_write_prototype as writer

CONTEXT = {'request': {'request_id': 'a' * 32, 'expected_status': 'In progress', 'desired_status': 'Backlog'},
           'project_id': 'PVT_test', 'item_id': 'PVTI_test', 'comment_id': 123, 'status': 'In progress'}


def board(status='In progress'):
    return {'user': {'login': 'hva73', 'projectV2': {'id': 'PVT_test', 'number': 1, 'closed': False,
        'fields': {'pageInfo': {'hasNextPage': False}, 'nodes': [{'id': 'field', 'name': 'Status',
            'options': [{'id': 'backlog-option', 'name': 'Backlog'}]}]}}},
        'node': {'id': 'PVTI_test', 'project': {'id': 'PVT_test'}, 'isArchived': False,
                 'content': {'number': 4, 'repository': {'nameWithOwner': 'hva73/invest'}},
                 'fieldValueByName': {'name': status}}}


class WriterTest(unittest.TestCase):
    def test_hard_gate_blocks_all_dependencies(self):
        validate = Mock(); claim = Mock(); graphql = Mock()
        with patch.object(writer, 'LIVE_WRITE_ENABLED', False), self.assertRaises(writer.Blocked): writer.execute(CONTEXT, validate, claim, graphql)
        validate.assert_not_called(); claim.assert_not_called(); graphql.assert_not_called()

    def test_verified_write_and_readback(self):
        validate = Mock(return_value=copy.deepcopy(CONTEXT)); claim = Mock(return_value='CLAIMED')
        graphql = Mock(side_effect=[board(), board(), {'updateProjectV2ItemFieldValue': {'projectV2Item': {'id': 'PVTI_test'}}}, board('Backlog')])
        with patch.object(writer, 'LIVE_WRITE_ENABLED', True):
            self.assertEqual(writer.execute(CONTEXT, validate, claim, graphql), 'VERIFIED')
        self.assertEqual([c.args[0] for c in graphql.call_args_list], [writer.READ, writer.READ, writer.WRITE, writer.READ])
        self.assertEqual(graphql.call_args_list[2].args[1]['input']['value']['singleSelectOptionId'], 'backlog-option')
        claim.assert_called_once()

    def test_unexpected_status_or_unconfirmed_claim_blocks_write(self):
        for responses, claim_result in [([board('Backlog')], 'CLAIMED'), ([board()], None), ([board(), board('Backlog')], 'CLAIMED')]:
            graphql = Mock(side_effect=responses); claim = Mock(return_value=claim_result)
            with self.subTest(responses=responses, claim_result=claim_result), patch.object(writer, 'LIVE_WRITE_ENABLED', True), self.assertRaises(writer.Blocked):
                writer.execute(CONTEXT, Mock(return_value=CONTEXT), claim, graphql)
            self.assertNotIn(writer.WRITE, [c.args[0] for c in graphql.call_args_list])

    def test_uncertain_mutation_is_not_retried(self):
        graphql = Mock(side_effect=[board(), board(), OSError('network')])
        with patch.object(writer, 'LIVE_WRITE_ENABLED', True), self.assertRaises(writer.Uncertain):
            writer.execute(CONTEXT, Mock(return_value=CONTEXT), Mock(return_value='CLAIMED'), graphql)
        self.assertEqual([c.args[0] for c in graphql.call_args_list].count(writer.WRITE), 1)

    def test_wrong_item_and_ambiguous_field_block(self):
        for change in ('item', 'field'):
            value = board()
            if change == 'item': value['node']['content']['number'] = 5
            else: value['user']['projectV2']['fields']['nodes'].append(copy.deepcopy(value['user']['projectV2']['fields']['nodes'][0]))
            graphql = Mock(return_value=value); claim = Mock()
            with self.subTest(change=change), patch.object(writer, 'LIVE_WRITE_ENABLED', True), self.assertRaises(writer.Blocked):
                writer.execute(CONTEXT, Mock(return_value=CONTEXT), claim, graphql)
            claim.assert_not_called()


if __name__ == '__main__': unittest.main()

