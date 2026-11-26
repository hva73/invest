import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from development import controller_remote
from development.controller_queue import plan


class RemoteRecoveryTests(unittest.TestCase):
    def test_one_unavailable_issue_does_not_block_others_and_recovers(self):
        rows = [
            dict(issue=1, generation=1, role="motor", priority=0,
                 status="ready", paths=["motor.py"]),
            dict(issue=1, generation=2, role="motor", priority=1,
                 status="ready", paths=["motor.py"]),
            dict(issue=2, generation=1, role="data", priority=1,
                 status="ready", paths=["data.py"]),
            dict(issue=3, generation=1, role="mobile", priority=2,
                 status="ready", paths=["ui.js"], dependencies=["1:1"]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = root / "queue.json"
            def fetch():
                return json.loads(json.dumps(rows))
            def issue_open(issue):
                if issue == 1:
                    raise subprocess.TimeoutExpired(["gh"], 30)
                return True
            with patch.object(controller_remote, "fetch_queue", side_effect=fetch), patch.object(
                controller_remote, "issue_open", side_effect=issue_open
            ) as lookup, contextlib.redirect_stdout(io.StringIO()) as log:
                controller_remote.refresh(root, queue)
                snapshot = json.loads(queue.read_text())
                self.assertEqual([r["status"] for r in snapshot],
                                 ["blocked", "blocked", "ready", "ready"])
                self.assertEqual([t.issue for t in plan(snapshot)], [2])
                self.assertEqual(lookup.call_count, 3)
                self.assertIn("ISSUE_LOOKUP_UNAVAILABLE: 1", log.getvalue())
            with patch.object(controller_remote, "fetch_queue", side_effect=fetch), patch.object(
                controller_remote, "issue_open", return_value=True
            ):
                controller_remote.refresh(root, queue)
                snapshot = json.loads(queue.read_text())
                self.assertEqual([t.issue for t in plan(snapshot)], [1])
                # Both motor and data now belong to A; B is independent.
                snapshot[0]["status"]="done"
                self.assertEqual([t.issue for t in plan(snapshot)], [1, 3])
                snapshot[1]["status"]="done"
                self.assertEqual([t.issue for t in plan(snapshot)], [2, 3])

    def test_closed_issue_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = root / "queue.json"
            rows = [dict(issue=1, status="ready")]
            with patch.object(controller_remote, "fetch_queue", return_value=rows), patch.object(
                controller_remote, "issue_open", return_value=False
            ):
                controller_remote.refresh(root, queue)
                self.assertEqual(json.loads(queue.read_text())[0]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
