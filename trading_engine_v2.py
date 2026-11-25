"""Simulation-only evaluation of versioned HOT WATCH rules."""
from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from json import loads
from math import isfinite
from types import MappingProxyType
from typing import Literal

from hotwatch_contract import GLOBAL_RISK, canonical, checksum
from hotwatch_features import features
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
class MarketFeatureInput:
    scope: Scope
    as_of: datetime
    samples: tuple[Evidence, ...]
    provider: str
    feed: str
    timeframe: str
    revision: str
    entitlement: str
    feature_version: str
    parameters: dict


@dataclass(frozen=True)
class MarketIdentity:
    exchange: str
    asset_id: str
    currency: str
    provider: str
    feed: str
    timeframe: str
    revision: str
    entitlement: str
    feature_version: str
    is_test: bool


@dataclass(frozen=True)
class MarketHistory:
    identity: MarketIdentity
    as_of: datetime
    samples: tuple[Evidence, ...]


@dataclass(frozen=True)
class MarketAccess:
    """Value of locally verified entitlement evidence supplied by the caller."""

    user_id: int
    identity: MarketIdentity
    expires_at: datetime


@dataclass(frozen=True)
class MarketSubscriber:
    scope: Scope
    access: Evidence
    parameters: dict


# Fields read by features(), plus timestamps that establish availability.
_MARKET_FIELDS = (
    "source", "asset_id", "currency", "venue", "session_key", "market_status",
    "feed_type", "interval_s", "price_time_kind", "verification", "event_time",
    "price", "high", "low", "close", "bid", "ask", "volume", "volume_type",
    "bid_at", "ask_at", "status_at",
)
_FEATURE_PERIODS = ("short_period", "long_period", "rsi_period", "atr_period", "breakout_window")
_MARKET_BATCH_CACHE_LIMIT = 128


_INVALID_MARKET_INPUT = (AttributeError, KeyError, TypeError, ValueError, ArithmeticError)


def _feature_parameters(parameters):
    periods = {name: int(parameters[name]) for name in _FEATURE_PERIODS}
    periods["momentum_window_minutes"] = int(parameters.get("momentum_window_minutes", 3))
    if min(periods.values()) < 1:
        raise ValueError("Feature periods must be positive")
    return periods


def _has_sources(evidence):
    return (bool(evidence.source_ids) and all(isinstance(source, str) and source.strip() for source in evidence.source_ids))


def _market_rows(samples, as_of, asset_id, identity=None):
    rows, provenance = [], []
    previous = bar_interval = None
    for sample in samples:
        event, available = _utc(sample.event_time), _utc(sample.available_at)
        row = {name: sample.value[name] for name in _MARKET_FIELDS if name in sample.value}
        end = event
        if row.get("price_time_kind") == "bar_open":
            if row["interval_s"] <= 0:
                raise ValueError("Invalid market bar interval")
            end += timedelta(seconds=row["interval_s"])
        if (not _has_sources(sample) or not end <= available <= as_of
                or row["asset_id"] != asset_id or stamp(row["event_time"]) != event
                or any(row.get(name) and stamp(row[name]) > available
                       for name in ("bid_at", "ask_at", "status_at"))):
            raise ValueError("Market feature evidence unavailable")
        if identity is not None:
            price = Decimal(str(row["price"]))
            if (not isinstance(sample.source_ids, tuple)
                    or any(type(value) not in (str, int, float, bool, type(None))
                           or (type(value) is float and not isfinite(value)) for value in row.values())
                    or row["verification"] != "verified" or sample.value.get("error_code") is not None
                    or (row["source"], row["feed_type"], row["venue"], row["currency"])
                    != (identity.provider, identity.feed, identity.exchange, identity.currency)
                    or row.get("price_time_kind") not in ("trade", "bar_open", "snapshot")
                    or (previous is not None and event <= previous)
                    or not price.is_finite() or price <= 0):
                raise ValueError("Unverified or mismatched market observation")
            if row["price_time_kind"] == "bar_open":
                if bar_interval is None:
                    unit_seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}
                    bar_interval = int(identity.timeframe[:-1]) * unit_seconds[identity.timeframe[-1]]
                if type(row["interval_s"]) is not int or bar_interval != row["interval_s"]:
                    raise ValueError("Market bar timeframe mismatch")
        rows.append(row)
        provenance.append((event, available, sample.source_ids))
        previous = event
    if not rows:
        raise ValueError("Market history is empty")
    if identity is not None:
        oldest = as_of - timedelta(seconds=GLOBAL_RISK["max_quote_age_s"])
        if end < oldest:
            raise ValueError("Market history is stale")
        # Historical status groups observations; it is not current execution authority.
        # A fresh price history can support price-only rules without an executable quote.
        if not all(row.get(name) and stamp(row[name]) >= oldest
                   for name in ("bid_at", "ask_at")):
            row["bid"] = row["ask"] = None
    return rows, provenance


