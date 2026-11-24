import unittest
from development.controller_dispatch import reserve

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

if __name__ == "__main__":
    unittest.main()
