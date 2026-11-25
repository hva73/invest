"""Isolated, simulation-only decision and evidence interface for #273."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Literal


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Instrument:
    exchange: str
    asset_id: str


@dataclass(frozen=True)
class StrategyKey:
    strategy_id: str
    version: str


@dataclass(frozen=True)
class Evidence:
    name: str
    passed: bool
    observed_at: datetime
    source_ids: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        if isinstance(self.source_ids, str):
            raise ValueError("Source references must be a sequence of IDs")
        sources = tuple(self.source_ids)
        if (type(self.passed) is not bool or not sources
                or any(not isinstance(source, str) or not source for source in sources)):
            raise ValueError("Evidence requires a boolean and source references")
        object.__setattr__(self, "source_ids", sources)


@dataclass(frozen=True)
class Provenance:
    candidate_id: str | None = None
    watch_id: str | None = None
    trade_cycle_id: str | None = None
    portfolio_id: str | None = None
    position_id: str | None = None
    entry_origin: str | None = None
    exit_origin: str | None = None
    intent_id: str | None = None
    order_id: str | None = None
    fill_id: str | None = None


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    instrument: Instrument
    as_of: datetime
    evidence: tuple[Evidence, ...]
    purpose: Literal["entry", "exit"] = "entry"
    provenance: Provenance = Provenance()

    def __post_init__(self):
        object.__setattr__(self, "as_of", _utc(self.as_of))
        facts = tuple(self.evidence)
        if any(not isinstance(fact, Evidence) for fact in facts):
            raise ValueError("Snapshot evidence must contain Evidence records")
        object.__setattr__(self, "evidence", facts)
        if not all((self.snapshot_id, self.instrument.asset_id, self.instrument.exchange)):
            raise ValueError("Snapshot and instrument identifiers are required")
        if self.purpose not in ("entry", "exit"):
            raise ValueError("Unknown evaluation purpose")
        if self.provenance.position_id and not self.provenance.portfolio_id:
            raise ValueError("Position references require a portfolio")
        if len({fact.name for fact in facts}) != len(facts):
            raise ValueError("Evidence names must be unique within a snapshot")


@dataclass(frozen=True)
class DecisionIdentity:
    instrument: Instrument
    strategy: StrategyKey
    as_of: datetime
    snapshot_id: str
    purpose: Literal["entry", "exit"]


class Outcome(str, Enum):
    OBSERVATION = "observation"
    BLOCKED = "blocked"
    DECISION = "decision"


@dataclass(frozen=True)
class Reason:
    code: str
    inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    identity: DecisionIdentity
    outcome: Outcome
    reasons: tuple[Reason, ...]
    evidence: tuple[Evidence, ...]
    provenance: Provenance
    action: Literal["simulated_entry"] | None = None


@dataclass(frozen=True)
class Profile:
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    observation_code: str


MOMENTUM = StrategyKey("escape_momentum", "0.1.0-sim")
EARLY_CATALYST = StrategyKey("escape_early_catalyst", "0.1.0-sim")
_RISK = "simulated_risk_passed"
REGISTRY = MappingProxyType({
    MOMENTUM: Profile(
        (_RISK, "momentum_confirmed", "macd_confirmed"),
        (),
        "momentum_conditions_unmet",
    ),
    EARLY_CATALYST: Profile(
        (_RISK, "catalyst_verified", "early_reaction_confirmed"),
        ("macd_confirmed",),
        "catalyst_conditions_unmet",
    ),
})


def evaluate(snapshot: Snapshot, strategy: StrategyKey) -> Decision:
    """Evaluate named synthetic predicates with no clock, I/O or execution hook."""
    identity = DecisionIdentity(
        snapshot.instrument, strategy, snapshot.as_of, snapshot.snapshot_id, snapshot.purpose
    )
    profile = REGISTRY.get(strategy)
    if profile is None:
        return Decision(identity, Outcome.BLOCKED, (Reason("unknown_strategy_version"),),
                        (), snapshot.provenance)
    if snapshot.purpose == "exit":
        return Decision(identity, Outcome.BLOCKED, (Reason("unsupported_exit_evaluation"),),
                        (), snapshot.provenance)

    facts = {fact.name: fact for fact in snapshot.evidence}
    required = profile.required_inputs
    declared = required + profile.optional_inputs
    evidence = tuple(facts[name] for name in declared if name in facts)
    blockers = tuple(
        Reason("missing_required_input", (name,)) if name not in facts
        else Reason("future_required_input", (name,))
        for name in required
        if name not in facts or facts[name].observed_at > snapshot.as_of
    )
    if _RISK in facts and facts[_RISK].observed_at <= snapshot.as_of and not facts[_RISK].passed:
        blockers += (Reason("simulated_risk_blocked", (_RISK,)),)
    if blockers:
        return Decision(identity, Outcome.BLOCKED, blockers, evidence, snapshot.provenance)

    unmet = tuple(name for name in required if not facts[name].passed)
    if unmet:
        return Decision(identity, Outcome.OBSERVATION, (Reason(profile.observation_code, unmet),),
                        evidence, snapshot.provenance)
    return Decision(identity, Outcome.DECISION, (Reason("simulated_conditions_met", required),),
                    evidence, snapshot.provenance, action="simulated_entry")
