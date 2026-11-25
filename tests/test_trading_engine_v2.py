import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from hotwatch_contract import GLOBAL_RISK, checksum
from hotwatch_strategy import BASELINE, EARLY_CATALYST_V1, risk_gate
from trading_engine_v2 import Evidence, Scope, VerifiedExecution, evaluate


class TradingEngineV2Tests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 11, 25, 14, tzinfo=timezone.utc)
        self.later = self.at + timedelta(seconds=1)
        self.scope = Scope(7, True, "NASDAQ", "asset-1", 3, "candidate", "watch", "cycle")
        self.sample = self.evidence({
            "asset_id": self.scope.asset_id, "event_time": self.at.isoformat(),
            "market_status": "REGULAR", "verification": "verified",
            "error_code": None, "price": "100",
            "context": {
                "as_of": self.at.isoformat(), "status": "verified", "position": "none",
                "tradability": "available", "fx_to_dkk": "7", "fees_dkk": "1",
                "portfolio_equity_dkk": "10000", "exposure_dkk": "0",
            },
        })
        self.risk = self.evidence({
            **GLOBAL_RISK, "proposed_quantity": "1", "stop_price": "95",
            "exit_deadline": None, "entry_allowed": True, "exit_allowed": True,
        })
        self.metrics = {
            key: self.evidence(value)
            for key, value in {
                "return_3_pct": ".6", "return_window_pct": ".6", "relative_volume": "3",
                "acceleration_pct_s2": ".01", "spread_pct": ".1", "rsi": "60",
                "volatility_pct": ".3", "breakout": True, "trend_up": True,
                "ordinary_share": True, "pluto_tradable": True,
                "no_verified_news": True, "reference_gain_pct": "2",
            }.items()
        }

    def evidence(self, value):
        return Evidence(value, self.at, self.at, ("captured-source",))

    def run_evaluation(self, spec=BASELINE, **overrides):
        arguments = dict(
            scope=self.scope, snapshot_id="snapshot", as_of=self.at, purpose="entry",
            spec=spec, spec_checksum=checksum(spec), sample=self.sample,
            metrics=self.metrics, risk=self.risk,
        )
        return evaluate(**(arguments | overrides))

    def test_real_rules_on_same_evidence_and_optional_macd(self):
        momentum = self.run_evaluation()
        early = self.run_evaluation(EARLY_CATALYST_V1)
        self.assertEqual(momentum.reasons, ("RULE_INPUT_UNAVAILABLE",))
        self.assertEqual(early.action, "BUY")
        self.assertEqual(early.origin.strategy_version, "1.0.0")
        self.metrics["macd_histogram"] = self.evidence(".1")
        self.assertEqual(self.run_evaluation().action, "BUY")
        early_with_macd = self.run_evaluation(EARLY_CATALYST_V1)
        self.assertEqual(early_with_macd.action, early.action)
        self.assertNotEqual(early_with_macd.origin.digest, early.origin.digest)
        self.metrics["return_window_pct"] = self.evidence(".2")
        self.assertEqual(self.run_evaluation(EARLY_CATALYST_V1).outcome, "observation")
        self.assertEqual(self.run_evaluation().action, "BUY")

    def test_replay_excludes_future_availability_and_event_time(self):
        early_at_cutoff = self.run_evaluation(EARLY_CATALYST_V1)
        macd = self.evidence(".1")
        self.metrics["macd_histogram"] = replace(macd, available_at=self.later)
        self.assertEqual(self.run_evaluation().outcome, "blocked")
        self.assertEqual(self.run_evaluation(EARLY_CATALYST_V1), early_at_cutoff)
        self.assertEqual(self.run_evaluation(as_of=self.later).action, "BUY")

        self.metrics["return_1_pct"] = replace(self.evidence("6"), available_at=self.later)
        self.assertEqual(self.run_evaluation(EARLY_CATALYST_V1), early_at_cutoff)
        self.assertIn("PRICE_GAP_LIMIT",
                      self.run_evaluation(EARLY_CATALYST_V1, as_of=self.later).reasons)

        self.metrics["macd_histogram"] = replace(macd, event_time=self.later)
        self.assertEqual(self.run_evaluation(as_of=self.later).outcome, "blocked")
        self.metrics["macd_histogram"] = macd
        late_sample = replace(self.sample, available_at=self.later)
        self.assertEqual(self.run_evaluation(sample=late_sample).reasons, ("SAMPLE_UNAVAILABLE",))
        late_risk = replace(self.risk, available_at=self.later)
        self.assertEqual(self.run_evaluation(risk=late_risk).reasons, ("RISK_INPUT_UNAVAILABLE",))

    def test_origin_binds_captured_values_and_provenance(self):
        original = self.run_evaluation(EARLY_CATALYST_V1)
        order = VerifiedExecution(
            self.scope.digest, original.origin.digest, "order", ("pluto-readback",),
        )
        self.assertTrue(order.links(original.origin))
        self.assertEqual(original, self.run_evaluation(
            EARLY_CATALYST_V1, metrics=dict(reversed(list(self.metrics.items()))),
        ))
        metric = self.metrics["rsi"]
        earlier = self.at - timedelta(seconds=1)
        changes = {
            "sample value": {"sample": replace(self.sample, value=self.sample.value | {"price": "101"})},
            "risk value": {"risk": replace(self.risk, value=self.risk.value | {"stop_price": "96"})},
            "metric value": {"metrics": self.metrics | {"rsi": replace(metric, value="61")}},
            "source": {"metrics": self.metrics | {"rsi": replace(metric, source_ids=("other",))}},
            "event time": {"metrics": self.metrics | {"rsi": replace(metric, event_time=earlier)}},
            "availability": {"metrics": self.metrics | {
                "rsi": replace(metric, event_time=earlier, available_at=earlier),
            }},
        }
        for name, changeset in changes.items():
            with self.subTest(name=name):
                changed = self.run_evaluation(EARLY_CATALYST_V1, **changeset)
                self.assertEqual(changed.action, original.action)
                self.assertEqual(changed.origin.snapshot_id, original.origin.snapshot_id)
                self.assertNotEqual(changed.origin.digest, original.origin.digest)
                self.assertFalse(order.links(changed.origin))
                if name == "availability":
                    event_only = self.run_evaluation(EARLY_CATALYST_V1, **changes["event time"])
                    self.assertNotEqual(changed.origin.digest, event_only.origin.digest)

    def test_unavailable_values_are_excluded_from_origin(self):
        late_sample = replace(self.sample, available_at=self.later)
        hidden_sample = replace(self.sample, value=self.sample.value | {
            "bid_at": self.later.isoformat(), "price": "999",
        })
        self.assertEqual(self.run_evaluation(sample=late_sample),
                         self.run_evaluation(sample=hidden_sample))
        late_risk = replace(self.risk, available_at=self.later)
        unsourced_risk = replace(self.risk, source_ids=(), value=object())
        self.assertEqual(self.run_evaluation(EARLY_CATALYST_V1, risk=late_risk),
                         self.run_evaluation(EARLY_CATALYST_V1, risk=unsourced_risk))
        unsourced_metrics = self.metrics | {"unused": replace(self.evidence(object()), source_ids=())}
        self.assertEqual(self.run_evaluation(), self.run_evaluation(metrics=unsourced_metrics))

    def test_gate_uses_the_captured_nested_values(self):
        original = self.run_evaluation(EARLY_CATALYST_V1)

        def mutate_inputs(observation, metrics, limits, *args, **kwargs):
            self.sample.value["context"]["tradability"] = "unavailable"
            self.risk.value["proposed_quantity"] = "999"
            return risk_gate(observation, metrics, limits, *args, **kwargs)

        with patch("trading_engine_v2.risk_gate", side_effect=mutate_inputs):
            self.assertEqual(self.run_evaluation(EARLY_CATALYST_V1), original)

    def test_common_gate_only_for_action_and_global_cap_still_applies(self):
        self.metrics["macd_histogram"] = self.evidence(".1")
        oversize = self.evidence(self.risk.value | {
            "proposed_quantity": "2", "max_notional_dkk": "5000",
        })
        with patch("trading_engine_v2.risk_gate", wraps=risk_gate) as gate:
            for spec in (BASELINE, EARLY_CATALYST_V1):
                with self.subTest(strategy=spec["strategy_id"]):
                    gate.reset_mock()
                    blocked = self.run_evaluation(spec, risk=oversize)
                    self.assertIn("POSITION_SIZE_LIMIT", blocked.reasons)
                    self.assertIsNone(blocked.action)
                    gate.assert_called_once()
            gate.reset_mock()
            self.metrics["breakout"] = self.evidence(False)
            self.assertEqual(self.run_evaluation(risk=oversize).outcome, "observation")
            gate.assert_not_called()
        self.assertEqual(self.run_evaluation(spec_checksum="wrong").reasons, ("STRATEGY_UNVERIFIED",))
        denied = self.evidence(self.risk.value | {"entry_allowed": False})
        self.assertIn("ENTRY_NOT_AUTHORIZED_BY_CANDIDATE_DECISION",
                      self.run_evaluation(EARLY_CATALYST_V1, risk=denied).reasons)

    def test_exit_origin_and_verified_execution_are_separate_and_scoped(self):
        entry = self.run_evaluation(EARLY_CATALYST_V1)
        held = self.evidence(self.sample.value | {
            "context": self.sample.value["context"] | {"position": "held", "quantity": "1"},
        })
        scope = replace(self.scope, position_id="position-1")
        exit_metrics = {"return_3_pct": self.evidence("-1"), "breakdown": self.evidence(True)}
        exit_spec = BASELINE | {"version": "1.0.1"}
        arguments = dict(scope=scope, purpose="exit", sample=held, metrics=exit_metrics)
        exit_decision = self.run_evaluation(exit_spec, **arguments)
        self.assertEqual(exit_decision.action, "SELL")
        self.assertEqual(exit_decision.origin.strategy_version, "1.0.1")
        self.assertEqual(entry.origin.strategy_version, "1.0.0")
        self.assertIsNone(self.run_evaluation(exit_spec, **(arguments | {"scope": self.scope})).action)

        order = VerifiedExecution(scope.digest, exit_decision.origin.digest, "order", ("pluto-readback",))
        self.assertTrue(order.links(exit_decision.origin))
        self.assertFalse(order.links(entry.origin))
        self.assertIsNone(order.fill_id)
        fill = replace(order, fill_id="fill")
        self.assertTrue(fill.links(exit_decision.origin))
        for change in ({"user_id": 8}, {"is_test": False}, {"portfolio_id": 4},
                       {"position_id": "position-2"}):
            other = self.run_evaluation(exit_spec, **(arguments | {"scope": replace(scope, **change)}))
            self.assertFalse(fill.links(other.origin))


if __name__ == "__main__":
    unittest.main()
