import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_status_write_readonly_probe as probe
from tests.test_projects_status_write_prototype import CONTEXT, board


class ProbeTest(unittest.TestCase):
    def test_only_read_query_is_used(self):
        calls = []
        def graph(query, variables):
            calls.append(query)
            return board()
        with patch.dict(os.environ, {'ESCAPE_PROJECTS_TOKEN': 'fake'}, clear=True), patch.object(probe.dryrun, 'main', return_value=CONTEXT), patch.object(probe.writer, 'GraphQL', return_value=graph):
            probe.main()
        self.assertEqual(calls, [probe.writer.READ])
        self.assertNotIn('mutation', calls[0].lower())


if __name__ == '__main__': unittest.main()