def _market_facts(rows, parameters, event, available, sources):
    return {name: Evidence(value, event, available, sources)
            for name, value in features(rows, parameters).items()}


def _market_provenance(provenance):
    return (max(event for event, _, _ in provenance),
            max(available for _, available, _ in provenance),
            tuple(dict.fromkeys(source for _, _, sources in provenance for source in sources)))


def market_features_batch(requests: Iterable[MarketFeatureInput]) -> list[dict[str, Evidence]]:
    """Compute market-only facts for one simulation batch in request order."""
    cache: dict[str, dict[str, Evidence]] = {}
    results = []
    for request in requests:
        try:
            as_of = _utc(request.as_of)
            identity = (request.scope.exchange, request.scope.asset_id, request.provider,
                        request.feed, request.timeframe, request.revision, request.entitlement,
                        request.feature_version)
            if (not all(isinstance(value, str) and value.strip() for value in identity)
                    or type(request.scope.is_test) is not bool):
                raise ValueError("Market feature identity is required")
            parameters = _feature_parameters(request.parameters)
            rows, provenance = _market_rows(request.samples, as_of, request.scope.asset_id)
            key = checksum((identity, request.scope.is_test, as_of.isoformat(), parameters, rows,
                            [(event.isoformat(), available.isoformat(), sources)
                             for event, available, sources in provenance]))
            facts = cache.get(key)
            if facts is None:
                facts = _market_facts(rows, parameters, *_market_provenance(provenance))
                if len(cache) < _MARKET_BATCH_CACHE_LIMIT:
                    cache[key] = facts
        except _INVALID_MARKET_INPUT:
            facts = {}
        results.append(dict(facts))
    return results


def shared_market_features_batch(
    history: MarketHistory, subscribers: Iterable[MarketSubscriber],
) -> list[dict[str, Evidence]]:
    """Resolve one local market capture and fan out features to its entitled subscribers."""
    subscribers = tuple(subscribers)
    results = [{} for _ in subscribers]
    try:
        identity = history.identity
        as_of = _utc(history.as_of)
        fields = asdict(identity)
        fields.pop("is_test")
        if (not all(isinstance(value, str) and value.strip() for value in fields.values())
                or identity.is_test is not True or identity.provider not in ("eodhd", "pluto")):
            raise ValueError("Verified simulation market identity is required")
        rows, provenance = _market_rows(history.samples, as_of, identity.asset_id, identity)
        capture = tuple(MappingProxyType(row) for row in rows)
        metadata = _market_provenance(provenance)
    except _INVALID_MARKET_INPUT:
        return results

    groups = {}
    for index, subscriber in enumerate(subscribers):
        try:
            scope, access = subscriber.scope, subscriber.access
            grant = access.value
            if (scope.is_test is not identity.is_test
                    or (scope.exchange, scope.asset_id) != (identity.exchange, identity.asset_id)
                    or not isinstance(grant, MarketAccess)
                    or type(scope.user_id) is not int or scope.user_id <= 0
                    or type(grant.user_id) is not int or grant.user_id != scope.user_id
                    or grant.identity.is_test is not identity.is_test or grant.identity != identity
                    or not isinstance(access.source_ids, tuple) or not _has_sources(access)
                    or not access.visible(as_of)
                    or _utc(grant.expires_at) <= as_of):
                continue
            key = tuple(_feature_parameters(subscriber.parameters).items())
            groups.setdefault(key, []).append(index)
        except _INVALID_MARKET_INPUT:
            continue

    for key, indexes in groups.items():
        try:
            facts = _market_facts(capture, dict(key), *metadata)
        except _INVALID_MARKET_INPUT:
            continue
        for index in indexes:
            results[index] = dict(facts)
    return results


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
    position_switch_digest: str | None = None

    @property
    def digest(self) -> str:
        fields = asdict(self)
        if self.position_switch_digest is None:
            del fields["position_switch_digest"]
        return checksum(fields)


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


