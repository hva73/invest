"""Pure, simulation-only evaluation of versioned HOT WATCH rules."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Literal

from hotwatch_contract import checksum
from hotwatch_strategy import exit_context_key, risk_gate, rule_state, validate_strategy
from report_validation import stamp


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Scope:
    user_id: int
    is_test: bool
    exchange: str
    asset_id: str
    portfolio_id: int
    candidate_id: str
    watch_id: str
    trade_cycle_id: str | None = None
    position_id: str | None = None

    @property
    def digest(self) -> str:
        return checksum(asdict(self))


@dataclass(frozen=True)
class Evidence:
    value: object
    event_time: datetime
    available_at: datetime
    source_ids: tuple[str, ...]

    def visible(self, as_of: datetime) -> bool:
        return bool(self.source_ids) and _utc(self.event_time) <= _utc(self.available_at) <= as_of

    def capture(self, as_of: datetime) -> dict | None:
        if not self.visible(as_of):
            return None
        return {
            "value": deepcopy(self.value),
            "event_time": _utc(self.event_time).isoformat(),
            "available_at": _utc(self.available_at).isoformat(),
            "source_ids": tuple(self.source_ids),
        }


@dataclass(frozen=True)
class DecisionOrigin:
    scope_digest: str
    snapshot_id: str
    as_of: str
    purpose: Literal["entry", "exit"]
    strategy_id: str
    strategy_version: str
    strategy_checksum: str
    snapshot_checksum: str | None = None

    @property
    def digest(self) -> str:
        return checksum(asdict(self))


@dataclass(frozen=True)
class Decision:
    origin: DecisionOrigin
    outcome: Literal["observation", "blocked", "decision"]
    reasons: tuple[str, ...] = ()
    action: Literal["BUY", "SELL", "REDUCE"] | None = None


@dataclass(frozen=True)
class VerifiedExecution:
    """Linkage supplied by an authoritative readback, separate from evaluation."""

    scope_digest: str
    decision_digest: str
    order_id: str
    source_ids: tuple[str, ...]
    fill_id: str | None = None

    def links(self, origin: DecisionOrigin) -> bool:
        return bool(self.order_id and self.source_ids and origin.snapshot_checksum
                    and self.scope_digest == origin.scope_digest
                    and self.decision_digest == origin.digest)


def evaluate(
    scope: Scope,
    snapshot_id: str,
    as_of: datetime,
    purpose: Literal["entry", "exit"],
    spec: dict,
    spec_checksum: str,
    sample: Evidence,
    metrics: dict[str, Evidence],
    risk: Evidence,
) -> Decision:
    """Use a caller-resolved strategy version and timestamped HOT WATCH inputs."""
    as_of = _utc(as_of)
    identity = spec if isinstance(spec, dict) else {}
    origin = DecisionOrigin(
        scope.digest, snapshot_id, as_of.isoformat(), purpose,
        identity.get("strategy_id", ""), identity.get("version", ""), spec_checksum,
    )
    try:
        captured_sample = sample.capture(as_of)
        sample_error = "SAMPLE_UNAVAILABLE"
        if captured_sample is not None:
            observation = captured_sample["value"]
            event_time = stamp(observation["event_time"])
            context = observation["context"]
            sample_times = [observation.get(key) for key in ("bid_at", "ask_at", "status_at")]
            sample_error = None
            if (observation["asset_id"] != scope.asset_id
                    or event_time != _utc(sample.event_time)):
                sample_error = "SAMPLE_IDENTITY_MISMATCH"
            available_at = _utc(sample.available_at)
            if event_time > available_at or any(
                value and stamp(value) > available_at
                for value in (*sample_times, context.get("as_of"))
            ):
                captured_sample = None
                sample_error = sample_error or "SAMPLE_UNAVAILABLE"
        captured_metrics = {
            name: captured for name, fact in metrics.items()
            if (captured := fact.capture(as_of)) is not None
        }
        captured_risk = risk.capture(as_of)
        origin = replace(origin, snapshot_checksum=checksum({
            "sample": captured_sample, "metrics": captured_metrics, "risk": captured_risk,
        }))
        if validate_strategy(spec) or checksum(spec) != spec_checksum:
            return Decision(origin, "blocked", ("STRATEGY_UNVERIFIED",))
        if purpose not in ("entry", "exit") or not (
            scope.portfolio_id and scope.asset_id and scope.exchange
        ):
            return Decision(origin, "blocked", ("SCOPE_INVALID",))
        if sample_error:
            return Decision(origin, "blocked", (sample_error,))
        position = context["position"]
        expected_position = "held" if purpose == "exit" else "none"
        if position != expected_position:
            return Decision(origin, "blocked", ("POSITION_SCOPE_MISMATCH",))
        if purpose == "exit" and (
            not scope.position_id or not exit_context_key(context, origin.scope_digest)
        ):
            return Decision(origin, "blocked", ("POSITION_SCOPE_MISMATCH",))

        visible = {name: fact["value"] for name, fact in captured_metrics.items()}
        parameters = spec["parameters"]
        early = spec["schema_version"] == 2
        states = [rule_state(spec[f"{purpose}_rules"], visible, parameters)]
        if purpose == "entry" and early:
            states.append(rule_state(spec["watch_rules"], visible, parameters))
            if parameters["use_macd_confirmation"]:
                states.append(rule_state(
                    {"metric": "macd_histogram", "operator": ">", "value": "0"},
                    visible, parameters,
                ))
        if False in states:
            return Decision(origin, "observation", ("RULES_NOT_MET",))
        if None in states:
            return Decision(origin, "blocked", ("RULE_INPUT_UNAVAILABLE",))
        if captured_risk is None:
            return Decision(origin, "blocked", ("RISK_INPUT_UNAVAILABLE",))

        action = "BUY"
        if purpose == "exit":
            action = "REDUCE" if parameters["allow_reduce"] else "SELL"
        limits = dict(captured_risk["value"])
        permission = f"{purpose}_allowed"
        limits[permission] = limits.get(permission) is True
        signal, codes, critical = risk_gate(
            observation, visible, limits, as_of, action, require_macd=not early,
        )
        if signal not in ("BUY", "SELL", "REDUCE") or codes:
            return Decision(origin, "blocked", tuple(codes) or ("RISK_GATE_BLOCKED",))
        return Decision(origin, "decision", tuple(critical), signal)
    except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
        return Decision(origin, "blocked", ("INVALID_INPUT",))
