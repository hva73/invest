import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

from trading_engine_v2 import (
    EARLY_CATALYST,
    MOMENTUM,
    REGISTRY,
    Evidence,
    Instrument,
    Outcome,
    Provenance,
    Reason,
    Snapshot,
    StrategyKey,
    evaluate,
)


AT = datetime(2026, 11, 25, 10, tzinfo=timezone.utc)


def fact(name, passed=True, at=AT):
    return Evidence(name, passed, at, ("synthetic-source",))


class TradingEngineTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = Snapshot(
            "synthetic-snapshot", Instrument("TEST", "synthetic-asset"), AT,
            (
                fact("simulated_risk_passed"),
                fact("momentum_confirmed"),
                fact("catalyst_verified"),
                fact("early_reaction_confirmed"),
            ),
        )

    def test_shared_snapshot_and_strategy_specific_requirements(self):
        momentum = evaluate(self.snapshot, MOMENTUM)
        early = evaluate(self.snapshot, EARLY_CATALYST)
        self.assertEqual(momentum.outcome, Outcome.BLOCKED)
        self.assertEqual(momentum.reasons, (Reason("missing_required_input", ("macd_confirmed",)),))
        self.assertEqual(early.outcome, Outcome.DECISION)
        self.assertEqual(early.action, "simulated_entry")
        self.assertNotEqual(momentum.identity, early.identity)
        self.assertIn("macd_confirmed", REGISTRY[EARLY_CATALYST].optional_inputs)

    def test_distinct_positive_and_negative_conditions(self):
        snapshot = replace(self.snapshot, evidence=(
            fact("simulated_risk_passed"), fact("momentum_confirmed"), fact("macd_confirmed"),
            fact("catalyst_verified", False), fact("early_reaction_confirmed"),
        ))
        self.assertEqual(evaluate(snapshot, MOMENTUM).outcome, Outcome.DECISION)
        early = evaluate(snapshot, EARLY_CATALYST)
        self.assertEqual(early.outcome, Outcome.OBSERVATION)
        self.assertEqual(early.reasons, (Reason("catalyst_conditions_unmet", ("catalyst_verified",)),))
        self.assertIsNone(early.action)

        snapshot = replace(snapshot, evidence=(
            fact("simulated_risk_passed"), fact("momentum_confirmed", False),
            fact("macd_confirmed", False), fact("catalyst_verified"), fact("early_reaction_confirmed"),
        ))
        self.assertEqual(evaluate(snapshot, MOMENTUM).outcome, Outcome.OBSERVATION)
        self.assertEqual(evaluate(snapshot, EARLY_CATALYST).outcome, Outcome.DECISION)

    def test_missing_mandatory_data_and_future_evidence_block(self):
        required = "catalyst_verified"
        facts = tuple(item for item in self.snapshot.evidence if item.name != required)
        for evidence, code in (
            (facts, "missing_required_input"),
            (facts + (fact(required, at=AT + timedelta(seconds=1)),), "future_required_input"),
        ):
            with self.subTest(code=code):
                result = evaluate(replace(self.snapshot, evidence=evidence), EARLY_CATALYST)
                self.assertEqual(result.outcome, Outcome.BLOCKED)
                self.assertEqual(result.reasons, (Reason(code, (required,)),))
                self.assertIsNone(result.action)

    def test_risk_false_and_missing_block_both_strategies(self):
        snapshot = self.snapshot
        facts = snapshot.evidence[1:] + (fact("macd_confirmed"),)
        for evidence, code in (
            (facts, "missing_required_input"),
            (facts + (fact("simulated_risk_passed", False),), "simulated_risk_blocked"),
        ):
            for strategy in REGISTRY:
                with self.subTest(strategy=strategy, code=code):
                    result = evaluate(replace(snapshot, evidence=evidence), strategy)
                    self.assertEqual(result.outcome, Outcome.BLOCKED)
                    self.assertEqual(result.reasons, (Reason(code, ("simulated_risk_passed",)),))
                    self.assertIsNone(result.action)

    def test_replay_order_and_timezone_do_not_change_result(self):
        expected = evaluate(self.snapshot, EARLY_CATALYST)
        replay = replace(
            self.snapshot, as_of=AT.astimezone(timezone(timedelta(hours=1))),
            evidence=reversed(self.snapshot.evidence),
        )
        self.assertEqual(evaluate(replay, EARLY_CATALYST), expected)
        for change in (
            {"as_of": AT + timedelta(seconds=1)},
            {"snapshot_id": "synthetic-next"},
            {"instrument": Instrument("TEST", "other-asset")},
        ):
            self.assertNotEqual(evaluate(replace(replay, **change), EARLY_CATALYST).identity,
                                expected.identity)

    def test_collections_are_immutable_snapshots(self):
        sources = ["synthetic-source"]
        facts = [Evidence("catalyst_verified", True, AT, sources)]
        snapshot = replace(self.snapshot, evidence=facts)
        sources.clear()
        facts.clear()
        self.assertEqual(snapshot.evidence[0].source_ids, ("synthetic-source",))
        with self.assertRaises(FrozenInstanceError):
            snapshot.evidence[0].passed = False
        with self.assertRaises(TypeError):
            REGISTRY[EARLY_CATALYST] = REGISTRY[MOMENTUM]

    def test_provenance_is_carried_without_creating_execution_references(self):
        origin = Provenance(candidate_id="synthetic-candidate", watch_id="synthetic-watch",
                            trade_cycle_id="synthetic-cycle", entry_origin="synthetic-radar")
        result = evaluate(replace(self.snapshot, provenance=origin), EARLY_CATALYST)
        self.assertEqual(result.provenance, origin)
        self.assertIsNone(result.provenance.intent_id)
        self.assertIsNone(result.provenance.order_id)
        self.assertIsNone(result.provenance.fill_id)

        exit_ref = replace(
            origin, portfolio_id="synthetic-portfolio", position_id="synthetic-position",
            exit_origin="synthetic-holding-watch", intent_id="synthetic-intent",
            order_id="synthetic-order",
        )
        exit_result = evaluate(replace(self.snapshot, purpose="exit", provenance=exit_ref), MOMENTUM)
        self.assertEqual(exit_result.provenance, exit_ref)
        self.assertIsNone(exit_result.provenance.fill_id)
        self.assertIsNone(exit_result.action)
        self.assertEqual(exit_result.reasons, (Reason("unsupported_exit_evaluation"),))
        filled = replace(exit_ref, fill_id="synthetic-fill")
        self.assertEqual(
            evaluate(replace(self.snapshot, purpose="exit", provenance=filled), MOMENTUM).provenance,
            filled,
        )

    def test_unregistered_version_has_no_fallback(self):
        result = evaluate(self.snapshot, StrategyKey("escape_momentum", "1.0.0"))
        self.assertEqual(result.outcome, Outcome.BLOCKED)
        self.assertEqual(result.reasons, (Reason("unknown_strategy_version"),))
        self.assertIsNone(result.action)


if __name__ == "__main__":
    unittest.main()
