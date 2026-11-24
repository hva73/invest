"""Contract tests for the read-only Polymarket research adapter."""
import json
import unittest
from datetime import datetime, timezone, timedelta
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
        now = datetime.fromtimestamp(1795400600, timezone.utc) + timedelta(minutes=3)
        history = poly.price_history(item, opener=opener, now=now)
        self.assertEqual(len(history), 2)
        result = poly.triage(item, history, now=now)
        self.assertEqual(result["change_percentage_points"], 20.0)
        self.assertEqual(result["research_priority"], "REVIEW")
        self.assertEqual(result["status"], "AFVENT_KILDEVERIFIKATION")

    def test_topic_word_boundaries_and_closed_market(self):
        odd = poly.normalize_market(market(question="Will a second boiler win a secret contest?"), "now")
        self.assertFalse(poly.triage(odd)["relevant_topic"])
        self.assertIsNone(poly.normalize_market(market(active=None), "now"))
        self.assertIsNone(poly.normalize_market(market(closed=None), "now"))
        self.assertIsNone(poly.normalize_market(market(slug="https://invalid.example"), "now"))

    def test_stale_and_future_history_never_raise_research_priority(self):
        observed = datetime.fromtimestamp(1795400600, timezone.utc) + timedelta(minutes=3)
        sample = poly.normalize_market(market(), observed.isoformat())
        history = [{"timestamp": (observed-timedelta(hours=25)).isoformat(), "yes_price": .2},
                   {"timestamp": (observed-timedelta(hours=4)).isoformat(), "yes_price": .6}]
        stale = poly.triage(sample, history, now=observed)
        self.assertEqual(stale["research_priority"], "CONTEXT_ONLY")
        self.assertIsNone(stale["change_percentage_points"])
        self.assertEqual(stale["history_coverage"], "UNVERIFIED")
        future = [{"timestamp": observed.isoformat(), "yes_price": .2},
                  {"timestamp": (observed+timedelta(minutes=5)).isoformat(), "yes_price": .8}]
        self.assertIsNone(poly.triage(sample, future, now=observed)["change_percentage_points"])

    def test_history_filters_future_and_outside_last_day(self):
        now = datetime.fromtimestamp(1795400600, timezone.utc) + timedelta(minutes=3)
        opener = Mock()
        opener.open.return_value = FakeResponse({"history": [
            {"t": int(now.timestamp()) - 90000, "p": .01},
            {"t": int(now.timestamp()) - 600, "p": .35},
            {"t": int(now.timestamp()) - 60, "p": .55},
            {"t": int(now.timestamp()) + 500, "p": .99},
        ]})
        history = poly.price_history({"yes_token_id": "123456"}, opener=opener, now=now)
        self.assertEqual(len(history), 2)
        self.assertEqual(poly.triage(poly.normalize_market(market(), now.isoformat()), history, now=now)["research_priority"], "REVIEW")

    def test_no_inferred_change_without_history(self):
        item = poly.normalize_market(market(), "now")
        self.assertIsNone(poly.triage(item)["change_percentage_points"])


if __name__ == "__main__":
    unittest.main()
