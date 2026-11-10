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
        with patch.object(runner.dryrun, 'main') as validate, patch.object(runner.journal, 'claim') as claim:
            with self.assertRaises(runner.writer.Blocked): runner.run('fake-project', 'fake-journal')
            validate.assert_not_called()
            claim.assert_not_called()

    def test_runner_connects_trusted_validation_and_bound_journal(self):
        context = copy.deepcopy(CONTEXT)
        def exercise(actual, validate, claim, graphql):
            self.assertEqual(actual, context)
            self.assertEqual(validate(), context)
            self.assertEqual(claim(context), 'CLAIMED')
            return 'VERIFIED'
        with patch.dict(os.environ, {}, clear=True), patch.object(runner.writer, 'LIVE_WRITE_ENABLED', True), patch.object(runner.dryrun, 'main', return_value=context), patch.object(runner.journal, 'claim', return_value='CLAIMED') as claim, patch.object(runner.writer, 'GraphQL', return_value=Mock()), patch.object(runner.writer, 'execute', side_effect=exercise):
            self.assertEqual(runner.run('fake-project', 'fake-journal'), 'VERIFIED')
            self.assertNotIn('ESCAPE_PROJECTS_TOKEN', os.environ)
            self.assertEqual(runner.journal.JOURNAL_BRANCH, 'codex/projects-replay-isolated-test')
            claim.assert_called_once_with('fake-journal', 'a' * 32, 123, 'PVT_test', 'PVTI_test', 'In progress', 'Backlog')


if __name__ == '__main__': unittest.main()