@dataclass(frozen=True)
class PositionStrategySwitch:
    scope_digest: str
    entry_origin: DecisionOrigin
    prior_strategy: tuple[str, str, str]
    new_strategy: tuple[str, str, str]
    effective_at: str
    observed_at: str
    held_evidence: str
    previous_digest: str | None

    @property
    def digest(self) -> str:
        return checksum(asdict(self))


def switch_position_strategy(
    scope: Scope,
    entry_origin: DecisionOrigin,
    held: Evidence,
    effective_at: datetime,
    strategy_id: str,
    version: str,
    catalog: dict[tuple[int, str, str], tuple[dict, str]],
    previous: PositionStrategySwitch | None = None,
) -> PositionStrategySwitch:
    """Return an immutable simulation transition using caller-verified readback."""
    at = _utc(effective_at)
    scope_digest = scope.digest
    if (
        type(scope.user_id) is not int or scope.user_id <= 0 or scope.is_test is not True
        or type(scope.portfolio_id) is not int or scope.portfolio_id <= 0
        or not all((scope.exchange, scope.asset_id, scope.position_id, scope.trade_cycle_id))
        or entry_origin.purpose != "entry" or not entry_origin.snapshot_checksum
        or entry_origin.scope_digest not in (
            scope_digest, replace(scope, position_id=None).digest,
        )
        or (previous is not None and (
            previous.scope_digest != scope_digest or previous.entry_origin != entry_origin
        ))
    ):
        raise ValueError("POSITION_SCOPE_MISMATCH")

    try:
        captured = held.capture(at)
        facts = captured["value"]
        observed = stamp(facts["as_of"])
        quantity = Decimal(facts["quantity"])
        cost = Decimal(facts["cost_price"]) if facts.get("cost_price") is not None else None
        valid = (
            facts["scope_digest"] == scope_digest
            and facts["entry_digest"] == entry_origin.digest
            and exit_context_key(facts, scope_digest)
            and quantity.is_finite() and (cost is None or (cost.is_finite() and cost >= 0))
            and all(isinstance(source, str) and source.strip() for source in held.source_ids)
            and stamp(entry_origin.as_of) <= observed == _utc(held.event_time)
            and (at - observed).total_seconds() <= 300
        )
        snapshot = canonical(captured)
    except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
        valid = False
    if not valid:
        raise ValueError("POSITION_EVIDENCE_UNVERIFIED")

    def resolve(sid, ver):
        record = catalog.get((scope.user_id, sid, ver), catalog.get((0, sid, ver)))
        if isinstance(record, tuple) and len(record) == 2:
            spec, digest = record
            try:
                if (not validate_strategy(spec) and spec["strategy_id"] == sid
                        and spec["version"] == ver and checksum(spec) == digest):
                    return sid, ver, digest
            except (TypeError, ValueError):
                pass
        raise ValueError("STRATEGY_UNVERIFIED")

    target = resolve(strategy_id, version)
    prior = (entry_origin.strategy_id, entry_origin.strategy_version,
             entry_origin.strategy_checksum) if previous is None else previous.new_strategy
    if previous is not None:
        previous_at = stamp(previous.effective_at)
        if at == previous_at and target == prior and snapshot == previous.held_evidence:
            return previous
        if at <= previous_at or observed < previous_at or observed <= stamp(previous.observed_at):
            raise ValueError("POSITION_SWITCH_STALE")
    if resolve(*prior[:2]) != prior:
        raise ValueError("STRATEGY_UNVERIFIED")
    if target == prior:
        raise ValueError("POSITION_STRATEGY_UNCHANGED")
    return PositionStrategySwitch(
        scope_digest, entry_origin, prior, target, at.isoformat(), observed.isoformat(), snapshot,
        previous.digest if previous is not None else None,
    )


