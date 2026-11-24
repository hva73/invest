"""Offline diagnostic for peak incremental release storage, in bytes."""

from dataclasses import dataclass, fields
from typing import Optional, Tuple


@dataclass(frozen=True)
class SpaceEvidence:
    """All free space is measured before adding the budgeted allocations.

    Supply conservative account quota and filesystem measurements independently.
    Budget incremental copies of old code/keys, each simultaneously retained
    candidate staging set, and WAL/journal/sidecars. These, allocation overhead
    and reserved safety margin are charged in every phase. Use an explicit zero
    for a verified absent cost. The model assumes the allocations share the
    measured account and filesystem.

    Supply archive_overhead_bytes for the default uncompressed bound, or
    proven_archive_upper_bound_bytes with an archive_bound_evidence reference.
    raw_archive_overlap=False requires a reference to evidence that establishes
    the two allocations are disjoint throughout the release.
    """

    account_free_bytes: Optional[int] = None
    filesystem_free_bytes: Optional[int] = None
    raw_locked_db_snapshot_bytes: Optional[int] = None
    archive_overhead_bytes: Optional[int] = None
    proven_archive_upper_bound_bytes: Optional[int] = None
    old_code_and_keys_bytes: Optional[int] = None
    candidate_staging_sets_bytes: Optional[Tuple[int, ...]] = None
    wal_journal_sidecars_bytes: Optional[int] = None
    allocation_overhead_bytes: Optional[int] = None
    safety_margin_bytes: Optional[int] = None
    raw_archive_overlap: Optional[bool] = None
    non_overlap_evidence: Optional[str] = None
    archive_bound_evidence: Optional[str] = None


@dataclass(frozen=True)
class PhaseBudget:
    name: str
    known_budgeted_bytes: int
    peak_bytes: Optional[int]
    account_headroom_bytes: Optional[int]
    filesystem_headroom_bytes: Optional[int]


@dataclass(frozen=True)
class SpaceBudget:
    phases: Tuple[PhaseBudget, ...]
    peak_bytes: Optional[int]
    blockers: Tuple[str, ...]
    outcome: str


def _valid_bytes(value):
    return type(value) is int and value >= 0


def _has_reference(value):
    return isinstance(value, str) and bool(value.strip())


def calculate_space_budget(evidence: SpaceEvidence) -> SpaceBudget:
    """Compute phase budgets without inspecting or changing any external state."""
    blockers = []
    sizes = {}
    optional_sizes = {"archive_overhead_bytes", "proven_archive_upper_bound_bytes"}
    special_fields = {
        "candidate_staging_sets_bytes", "raw_archive_overlap",
        "non_overlap_evidence", "archive_bound_evidence",
    }
    for field in fields(SpaceEvidence):
        name = field.name
        if name in special_fields:
            continue
        value = getattr(evidence, name)
        if _valid_bytes(value):
            sizes[name] = value
        elif value is not None:
            blockers.append(f"invalid:{name}")
        elif name not in optional_sizes:
            blockers.append(f"missing:{name}")

    staging = evidence.candidate_staging_sets_bytes
    staging_total = None
    if staging is None:
        blockers.append("missing:candidate_staging_sets_bytes")
    elif type(staging) is tuple and staging and all(map(_valid_bytes, staging)):
        staging_total = sum(staging)
    else:
        blockers.append("invalid:candidate_staging_sets_bytes")

    raw = sizes.get("raw_locked_db_snapshot_bytes")
    archive = sizes.get("proven_archive_upper_bound_bytes")
    overhead = sizes.get("archive_overhead_bytes")
    if evidence.proven_archive_upper_bound_bytes is None:
        if evidence.archive_overhead_bytes is None:
            blockers.append("missing:archive_bound_evidence")
        if raw is not None and overhead is not None:
            archive = raw + overhead
    elif archive is not None and not _has_reference(evidence.archive_bound_evidence):
        blockers.append("missing:archive_bound_evidence")
        archive = None

    overlap = evidence.raw_archive_overlap
    disjoint = False
    if overlap is None:
        blockers.append("missing:raw_archive_overlap")
    elif type(overlap) is not bool:
        blockers.append("invalid:raw_archive_overlap")
    elif not overlap:
        disjoint = _has_reference(evidence.non_overlap_evidence)
        if not disjoint:
            blockers.append("missing:non_overlap_evidence")

    common = (
        sizes.get("old_code_and_keys_bytes"),
        staging_total,
        sizes.get("wal_journal_sidecars_bytes"),
        sizes.get("allocation_overhead_bytes"),
        sizes.get("safety_margin_bytes"),
    )
    phase_inputs = [("raw_snapshot", (raw,)), ("archive", (archive,))]
    if not disjoint:
        phase_inputs.append(("raw_snapshot_and_archive", (raw, archive)))

    account_free = sizes.get("account_free_bytes")
    filesystem_free = sizes.get("filesystem_free_bytes")
    phases = []
    for name, copies in phase_inputs:
        costs = common + copies
        subtotal = sum(cost for cost in costs if cost is not None)
        peak = subtotal if None not in costs else None
        for limit_name, free in (("account", account_free), ("filesystem", filesystem_free)):
            if free is not None and subtotal > free:
                blockers.append(f"insufficient_{limit_name}_space:{name}")
        phases.append(PhaseBudget(
            name,
            subtotal,
            peak,
            account_free - peak if account_free is not None and peak is not None else None,
            filesystem_free - peak if filesystem_free is not None and peak is not None else None,
        ))

    peak = None
    if all(phase.peak_bytes is not None for phase in phases):
        peak = max(phase.peak_bytes for phase in phases)
    return SpaceBudget(
        tuple(phases), peak, tuple(blockers),
        "diagnostic_blocked" if blockers else "diagnostic_fits",
    )
