import json
import sqlite3
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hotwatch_contract import GLOBAL_RISK, canonical, checksum
from hotwatch_features import features
from hotwatch_strategy import BASELINE, EARLY_CATALYST_V1, risk_gate, rule_state
import trading_engine_v2
from trading_engine_v2 import (
    Evidence, MarketAccess, MarketFeatureInput, MarketHistory, MarketIdentity, MarketSubscriber,
    Scope, VerifiedExecution, evaluate, evaluate_test_position_exit, market_features_batch,
    shared_market_features_batch,
    append_test_position_strategy_switch, read_test_position_switch_history,
    setup_test_position_switch_history, switch_position_strategy,
)


class SimulationConnection(sqlite3.Connection):
    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


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

    def market_input(self):
        samples = []
        for i in range(40):
            at = self.at - timedelta(minutes=39 - i)
            price = Decimal("99") + (Decimal(i) / 50 if i % 2 else Decimal(0))
            if i == 39:
                price = Decimal("100.5")
            row = {
                "source": "eodhd", "asset_id": self.scope.asset_id, "currency": "USD",
                "venue": "NASDAQ", "session_key": "2026-11-25", "market_status": "REGULAR",
                "feed_type": "US trades", "interval_s": 60, "price_time_kind": "trade",
                "verification": "verified", "event_time": at.isoformat(),
                "price": str(price), "high": str(price), "low": str(price), "close": str(price),
                "bid": str(price - Decimal(".05")), "ask": str(price + Decimal(".05")),
                "bid_at": at.isoformat(), "ask_at": at.isoformat(), "status_at": at.isoformat(),
                "volume": "400" if i == 39 else "100", "volume_type": "interval",
            }
            samples.append(Evidence(row, at, at, (f"trade:{i}",)))
        return MarketFeatureInput(
            self.scope, self.at, tuple(samples), "eodhd", "US trades", "1m",
            "revision-1", "realtime-us", "1.3.0", BASELINE["parameters"],
        )

    def shared_history(self, market):
        identity = MarketIdentity(
            market.scope.exchange, market.scope.asset_id, "USD", market.provider,
            market.feed, market.timeframe, market.revision, market.entitlement,
            market.feature_version, market.scope.is_test,
        )
        return MarketHistory(identity, market.as_of, market.samples)

    def subscriber(self, history, scope, parameters=BASELINE["parameters"]):
        grant = MarketAccess(scope.user_id, history.identity, self.later)
        return MarketSubscriber(scope, self.evidence(grant), parameters)

    def test_market_features_fan_out_to_individual_decisions(self):
        market = self.market_input()
        exit_spec = BASELINE | {
            "version": "1.0.1",
            "exit_rules": {"metric": "breakout", "operator": "==", "value": True},
        }
        local_metrics = {name: self.metrics[name] for name in (
            "ordinary_share", "pluto_tradable", "no_verified_news", "reference_gain_pct",
        )}
        for count in (1, 10, 100):
            with self.subTest(count=count):
                requests, evaluations = [], []
                for i in range(count):
                    held = i % 3 == 2
                    spec = (EARLY_CATALYST_V1, BASELINE, exit_spec)[i % 3]
                    scope = replace(
                        self.scope, user_id=i + 1, portfolio_id=i + 100,
                        position_id=f"position-{i}" if held else None,
                    )
                    context = self.sample.value["context"] | {
                        "position": "held" if held else "none", "quantity": str(i + 1),
                    }
                    last = market.samples[-1]
                    requests.append(replace(
                        market, scope=scope, parameters=spec["parameters"],
                        samples=(*market.samples[:-1], replace(last, value=last.value | {"context": context})),
                    ))
                    evaluations.append(dict(
                        spec=spec, scope=scope, snapshot_id=f"snapshot-{i}",
                        purpose="exit" if held else "entry",
                        sample=self.evidence(self.sample.value | {"context": context, "price": last.value["price"]}),
                        risk=self.evidence(self.risk.value | {"entry_allowed": i % 3 != 1}),
                    ))
                with patch("trading_engine_v2.features", wraps=features) as compute:
                    history = self.shared_history(market)
                    subscribers = [
                        self.subscriber(history, req.scope, req.parameters) for req in requests
                    ]
                    with (
                        patch("trading_engine_v2._market_rows", wraps=trading_engine_v2._market_rows) as resolve,
                        patch("trading_engine_v2.checksum", wraps=checksum) as digest,
                    ):
                        shared = shared_market_features_batch(history, subscribers)
                        resolve.assert_called_once()
                        digest.assert_not_called()
                    compute.assert_called_once()
                    with (
                        patch("trading_engine_v2._market_rows", wraps=trading_engine_v2._market_rows) as resolve,
                        patch("trading_engine_v2.checksum", wraps=checksum) as digest,
                    ):
                        self.assertEqual(shared, market_features_batch(requests))
                        self.assertEqual(resolve.call_count, count)
                        self.assertEqual(digest.call_count, count)
                    self.assertEqual(compute.call_count, 2)
                    self.assertNotIn("context", compute.call_args.args[0][-1])
                    separate = [market_features_batch([request])[0] for request in requests]
                    self.assertEqual(compute.call_count, 2 + count)
                decisions = [
                    self.run_evaluation(**args, metrics=local_metrics | facts)
                    for args, facts in zip(evaluations, shared)
                ]
                self.assertEqual(decisions, [
                    self.run_evaluation(**args, metrics=local_metrics | facts)
                    for args, facts in zip(evaluations, separate)
                ])
                self.assertEqual(len({decision.origin.digest for decision in decisions}), count)
                self.assertEqual(decisions[0].action, "BUY")
                if count > 1:
                    self.assertIn("ENTRY_NOT_AUTHORIZED_BY_CANDIDATE_DECISION", decisions[1].reasons)
                    self.assertEqual(decisions[2].action, "SELL")
                self.assertEqual(shared[0]["sample_count"].value, 40)
                shared[0].clear()
                if count > 1:
                    self.assertEqual(shared[1]["sample_count"].value, 40)

    def test_shared_batch_disjoint_work_and_parameter_groups(self):
        market = self.market_input()
        for count in (1, 10, 100):
            with self.subTest(count=count):
                requests = []
                for i in range(count):
                    scope = replace(market.scope, asset_id=f"asset-{i}")
                    rows = tuple(replace(sample, value=sample.value | {"asset_id": scope.asset_id})
                                 for sample in market.samples)
                    requests.append(replace(market, scope=scope, samples=rows))
                expected = market_features_batch(requests)
                with (
                    patch("trading_engine_v2._market_rows", wraps=trading_engine_v2._market_rows) as resolve,
                    patch("trading_engine_v2.checksum", wraps=checksum) as digest,
                    patch("trading_engine_v2.features", wraps=features) as compute,
                ):
                    actual = []
                    for request in requests:
                        history = self.shared_history(request)
                        actual.extend(shared_market_features_batch(
                            history, [self.subscriber(history, request.scope)],
                        ))
                    self.assertEqual(actual, expected)
                    self.assertEqual(resolve.call_count, count)
                    self.assertEqual(compute.call_count, count)
                    digest.assert_not_called()

        history = self.shared_history(market)
        original = self.subscriber(history, self.scope)
        variant = replace(original, parameters=original.parameters | {"short_period": 6})
        with patch("trading_engine_v2.features", wraps=features) as compute:
            first, second, again = shared_market_features_batch(history, [original, variant, original])
            self.assertEqual(compute.call_count, 2)
        self.assertEqual(first, again)
        self.assertNotEqual(first["sma_short"], second["sma_short"])

    def test_shared_batch_rejects_unverified_market_and_subscriber_inputs(self):
        history = self.shared_history(self.market_input())
        subscriber = self.subscriber(history, self.scope)
        last = history.samples[-1]

        def changed_row(**changes):
            return replace(history, samples=(*history.samples[:-1],
                                             replace(last, value=last.value | changes)))

        invalid_histories = [
            changed_row(verification="unverified"), changed_row(source="synthetic"),
            changed_row(source="pluto"), changed_row(feed_type="other"),
            changed_row(venue="NYSE"), changed_row(asset_id="other"),
            changed_row(currency="EUR"), changed_row(error_code="NO_DATA"),
            changed_row(price="NaN"), changed_row(bid_at=self.later.isoformat()),
            changed_row(price_time_kind="bar_open"),
            replace(history, samples=history.samples[:-1] + (replace(last, source_ids=()),)),
            replace(history, samples=history.samples[:-1] + (replace(last, available_at=self.later),)),
            replace(history, samples=history.samples + (last,)),
            replace(history, as_of=self.at + timedelta(seconds=121)),
        ]
        access = subscriber.access
        grant = access.value
        denied = [
            replace(subscriber, scope=replace(self.scope, user_id=8)),
            replace(subscriber, scope=replace(self.scope, exchange="NYSE")),
            replace(subscriber, scope=replace(self.scope, asset_id="other")),
            replace(subscriber, scope=replace(self.scope, is_test=False)),
            replace(subscriber, access=replace(access, value=replace(
                grant, identity=replace(history.identity, entitlement="different"),
            ))),
            replace(subscriber, access=replace(access, value=replace(
                grant, identity=replace(history.identity, is_test=False),
            ))),
            replace(subscriber, access=replace(access, source_ids=())),
            replace(subscriber, access=replace(access, available_at=self.later)),
            replace(subscriber, access=replace(access, value=replace(grant, expires_at=self.at))),
        ]
        with patch("trading_engine_v2.features", wraps=features) as compute:
            for invalid in invalid_histories:
                with self.subTest(history=invalid.samples[-1]):
                    # Keep the grant valid at the tested replay time so a stale capture
                    # cannot appear to pass simply because the entitlement expired.
                    valid = replace(subscriber, access=replace(access, value=replace(
                        grant, expires_at=self.at + timedelta(minutes=10),
                    )))
                    self.assertEqual(shared_market_features_batch(invalid, [valid]), [{}])
            self.assertEqual(shared_market_features_batch(history, denied), [{}] * len(denied))
            compute.assert_not_called()
            results = shared_market_features_batch(history, [denied[0], subscriber, *denied[1:]])
            self.assertEqual(results[1]["sample_count"].value, 40)
            self.assertEqual(results[:1] + results[2:], [{}] * len(denied))
            compute.assert_called_once()
            captured_row = compute.call_args.args[0][-1]
            last.value["price"] = "1"
            self.assertEqual(captured_row["price"], "100.5")
            with self.assertRaises(TypeError):
                captured_row["price"] = "2"

    def test_optional_quote_freshness_does_not_discard_price_history(self):
        history = self.shared_history(self.market_input())
        subscriber = self.subscriber(history, self.scope)
        fresh = shared_market_features_batch(history, [subscriber])[0]
        self.assertIsNotNone(fresh["spread_pct"].value)
        stale = (self.at - timedelta(seconds=121)).isoformat()
        last = history.samples[-1]
        for changes in ({"ask_at": stale}, {"bid_at": None}, {"ask_at": None}):
            with self.subTest(changes=changes):
                altered = replace(history, samples=history.samples[:-1] +
                                  (replace(last, value=last.value | changes),))
                facts = shared_market_features_batch(altered, [subscriber])[0]
                self.assertEqual(facts["sample_count"].value, 40)
                self.assertEqual(facts["breakout"].value, fresh["breakout"].value)
                self.assertIsNone(facts["spread_pct"].value)
                visible = {key: item.value for key, item in facts.items()}
                self.assertTrue(rule_state({"metric": "breakout", "operator": "==", "value": True},
                                           visible, BASELINE["parameters"]))
                self.assertIsNone(rule_state({"metric": "spread_pct", "operator": "<=", "value": 1},
                                             visible, BASELINE["parameters"]))
                _, codes, _ = risk_gate(self.sample.value, visible, self.risk.value,
                                        self.at, "BUY", require_macd=False)
                self.assertIn("SPREAD_UNKNOWN", codes)
        old_status = replace(history, samples=history.samples[:-1] +
                             (replace(last, value=last.value | {"status_at": stale}),))
        self.assertEqual(shared_market_features_batch(old_status, [subscriber])[0], fresh)

    def test_shared_batch_accepts_closed_bars_at_the_freshness_boundary(self):
        history = self.shared_history(self.market_input())
        as_of = self.at + timedelta(seconds=180)
        bars = tuple(replace(
            sample, available_at=sample.event_time + timedelta(minutes=1),
            value=sample.value | {"price_time_kind": "bar_open"},
        ) for sample in history.samples)
        history = replace(history, samples=bars, as_of=as_of)
        subscriber = self.subscriber(history, self.scope)
        subscriber = replace(subscriber, access=replace(
            subscriber.access, value=replace(subscriber.access.value, expires_at=as_of + timedelta(minutes=1)),
        ))
        self.assertEqual(shared_market_features_batch(history, [subscriber])[0]["sample_count"].value, 40)
        self.assertEqual(shared_market_features_batch(
            replace(history, as_of=as_of + timedelta(microseconds=1)), [subscriber],
        ), [{}])
        wrong_timeframe = replace(history, identity=replace(history.identity, timeframe="5m"))
        wrong_subscriber = replace(subscriber, access=replace(
            subscriber.access, value=replace(subscriber.access.value, identity=wrong_timeframe.identity),
        ))
        self.assertEqual(shared_market_features_batch(wrong_timeframe, [wrong_subscriber]), [{}])

    def test_market_batch_isolates_inputs_and_unavailable_history(self):
        market = self.market_input()
        last = market.samples[-1]

        def with_last(**changes):
            return replace(market, samples=(*market.samples[:-1], replace(last, **changes)))

        variants = [
            replace(market, scope=replace(self.scope, is_test=False)),
            replace(market, scope=replace(self.scope, exchange="NYSE")),
            replace(market, provider="other"), replace(market, feed="other"),
            replace(market, timeframe="5m"), replace(market, revision="revision-2"),
            replace(market, entitlement="delayed-us"), replace(market, feature_version="1.3.1"),
            replace(market, as_of=self.later),
            replace(market, parameters=market.parameters | {"short_period": 6}),
            with_last(source_ids=("different-trade",)),
            with_last(value=last.value | {"price": "100.6"}),
            with_last(available_at=self.at - timedelta(microseconds=1),
                      event_time=self.at - timedelta(microseconds=1),
                      value=last.value | {key: (self.at - timedelta(microseconds=1)).isoformat()
                                          for key in ("event_time", "bid_at", "ask_at", "status_at")}),
        ]
        other_asset = replace(
            market, scope=replace(self.scope, asset_id="asset-2"),
            samples=tuple(replace(row, value=row.value | {"asset_id": "asset-2"}) for row in market.samples),
        )
        variants.append(other_asset)
        unavailable = [
            with_last(available_at=self.later), with_last(source_ids=()),
            with_last(value=last.value | {"bid_at": self.later.isoformat()}),
            with_last(value=last.value | {"price_time_kind": "bar_open"}),
        ]
        with patch("trading_engine_v2.features", wraps=features) as compute:
            original, *results = market_features_batch([market, *variants, *unavailable, market])
            self.assertEqual(compute.call_count, 1 + len(variants))
            self.assertEqual(results[len(variants):-1], [{}] * len(unavailable))
            self.assertEqual(results[-1], original)
            self.assertNotEqual(results[9]["sma_short"], original["sma_short"])
            self.assertEqual(market_features_batch([market]), [original])
            self.assertEqual(compute.call_count, 2 + len(variants))

    def test_market_batch_cache_has_a_fixed_capacity(self):
        market = self.market_input()
        market = replace(market, samples=market.samples[-1:])
        other = replace(market, revision="revision-2")
        with (
            patch("trading_engine_v2._MARKET_BATCH_CACHE_LIMIT", 1),
            patch("trading_engine_v2.features", wraps=features) as compute,
        ):
            first, second, again, second_again = market_features_batch([market, other, market, other])
            self.assertEqual(compute.call_count, 3)
            self.assertEqual(first, again)
            self.assertEqual(second, second_again)

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

    def position_switch_inputs(self):
        entry = self.run_evaluation(EARLY_CATALYST_V1)
        self.assertEqual(entry.action, "BUY")
        scope = replace(self.scope, position_id="position-1")
        held = Evidence({
            "scope_digest": scope.digest, "entry_digest": entry.origin.digest,
            "as_of": self.later.isoformat(), "status": "verified", "position": "held",
            "quantity": "1", "cost_price": "100", "fees_dkk": "1", "fx_to_dkk": "7",
            "unrealized_pnl_dkk": "-2", "native_stop": {"order_id": "stop-1", "price": "95"},
        }, self.later, self.later, ("position-readback",))
        catalog = {
            (0, spec["strategy_id"], spec["version"]): (spec, checksum(spec))
            for spec in (EARLY_CATALYST_V1, BASELINE)
        }
        return dict(
            scope=scope, entry_origin=entry.origin, held=held, effective_at=self.later,
            strategy_id=BASELINE["strategy_id"], version=BASELINE["version"], catalog=catalog,
        )

    def test_position_switch_preserves_facts_and_binds_gated_exit(self):
        inputs = self.position_switch_inputs()
        held = inputs["held"]
        original = held.capture(self.later)
        with patch("trading_engine_v2.risk_gate", wraps=risk_gate) as gate:
            transition = switch_position_strategy(**inputs)
            gate.assert_not_called()
            self.assertIs(switch_position_strategy(**inputs, previous=transition), transition)
            self.assertEqual(held.capture(self.later), original)
            self.assertEqual(json.loads(transition.held_evidence)["value"], original["value"])
            self.assertEqual(transition.entry_origin, inputs["entry_origin"])
            self.assertEqual(transition.prior_strategy[0], EARLY_CATALYST_V1["strategy_id"])
            sample = replace(held, value=self.sample.value | {
                "event_time": self.later.isoformat(), "context": held.value,
            })
            arguments = dict(
                scope=inputs["scope"], as_of=self.later, purpose="exit", sample=sample,
                metrics={"return_3_pct": self.evidence("-1"), "breakdown": self.evidence(True)},
                position_switch=transition,
            )
            exit_decision = self.run_evaluation(**arguments)
            gate.assert_called_once()
            self.assertEqual(exit_decision.action, "SELL")
            self.assertEqual(exit_decision.origin.strategy_id, BASELINE["strategy_id"])
            self.assertEqual(exit_decision.origin.position_switch_digest, transition.digest)
            self.assertNotEqual(exit_decision.origin.digest, transition.entry_origin.digest)
            self.assertEqual(self.run_evaluation(EARLY_CATALYST_V1, **arguments).reasons,
                             ("POSITION_SWITCH_MISMATCH",))
            self.assertEqual(self.run_evaluation(**(arguments | {"as_of": self.at})).reasons,
                             ("POSITION_SWITCH_MISMATCH",))
            other_context = replace(sample, value=sample.value | {
                "context": held.value | {"scope_digest": "another-position"},
            })
            self.assertEqual(self.run_evaluation(**(arguments | {"sample": other_context})).reasons,
                             ("POSITION_SCOPE_MISMATCH",))
            self.assertEqual(self.run_evaluation(**(arguments | {
                "risk": self.evidence(self.risk.value | {"exit_allowed": False}),
            })).reasons, ("EXIT_OUTSIDE_WATCH_SCOPE",))
        held.value["native_stop"]["price"] = "90"
        self.assertEqual(json.loads(transition.held_evidence)["value"]["native_stop"]["price"], "95")

    def test_position_switch_rejects_other_scopes_bad_evidence_and_unknown_versions(self):
        inputs = self.position_switch_inputs()
        held = inputs["held"]
        for change in (
            {"user_id": 8}, {"is_test": False}, {"portfolio_id": 4},
            {"exchange": "NYSE"}, {"asset_id": "other"}, {"trade_cycle_id": "other"},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "POSITION_SCOPE_MISMATCH"):
                switch_position_strategy(**(inputs | {"scope": replace(inputs["scope"], **change)}))
        with self.assertRaisesRegex(ValueError, "POSITION_EVIDENCE_UNVERIFIED"):
            switch_position_strategy(**(inputs | {"scope": replace(inputs["scope"], position_id="other")}))
        for change in (
            {"status": "unknown"}, {"position": "none"}, {"quantity": "Infinity"},
            {"cost_price": "NaN"}, {"entry_digest": "other"}, {"scope_digest": "other"},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "POSITION_EVIDENCE_UNVERIFIED"):
                switch_position_strategy(**(inputs | {"held": replace(held, value=held.value | change)}))
        for overrides in (
            {"effective_at": self.later + timedelta(seconds=301)},
            {"held": replace(held, available_at=self.later + timedelta(seconds=1))},
            {"held": replace(held, source_ids=("",))},
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "POSITION_EVIDENCE_UNVERIFIED"):
                switch_position_strategy(**(inputs | overrides))
        for overrides in (
            {"version": "9.9.9"},
            {"catalog": inputs["catalog"] | {
                (7, BASELINE["strategy_id"], BASELINE["version"]): (BASELINE, "wrong"),
            }},
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "STRATEGY_UNVERIFIED"):
                switch_position_strategy(**(inputs | overrides))

        first = switch_position_strategy(**inputs)
        next_at = self.later + timedelta(seconds=1)
        next_inputs = inputs | {
            "previous": first, "effective_at": next_at, "strategy_id": EARLY_CATALYST_V1["strategy_id"],
        }
        with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_STALE"):
            switch_position_strategy(**next_inputs)
        second = switch_position_strategy(**(next_inputs | {"held": replace(
            held, event_time=next_at, available_at=next_at,
            value=held.value | {"as_of": next_at.isoformat()},
        )}))
        self.assertEqual(second.previous_digest, first.digest)
        self.assertEqual(second.prior_strategy, first.new_strategy)
        self.assertEqual(second.entry_origin, first.entry_origin)

    def position_switch_database(self, *, initialize=True):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "simulation.sqlite"

        def connect():
            connection = sqlite3.connect(path, factory=SimulationConnection)
            connection.row_factory = sqlite3.Row
            return connection

        if initialize:
            setup_test_position_switch_history(connect)
        return connect

    def test_position_switch_history_reopens_and_rejects_stale_writes(self):
        connect = self.position_switch_database()
        inputs = self.position_switch_inputs()
        scope, held = inputs["scope"], inputs["held"]
        first = append_test_position_strategy_switch(connect, **inputs)
        next_at = self.later + timedelta(seconds=1)
        refresh = replace(held, event_time=next_at, available_at=next_at,
                          value=held.value | {"as_of": next_at.isoformat(), "cost_price": "101"})
        next_inputs = inputs | {
            "previous": first, "effective_at": next_at, "held": refresh,
            "strategy_id": EARLY_CATALYST_V1["strategy_id"],
        }
        second = append_test_position_strategy_switch(connect, **next_inputs)
        self.assertEqual(append_test_position_strategy_switch(connect, **inputs), first)
        self.assertEqual(append_test_position_strategy_switch(connect, **next_inputs), second)
        competing = next_inputs | {"held": replace(refresh, value=refresh.value | {"cost_price": "99"})}
        with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_STALE"):
            append_test_position_strategy_switch(connect, **competing)
        setup_test_position_switch_history(connect)
        history = read_test_position_switch_history(connect, scope)
        self.assertEqual(history, (first, second))
        self.assertEqual(history[1].previous_digest, history[0].digest)
        self.assertEqual(history[1].entry_origin, inputs["entry_origin"])
        self.assertEqual(json.loads(history[0].held_evidence)["value"], held.value)
        self.assertEqual(json.loads(history[1].held_evidence)["value"], refresh.value)

    def test_position_switch_history_isolates_scopes_and_detects_corruption(self):
        connect = self.position_switch_database()
        inputs = self.position_switch_inputs()
        scope = inputs["scope"]
        first = append_test_position_strategy_switch(connect, **inputs)
        for change in ({"user_id": 8}, {"portfolio_id": 4}, {"position_id": "other"},
                       {"trade_cycle_id": "other"}):
            other = replace(scope, **change)
            self.assertEqual(read_test_position_switch_history(connect, other), ())
            with self.assertRaisesRegex(ValueError, "POSITION_SCOPE_MISMATCH|POSITION_EVIDENCE_UNVERIFIED"):
                append_test_position_strategy_switch(connect, **(inputs | {"scope": other}))
        for other in (replace(scope, is_test=False), replace(scope, asset_id="other")):
            with self.assertRaisesRegex(ValueError, "POSITION_SCOPE_MISMATCH"):
                read_test_position_switch_history(connect, other)
        with self.assertRaisesRegex(ValueError, "POSITION_SCOPE_MISMATCH"):
            append_test_position_strategy_switch(connect, **(inputs | {"scope": replace(scope, is_test=False)}))
        self.assertEqual(read_test_position_switch_history(connect, scope), (first,))
        with connect() as connection:
            connection.execute("UPDATE test_position_switch_history_v1 SET digest = 'corrupt'")
        with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_HISTORY_INVALID"):
            read_test_position_switch_history(connect, scope)
        with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_HISTORY_INVALID"):
            append_test_position_strategy_switch(connect, **inputs)

    def test_persisted_strategy_drives_simulation_exit_at_effective_time(self):
        connect = self.position_switch_database(initialize=False)
        inputs = self.position_switch_inputs()
        scope, entry, held = inputs["scope"], inputs["entry_origin"], inputs["held"]
        target = BASELINE | {"parameters": BASELINE["parameters"] | {"exit_return_pct": "-0.5"}}
        target_key = (scope.user_id, target["strategy_id"], target["version"])
        catalog = inputs["catalog"] | {target_key: (target, checksum(target))}
        first = switch_position_strategy(**(inputs | {"catalog": catalog}))
        # Seed the accepted #298 schema and row before using the current adapter.
        with connect() as connection:
            connection.execute("""
                CREATE TABLE test_position_switch_history_v1 (
                    user_id INTEGER NOT NULL,
                    portfolio_id INTEGER NOT NULL,
                    position_id TEXT NOT NULL,
                    trade_cycle_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    digest TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, portfolio_id, position_id, trade_cycle_id, sequence),
                    UNIQUE (user_id, portfolio_id, position_id, trade_cycle_id, digest)
                )
            """)
            connection.execute("""
                INSERT INTO test_position_switch_history_v1 VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (scope.user_id, scope.portfolio_id, scope.position_id, scope.trade_cycle_id,
                  1, first.digest, canonical(asdict(first))))
        self.assertEqual(read_test_position_switch_history(connect, scope), (first,))
        future_at = self.later + timedelta(seconds=1)
        future_held = replace(held, event_time=future_at, available_at=future_at,
                              value=held.value | {"as_of": future_at.isoformat(), "cost_price": "101"})
        future = append_test_position_strategy_switch(connect, **(inputs | {
            "catalog": catalog, "effective_at": future_at, "held": future_held, "previous": first,
            "strategy_id": entry.strategy_id,
        }))
        # Each adapter call opens a fresh connection to the same SQLite file.
        self.assertEqual(read_test_position_switch_history(connect, scope), (first, future))
        self.assertEqual(first.entry_origin, entry)
        self.assertEqual(future.entry_origin, entry)
        self.assertEqual(json.loads(first.held_evidence)["value"]["cost_price"], "100")

        def exit_at(at, held_facts=held.value, **overrides):
            sample = replace(held, event_time=at, available_at=at, value=self.sample.value | {
                "event_time": at.isoformat(), "context": held_facts | {"as_of": at.isoformat()},
            })
            arguments = dict(
                connect=connect, scope=scope, snapshot_id="exit", as_of=at, entry_origin=entry,
                catalog=catalog, sample=sample, risk=self.risk,
                expected_head_digest=future.digest,
                metrics={"return_3_pct": self.evidence("-.6"), "breakdown": self.evidence(True)},
            )
            return evaluate_test_position_exit(**(arguments | overrides))

        setup_test_position_switch_history(connect)
        with connect() as connection:
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            self.assertEqual([row[0] for row in tables], ["test_position_switch_history_v1"])

        before = exit_at(self.at)
        self.assertEqual(before.origin.strategy_checksum, entry.strategy_checksum)
        self.assertIsNone(before.origin.position_switch_digest)
        self.assertEqual(before.reasons, ("RULES_NOT_MET",))
        with patch("trading_engine_v2.risk_gate", wraps=risk_gate) as gate:
            after = exit_at(self.later)
            gate.assert_called_once()
            context = gate.call_args.args[0]["context"]
            self.assertEqual(context["cost_price"], "100")
            self.assertEqual(context["entry_digest"], entry.digest)
        self.assertEqual(after.action, "SELL")
        self.assertEqual(after.origin.strategy_checksum, checksum(target))
        self.assertEqual(after.origin.position_switch_digest, first.digest)
        self.assertEqual(exit_at(future_at, future_held.value).origin.position_switch_digest,
                         future.digest)
        blocked = exit_at(self.later, risk=self.evidence(self.risk.value | {"exit_allowed": False}))
        self.assertIsNone(blocked.action)
        self.assertEqual(blocked.reasons, ("EXIT_OUTSIDE_WATCH_SCOPE",))

        for other_scope in (replace(scope, user_id=8), replace(scope, position_id="other"),
                            replace(scope, is_test=False)):
            with self.subTest(scope=other_scope), self.assertRaisesRegex(ValueError, "POSITION_SCOPE_MISMATCH"):
                exit_at(self.at, scope=other_scope)
        with self.assertRaisesRegex(ValueError, "POSITION_SCOPE_MISMATCH"):
            exit_at(self.later, held.value | {"entry_digest": "other"})
        with self.assertRaisesRegex(ValueError, "STRATEGY_UNVERIFIED"):
            exit_at(self.later, catalog=inputs["catalog"])
        with self.assertRaisesRegex(ValueError, "STRATEGY_UNVERIFIED"):
            exit_at(self.later, catalog={})
        # The independent head must detect valid-looking prefixes and empty
        # chains, even when evaluating before the first recorded switch.
        for sql in ("DELETE FROM test_position_switch_history_v1 WHERE sequence = 2",
                    "DELETE FROM test_position_switch_history_v1"):
            with connect() as connection:
                connection.execute(sql)
            with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_HISTORY_INVALID"):
                exit_at(self.at)
            with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_HISTORY_INVALID"):
                exit_at(self.later)
            with connect() as connection:
                connection.execute("DELETE FROM test_position_switch_history_v1")
                for seq, item in enumerate((first, future), 1):
                    connection.execute("""
                        INSERT INTO test_position_switch_history_v1 VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (scope.user_id, scope.portfolio_id, scope.position_id, scope.trade_cycle_id,
                          seq, item.digest, canonical(asdict(item))))
        # Explicit, independently attested empty history is still valid.
        empty_connect = self.position_switch_database()
        self.assertEqual(exit_at(self.at, connect=empty_connect, expected_head_digest=None).origin.strategy_checksum,
                         entry.strategy_checksum)
        with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_HISTORY_INVALID"):
            exit_at(self.at, connect=empty_connect, expected_head_digest=first.digest)
        with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_HISTORY_INVALID"):
            exit_at(self.at, expected_head_digest=None)

        # A missing predecessor leaves a detectable gap in the existing journal.
        with connect() as connection:
            connection.execute("DELETE FROM test_position_switch_history_v1 WHERE sequence = 1")
        with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_HISTORY_INVALID"):
            exit_at(self.later)
        with connect() as connection:
            connection.execute("""
                INSERT INTO test_position_switch_history_v1 VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (scope.user_id, scope.portfolio_id, scope.position_id, scope.trade_cycle_id,
                  1, first.digest, canonical(asdict(first))))
        with connect() as connection:
            connection.execute("UPDATE test_position_switch_history_v1 SET digest = 'corrupt' WHERE sequence = 2")
        with self.assertRaisesRegex(ValueError, "POSITION_SWITCH_HISTORY_INVALID"):
            exit_at(self.at)


if __name__ == "__main__":
    unittest.main()
