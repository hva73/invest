"""Contract tests for the read-only Polymarket research adapter."""
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

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

    def test_collector_limits_calls_and_never_creates_candidates(self):
        from scripts import polymarket_discovery as discovery
        now = datetime.fromtimestamp(1795400600, timezone.utc) + timedelta(minutes=3)
        raw = [
            poly.normalize_market(market(id=str(100+i), slug="market-"+str(i),
                question="Will the Fed cut rates in December?", volume24hr="9000",
                liquidityNum="30000"), now.isoformat()) for i in range(14)
        ]
        bars = [
            {"timestamp": (now-timedelta(minutes=40)).isoformat(), "yes_price": .3},
            {"timestamp": (now-timedelta(minutes=2)).isoformat(), "yes_price": .52},
        ]
        with patch.object(poly, "fetch_markets", return_value=raw) as fetch, \
             patch.object(poly, "price_history", return_value=bars) as history:
            report = discovery.collect(limit=30, max_histories=8, now=now)
        fetch.assert_called_once_with(limit=30, now=now)
        self.assertEqual(history.call_count, 8)
        self.assertEqual(report["markets_scanned"], 14)
        self.assertEqual(report["histories_attempted"], 8)
        self.assertEqual(len(report["observations"]), 8)
        self.assertTrue(all(x["research_priority"] == "REVIEW" for x in report["observations"]))
        self.assertTrue(all(not x["allowed_in_escape_candidate_payload"] for x in report["observations"]))
        self.assertEqual((report["handoffs"], report["orders"], report["persistent_backlog"]), (0, 0, False))

    def test_collector_does_not_promote_partial_or_failed_history(self):
        from scripts import polymarket_discovery as discovery
        now = datetime.fromtimestamp(1795400600, timezone.utc) + timedelta(minutes=3)
        sample = poly.normalize_market(market(), now.isoformat())
        with patch.object(poly, "fetch_markets", return_value=[sample]), \
             patch.object(poly, "price_history", side_effect=poly.PolymarketUnavailable("network")):
            result = discovery.collect(now=now)
        self.assertEqual(result["histories_attempted"], 1)
        self.assertEqual(result["observations"][0]["research_priority"], "CONTEXT_ONLY")
        self.assertEqual(result["errors"], [{"market_id": "123", "reason": "HISTORY_UNAVAILABLE"}])
        self.assertEqual(result["handoffs"], 0)

    def test_history_budget_is_bounded(self):
        from scripts import polymarket_discovery as discovery
        for budget in (True, -1, 9, 1.5, "8"):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                discovery.collect(max_histories=budget)



class ReviewEvidenceTests(unittest.TestCase):
    def test_event_identity_not_market_slug(self):
        item = poly.normalize_market(market(events=[{"id":"55","slug":"fed-event"}],
            conditionId="0x"+"a"*64, description="Resolve according to Fed release",
            resolutionSource="https://www.federalreserve.gov/"), "now")
        self.assertTrue(item["identity_complete"])
        self.assertEqual(item["url"], "https://polymarket.com/event/fed-event")
        self.assertEqual(item["no_token_id"], "789012")
        self.assertIsNone(poly.normalize_market(market(), "now")["url"])
        self.assertIsNone(poly.normalize_market(market(clobTokenIds='["1","1"]'), "now"))
        self.assertFalse(poly.normalize_market(market(events=[{"id":"55","slug":"fed-event"}]), "now")["identity_complete"])

    def test_conflicting_history_fails_closed(self):
        now = datetime(2026,11,24,tzinfo=timezone.utc)
        opener = Mock()
        t = int(now.timestamp())-60
        opener.open.return_value = FakeResponse({"history":[{"t":t,"p":.2},{"t":t,"p":.8}]})
        with self.assertRaises(poly.PolymarketUnavailable):
            poly.price_history({"yes_token_id":"123"}, opener=opener, now=now)

    def test_bad_endpoint_prices_do_not_promote(self):
        now = datetime(2026,11,24,tzinfo=timezone.utc)
        item = poly.normalize_market(market(), now.isoformat())
        for bad in (float("nan"), 2, True, None):
            bars = [{"timestamp":(now-timedelta(hours=1)).isoformat(),"yes_price":bad},
                    {"timestamp":now.isoformat(),"yes_price":.8}]
            self.assertEqual(poly.triage(item,bars,now=now)["research_priority"],"CONTEXT_ONLY")

    def test_rotation_and_duplicate_conflicts(self):
        from scripts import polymarket_discovery as discovery
        now = datetime(2026,11,24,tzinfo=timezone.utc)
        raw = [poly.normalize_market(market(id=str(100+i), volume24hr=str(20000-i*100)),now.isoformat()) for i in range(20)]
        conflict = dict(raw[0], question="different resolution question")
        with patch.object(poly,"fetch_markets",return_value=raw+[raw[1],conflict]), patch.object(poly,"price_history",return_value=[]):
            a = discovery.collect(now=now)
            b = discovery.collect(now=now+timedelta(hours=1))
        self.assertEqual(a["unique_markets"],19)
        self.assertEqual(a["duplicate_conflicts"],1)
        self.assertEqual(a["status"],"PARTIAL")
        self.assertEqual(a["histories_attempted"],8)
        self.assertNotEqual({x["market_id"] for x in a["observations"]},{x["market_id"] for x in b["observations"]})
        self.assertTrue(all(not x["candidate_eligible"] for x in a["observations"]))

if __name__ == "__main__":
    unittest.main()
