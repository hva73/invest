"""Contract tests for the read-only Polymarket research adapter."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

import polymarket_intelligence as poly


def market(**overrides):
    data = {
        "id": "123", "question": "Will the Fed cut interest rates?",
        "slug": "fed-rates-november", "active": True, "closed": False,
        "outcomes": '["Yes","No"]', "outcomePrices": '["0.72","0.28"]',
        "clobTokenIds": '["123456","789012"]',
        "liquidityNum": "25000", "volume24hr": "9000",
        "updatedAt": "2026-11-23T12:00:00Z",
    }
    data.update(overrides)
    return data


class FakeResponse:
    status = 200
    def __init__(self, value):
        self.value = json.dumps(value).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n):
        return self.value[:n]


class AdapterTests(unittest.TestCase):
    def test_market_is_non_trading_context(self):
        item = poly.normalize_market(market(), "2026-11-23T13:00:00+00:00")
        self.assertEqual(item["yes_price"], .72)
        self.assertEqual(item["classification"], "MARKET_EXPECTATION_UNVERIFIED")
        self.assertFalse(item["pluto_verified"])
        self.assertFalse(item["candidate_eligible"])
        self.assertFalse(poly.triage(item)["allowed_in_escape_candidate_payload"])

    def test_reject_unusable_markets(self):
        for change in ({"closed": True}, {"outcomes": '["A","B"]'},
                       {"outcomePrices": '["NaN","0.1"]'},
                       {"clobTokenIds": '["bad","456"]'},
                       {"id": "not-an-id"}):
            with self.subTest(change=change):
                self.assertIsNone(poly.normalize_market(market(**change), "now"))

    def test_fetch_public_markets(self):
        opener = Mock()
        opener.open.return_value = FakeResponse([market(), market(closed=True)])
        results = poly.fetch_markets(opener=opener,
                                     now=datetime(2026, 11, 23, tzinfo=timezone.utc))
        self.assertEqual(len(results), 1)
        self.assertIn("gamma-api.polymarket.com/markets?", opener.open.call_args.args[0].full_url)

    def test_history_is_timestamped_and_delta_is_not_buy(self):
        opener = Mock()
        opener.open.return_value = FakeResponse({"history": [
            {"t": 1795400000, "p": .35},
            {"t": 1795400600, "p": .55},
        ]})
        item = poly.normalize_market(market(), "now")
        history = poly.price_history(item, opener=opener)
        self.assertEqual(len(history), 2)
        result = poly.triage(item, history)
        self.assertEqual(result["change_percentage_points"], 20.0)
        self.assertEqual(result["research_priority"], "REVIEW")
        self.assertEqual(result["status"], "AFVENT_KILDEVERIFIKATION")

    def test_no_inferred_change_without_history(self):
        item = poly.normalize_market(market(), "now")
        self.assertIsNone(poly.triage(item)["change_percentage_points"])


if __name__ == "__main__":
    unittest.main()
