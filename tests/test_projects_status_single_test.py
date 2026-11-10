import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_status_single_test as single

ENV = {'GITHUB_REPOSITORY': 'hva73/invest', 'GITHUB_REF': 'refs/heads/codex/escape-development',
       'GITHUB_EVENT_NAME': 'issue_comment', 'GITHUB_ACTOR_ID': str(single.dryrun.OWNER_ID),
       'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '123', 'ESCAPE_PROJECTS_TOKEN': 'fake-project',
       'JOURNAL_TOKEN': 'fake-journal', 'ISSUE_TOKEN': 'fake-issue'}
CONTEXT = {'request': single.EXPECTED.copy(), 'status': 'Backlog', 'project_id': 'PVT_test',
           'item_id': 'PVTI_test', 'comment_id': 123}


class OneShot(unittest.TestCase):
    def test_exact_approved_transition_only(self):
        def run(*args):
            self.assertTrue(single.writer.LIVE_WRITE_ENABLED)
            return 'VERIFIED'
        with patch.dict(os.environ, ENV, clear=True), patch.object(single.dryrun, 'main', return_value=CONTEXT), patch.object(single.runner, 'run', side_effect=run) as call:
            self.assertEqual(single.main(), 'VERIFIED')
            call.assert_called_once_with('fake-project', 'fake-journal', 'fake-issue', '123')
            self.assertFalse(single.writer.LIVE_WRITE_ENABLED)
            self.assertNotIn('ESCAPE_PROJECTS_TOKEN', os.environ)

    def test_unapproved_and_changed_status_are_blocked(self):
        for changed in ({**CONTEXT, 'request': {**single.EXPECTED, 'request_id': 'b' * 32}},
                        {**CONTEXT, 'status': 'In progress'},
                        {**CONTEXT, 'request': {**single.EXPECTED, 'desired_status': 'In review'}}):
            with self.subTest(changed=changed), patch.dict(os.environ, ENV, clear=True), patch.object(single.dryrun, 'main', return_value=changed), patch.object(single.runner, 'run') as call:
                with self.assertRaises(single.writer.Blocked):
                    single.main()
                call.assert_not_called()
                self.assertFalse(single.writer.LIVE_WRITE_ENABLED)

    def test_rerun_is_blocked_before_validation(self):
        with patch.dict(os.environ, {**ENV, 'GITHUB_RUN_ATTEMPT': '2'}, clear=True), patch.object(single.dryrun, 'main') as validate:
            with self.assertRaises(single.writer.Blocked):
                single.main()
            validate.assert_not_called()

    def test_gate_is_reset_if_runner_fails(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(single.dryrun, 'main', return_value=CONTEXT), patch.object(single.runner, 'run', side_effect=single.writer.Uncertain):
            with self.assertRaises(single.writer.Uncertain):
                single.main()
            self.assertFalse(single.writer.LIVE_WRITE_ENABLED)
            self.assertNotIn('ESCAPE_PROJECTS_TOKEN', os.environ)


if __name__ == '__main__':
    unittest.main()

