import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_replay_actions_test as action


class ActionTest(unittest.TestCase):
    def test_claim_between_reads_and_conflicting_read_blocks(self):
        first = {'request': {'request_id': 'a' * 32, 'expected_status': 'Backlog', 'desired_status': 'In progress'}, 'project_id': 'PVT_a', 'item_id': 'PVTI_a', 'comment_id': 1, 'status': 'Backlog'}
        second = dict(first, status='Review')
        with patch.dict(os.environ, {'ESCAPE_PROJECTS_TOKEN': 'fake-project', 'JOURNAL_TOKEN': 'fake-journal'}, clear=True), patch.object(action.dryrun, 'main', side_effect=[first, second]), patch.object(action.replay, 'claim') as claim:
            with self.assertRaises(action.dryrun.Blocked):
                action.main()
            claim.assert_called_once()

    def test_claim_failure_blocks_second_read(self):
        first = {'request': {'request_id': 'a' * 32, 'expected_status': 'Backlog', 'desired_status': 'In progress'}, 'project_id': 'PVT_a', 'item_id': 'PVTI_a', 'comment_id': 1, 'status': 'Backlog'}
        with patch.dict(os.environ, {'ESCAPE_PROJECTS_TOKEN': 'fake-project', 'JOURNAL_TOKEN': 'fake-journal'}, clear=True), patch.object(action.dryrun, 'main', return_value=first) as read, patch.object(action.replay, 'claim', side_effect=action.replay.ClaimBlocked):
            with self.assertRaises(action.replay.ClaimBlocked):
                action.main()
            self.assertEqual(read.call_count, 1)


if __name__ == '__main__':
    unittest.main()
