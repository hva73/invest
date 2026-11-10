import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('projects_audit', Path(__file__).resolve().parents[1] / 'development' / 'projects_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ProjectsAudit(unittest.TestCase):
    def test_paginates_and_keeps_archived_items(self):
        page = lambda nodes, more, cursor: {'node': {'items': {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}}}
        with patch.object(audit, 'graphql', side_effect=[page([{'id': 'a', 'isArchived': True}], True, 'next'), page([{'id': 'b'}], False, None)]) as query:
            self.assertEqual([x['id'] for x in audit.items('p')], ['a', 'b'])
            self.assertIn('cursor=next', query.call_args.args)

    def test_incomplete_pagination_fails_closed(self):
        response = {'node': {'items': {'nodes': [], 'pageInfo': {'hasNextPage': True, 'endCursor': None}}}}
        with patch.object(audit, 'graphql', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'pagination incomplete'):
                audit.items('p')

    def test_matching_uses_repository_and_issue_number(self):
        row = lambda repo, number: {'content': {'repository': {'nameWithOwner': repo}, 'number': number}}
        rows = [row('hva73/invest', 3), row('other/invest', 3), row('hva73/invest', 4), {'content': None}]
        self.assertEqual(audit.matching(rows, 3), [rows[0]])

    def test_read_only_audit_performs_no_mutation(self):
        with patch.object(audit, 'project', return_value={'id': 'p', 'title': audit.TITLE, 'number': 1}), patch.object(audit, 'items', return_value=[]), patch.object(audit, 'graphql') as query, patch('sys.argv', ['projects_audit.py']), patch('builtins.print'):
            audit.main()
            query.assert_not_called()

    def test_existing_issue_is_not_added_or_status_changed(self):
        existing = {'id': 'item', 'isArchived': True, 'content': {'number': 3, 'repository': {'nameWithOwner': audit.REPO}}}
        with patch.object(audit, 'project', return_value={'id': 'p', 'title': audit.TITLE, 'number': 1}), patch.object(audit, 'items', return_value=[existing]), patch.object(audit, 'graphql') as query, patch('sys.argv', ['projects_audit.py', '--add-one', '3']), patch('builtins.print'):
            audit.main()
            query.assert_not_called()

    def test_adds_only_one_missing_issue_and_verifies_readback(self):
        added = {'id': 'item', 'content': {'number': 3, 'repository': {'nameWithOwner': audit.REPO}}}
        answers = [{'repository': {'issue': {'id': 'issue'}}}, {'addProjectV2ItemById': {'item': {'id': 'item'}}}]
        with patch.object(audit, 'project', return_value={'id': 'p', 'title': audit.TITLE, 'number': 1}), patch.object(audit, 'items', side_effect=[[], [], [added]]), patch.object(audit, 'graphql', side_effect=answers) as query, patch('sys.argv', ['projects_audit.py', '--add-one', '3']), patch('builtins.print'):
            audit.main()
            self.assertEqual(query.call_count, 2)
            self.assertEqual(query.call_args_list[1].args[0], audit.ADD)


if __name__ == '__main__':
    unittest.main()
