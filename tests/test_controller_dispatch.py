import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from development.controller_dispatch import reserve, write_status

class DispatcherBudgetTests(unittest.TestCase):
    def test_reservations_are_bounded(self):
        state = {}
        self.assertTrue(reserve(state, "2026-11-24", 120000, 60000))
        self.assertTrue(reserve(state, "2026-11-24", 120000, 60000))
        self.assertFalse(reserve(state, "2026-11-24", 120000, 1))
        self.assertEqual(state["reserved"], 120000)

    def test_default_unlimited_reservation_preserves_accounting(self):
        state = {"day": "2026-11-24", "reserved": 120000}
        self.assertTrue(reserve(state, "2026-11-24", None, 60000))
        self.assertEqual(state["reserved"], 180000)

    def test_daily_reset(self):
        state = {"day": "2026-11-24", "reserved": 120000}
        self.assertTrue(reserve(state, "2026-11-25", 120000, 60000))
        self.assertEqual(state, {"day": "2026-11-25", "reserved": 60000})

class DispatcherStatusTests(unittest.TestCase):
    def test_status_exposes_only_scheduler_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_status(root, "working", [{"issue": 273, "generation": 2,
                                             "task": "private task"}], ["268:1"])
            status = json.loads((root/"status.json").read_text())
            self.assertEqual(status["reason"], "working")
            self.assertEqual(status["active"], ["273:2"])
            self.assertEqual(status["waiting"], ["268:1"])
            self.assertNotIn("private task", str(status))
            self.assertTrue(status["updated_at"].endswith("+00:00"))

    def test_status_error_does_not_interrupt_dispatch(self):
        with patch("development.controller_dispatch.save", side_effect=OSError):
            write_status(Path("."), "queue_unavailable", [])


if __name__ == "__main__":
    unittest.main()
