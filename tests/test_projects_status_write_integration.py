import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_status_write_runner as runner
from tests.test_projects_status_write_prototype import CONTEXT, board


class IntegrationTest(unittest.TestCase):
    def execute(self, reads, claim_result='CLAIMED', audit_result='RECORDED', expected=None):
        graph = Mock(side_effect=reads)
        with patch.dict(os.environ, {}, clear=True), patch.object(runner.writer, 'LIVE_WRITE_ENABLED', True), patch.object(runner.dryrun, 'main', return_value=copy.deepcopy(CONTEXT)), patch.object(runner.journal, 'claim', return_value=claim_result) as claim, patch.object(runner.writer, 'GraphQL', return_value=graph), patch.object(runner.audit, 'post', return_value=audit_result) as report:
            if expected:
                with self.assertRaises(expected): runner.run('fake-project', 'fake-journal', 'fake-issue', '123')
            else:
                self.assertEqual(runner.run('fake-project', 'fake-journal', 'fake-issue', '123'), 'VERIFIED')
            return graph, claim, report

    def test_complete_simulated_success_and_audit(self):
        graph, claim, report = self.execute([board(), board(), {'updateProjectV2ItemFieldValue': {'projectV2Item': {'id': 'PVTI_test'}}}, board('Backlog')])
        self.assertEqual([x.args[0] for x in graph.call_args_list].count(runner.writer.WRITE), 1)
        claim.assert_called_once()
        report.assert_called_once_with('fake-issue', 'a' * 32, 'verified', '123', issue_number=4)

    def test_changed_status_after_claim_does_not_mutate_and_reports_blocked(self):
        graph, claim, report = self.execute([board(), board('Backlog')], expected=runner.writer.Blocked)
        self.assertNotIn(runner.writer.WRITE, [x.args[0] for x in graph.call_args_list])
        claim.assert_called_once()
        report.assert_called_once_with('fake-issue', 'a' * 32, 'blocked', '123', issue_number=4)

    def test_uncertain_response_is_not_retried_and_reported(self):
        graph, claim, report = self.execute([board(), board(), OSError('network')], expected=runner.writer.Uncertain)
        self.assertEqual([x.args[0] for x in graph.call_args_list].count(runner.writer.WRITE), 1)
        report.assert_called_once_with('fake-issue', 'a' * 32, 'uncertain', '123', issue_number=4)

    def test_readback_mismatch_is_uncertain(self):
        graph, claim, report = self.execute([board(), board(), {'updateProjectV2ItemFieldValue': {'projectV2Item': {'id': 'PVTI_test'}}}, board('In progress')], expected=runner.writer.Uncertain)
        self.assertEqual([x.args[0] for x in graph.call_args_list].count(runner.writer.WRITE), 1)
        report.assert_called_once_with('fake-issue', 'a' * 32, 'uncertain', '123', issue_number=4)


if __name__ == '__main__': unittest.main()

