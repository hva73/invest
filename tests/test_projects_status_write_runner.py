import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_status_write_runner as runner
from tests.test_projects_status_write_prototype import CONTEXT


class RunnerTest(unittest.TestCase):
    def test_disabled_runner_does_not_read_or_claim(self):
        with patch.object(runner.writer, 'LIVE_WRITE_ENABLED', False), patch.object(runner.dryrun, 'main') as validate, patch.object(runner.journal, 'claim') as claim:
            with self.assertRaises(runner.writer.Blocked): runner.run('fake-project', 'fake-journal', 'fake-issue', '123')
            validate.assert_not_called()
            claim.assert_not_called()

    def test_runner_connects_trusted_validation_and_bound_journal(self):
        context = copy.deepcopy(CONTEXT)
        def exercise(actual, validate, claim, graphql):
            self.assertEqual(actual, context)
            self.assertEqual(validate(), context)
            self.assertEqual(claim(context), 'CLAIMED')
            return 'VERIFIED'
        with patch.dict(os.environ, {}, clear=True), patch.object(runner.writer, 'LIVE_WRITE_ENABLED', True), patch.object(runner.dryrun, 'main', return_value=context), patch.object(runner.journal, 'claim', return_value='CLAIMED') as claim, patch.object(runner.writer, 'GraphQL', return_value=Mock()), patch.object(runner.writer, 'execute', side_effect=exercise), patch.object(runner.audit, 'post', return_value='RECORDED') as audit:
            self.assertEqual(runner.run('fake-project', 'fake-journal', 'fake-issue', '123'), 'VERIFIED')
            audit.assert_called_once_with('fake-issue', 'a' * 32, 'verified', '123', issue_number=4)
            self.assertNotIn('ESCAPE_PROJECTS_TOKEN', os.environ)
            self.assertEqual(runner.journal.JOURNAL_BRANCH, 'codex/projects-replay-isolated-test')
            claim.assert_called_once_with('fake-journal', 'a' * 32, 123, 'PVT_test', 'PVTI_test', 'In progress', 'Backlog')

    def test_write_prefix_is_distinct_from_automatic_dryrun_prefix(self):
        body = runner.WRITE_PREFIX + '{"request_id":"' + 'a' * 32 + '","expected_status":"In progress","desired_status":"Backlog"}'
        self.assertIsNone(runner.dryrun.parse_request(body))
        self.assertEqual(runner.dryrun.parse_request(body, runner.WRITE_PREFIX)['request_id'], 'a' * 32)

    def test_audit_failure_after_write_is_uncertain(self):
        with patch.object(runner.writer, 'LIVE_WRITE_ENABLED', True), patch.object(runner.dryrun, 'main', return_value=CONTEXT), patch.object(runner.writer, 'GraphQL'), patch.object(runner.writer, 'execute', return_value='VERIFIED'), patch.object(runner.audit, 'post', side_effect=runner.audit.AuditFailed):
            with self.assertRaises(runner.writer.Uncertain): runner.run('fake-project', 'fake-journal', 'fake-issue', '123')


if __name__ == '__main__': unittest.main()