def setup_test_position_switch_history(connect):
    """Explicitly initialize the v1 journal on the caller's simulation database."""
    with connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS test_position_switch_history_v1 (
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


def _position_switch_chain_key(scope):
    if (scope.is_test is not True or type(scope.user_id) is not int or scope.user_id <= 0
            or type(scope.portfolio_id) is not int or scope.portfolio_id <= 0
            or not all(isinstance(value, str) and value.strip() for value in (
                scope.position_id, scope.trade_cycle_id, scope.exchange, scope.asset_id,
            ))):
        raise ValueError("POSITION_SCOPE_MISMATCH")
    return scope.user_id, scope.portfolio_id, scope.position_id, scope.trade_cycle_id


def _read_position_switch_chain(connection, scope, key):
    history = []
    scope_digest = scope.digest
    rows = connection.execute("""
        SELECT sequence, digest, payload FROM test_position_switch_history_v1
        WHERE user_id = ? AND portfolio_id = ? AND position_id = ? AND trade_cycle_id = ?
        ORDER BY sequence
    """, key)
    for sequence, digest, payload in rows:
        try:
            fields = loads(payload)
            origin = DecisionOrigin(**fields.pop("entry_origin"))
            for name in ("prior_strategy", "new_strategy"):
                fields[name] = tuple(fields[name])
            transition = PositionStrategySwitch(entry_origin=origin, **fields)
            previous = history[-1] if history else None
            linked = (
                transition.previous_digest == previous.digest
                and origin == previous.entry_origin
                and transition.prior_strategy == previous.new_strategy
                and stamp(transition.effective_at) > stamp(previous.effective_at)
                and stamp(transition.observed_at) >= stamp(previous.effective_at)
                and stamp(transition.observed_at) > stamp(previous.observed_at)
            ) if previous else (
                transition.previous_digest is None
                and transition.prior_strategy == (
                    origin.strategy_id, origin.strategy_version, origin.strategy_checksum,
                )
            )
            if (sequence != len(history) + 1 or not linked
                    or canonical(asdict(transition)) != payload or transition.digest != digest):
                raise ValueError("Invalid journal row")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("POSITION_SWITCH_HISTORY_INVALID") from exc
        if transition.scope_digest != scope_digest:
            raise ValueError("POSITION_SCOPE_MISMATCH")
        history.append(transition)
    return tuple(history)


def read_test_position_switch_history(connect, scope: Scope) -> tuple[PositionStrategySwitch, ...]:
    """Read the verified chain for a caller-authorized simulation scope."""
    key = _position_switch_chain_key(scope)
    with connect() as connection:
        return _read_position_switch_chain(connection, scope, key)


def append_test_position_strategy_switch(
    connect,
    scope: Scope,
    entry_origin: DecisionOrigin,
    held: Evidence,
    effective_at: datetime,
    strategy_id: str,
    version: str,
    catalog: dict[tuple[int, str, str], tuple[dict, str]],
    previous: PositionStrategySwitch | None = None,
) -> PositionStrategySwitch:
    """Validate and append using the predecessor expected by the caller."""
    key = _position_switch_chain_key(scope)
    transition = switch_position_strategy(
        scope, entry_origin, held, effective_at, strategy_id, version, catalog, previous,
    )
    digest = transition.digest
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        history = _read_position_switch_chain(connection, scope, key)
        if transition in history:
            return transition
        head = history[-1] if history else None
        if head != previous or transition is previous:
            raise ValueError("POSITION_SWITCH_STALE")
        connection.execute("""
            INSERT INTO test_position_switch_history_v1
                (user_id, portfolio_id, position_id, trade_cycle_id, sequence, digest, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (*key, len(history) + 1, digest, canonical(asdict(transition))))
    return transition


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
    *,
    position_switch: PositionStrategySwitch | None = None,
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
        if position_switch is not None:
            if (
                purpose != "exit" or scope.is_test is not True
                or position_switch.scope_digest != scope.digest
                or as_of < stamp(position_switch.effective_at)
                or position_switch.new_strategy != (
                    origin.strategy_id, origin.strategy_version, origin.strategy_checksum,
                )
            ):
                return Decision(origin, "blocked", ("POSITION_SWITCH_MISMATCH",))
            origin = replace(origin, position_switch_digest=position_switch.digest)
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
        if position_switch is not None and (
            context.get("scope_digest") != scope.digest
            or context.get("entry_digest") != position_switch.entry_origin.digest
            or stamp(context["as_of"]) < stamp(position_switch.effective_at)
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
