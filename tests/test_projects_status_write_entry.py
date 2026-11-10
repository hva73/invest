import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_status_write_entry as entry


class EntryTest(unittest.TestCase):
    def test_disabled_gate_does_not_read_tokens_or_call_runner(self):
        env = {'ESCAPE_PROJECTS_TOKEN': 'fake-project', 'JOURNAL_TOKEN': 'fake-journal', 'ISSUE_TOKEN': 'fake-issue'}
        with patch.dict(os.environ, env, clear=True), patch.object(entry.runner, 'run') as run:
            with self.assertRaises(entry.writer.Blocked): entry.main()
            run.assert_not_called()
            self.assertEqual(os.environ.get('ESCAPE_PROJECTS_TOKEN'), 'fake-project')


if __name__ == '__main__': unittest.main()
