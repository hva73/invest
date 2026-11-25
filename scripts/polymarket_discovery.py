"""Polymarket read-only discovery output for the existing ESCAPE Radar workflow.

Usage: python scripts/polymarket_discovery.py
Prints an ephemeral JSON research backlog; does not write ESCAPE, Pluto, or jobs.
A separate Radar run must verify official sources + exact Pluto instrument identity.
"""
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import polymarket_intelligence as poly


def collect(limit=100, max_histories=8, now=None):
    """Ephemeral read-only context; not an ESCAPE report candidate list."""
    if type(max_histories) is not int or not 0 <= max_histories <= 8:
        raise ValueError("invalid history budget")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    markets = poly.fetch_markets(limit=limit, now=now)
    unique = {}
    conflicting = set()
    for item in markets:
        key = item["market_id"]
        if key in unique and unique[key] != item:
            conflicting.add(key)
        unique[key] = item
    prelim = [poly.triage(item, now=now) for key, item in unique.items() if key not in conflicting]
    eligible = [item for item in prelim if item["relevant_topic"] and item["liquidity_gate"]]
    eligible.sort(key=lambda item: (item["volume_24h_usd"] or 0), reverse=True)
    # Reserve half the fixed history budget for rotating lower-volume matches.
    # No extra upstream calls or persistent state; coverage is explicitly bounded.
    head_count = (max_histories + 1) // 2
    head = eligible[:head_count]
    tail = eligible[head_count:]
    slots = min(max_histories - len(head), len(tail))
    offset = (int(now.timestamp()) // 3600 * max(1, slots)) % len(tail) if tail else 0
    selected = head + [tail[(offset + i) % len(tail)] for i in range(slots)]
    results = []
    errors = []
    for item in selected:
        try:
            history = poly.price_history(item, now=now)
            results.append(poly.triage(item, history, now=now))
        except poly.PolymarketUnavailable:
            results.append(item)
            errors.append({"market_id": item["market_id"], "reason": "HISTORY_UNAVAILABLE"})
    results.sort(key=lambda item: (item["research_priority"] != "REVIEW",
                                   -abs(item["change_percentage_points"] or 0)))
    return {"status": "PARTIAL" if errors or conflicting else "RETRIEVED",
            "duplicate_conflicts": len(conflicting),
            "unique_markets": len(unique) - len(conflicting),
            "sampling": "volume_head_plus_hourly_rotating_tail",
            "source": "Polymarket public Gamma/CLOB",
            "classification": "UNVERIFIED_PREDICTION_MARKET_CONTEXT",
            "retrieved_at": now.astimezone(timezone.utc).isoformat(),
            "markets_scanned": len(markets),
            "liquid_relevant_markets": len(eligible),
            "histories_attempted": len(selected),
            "observations": results,
            "errors": errors,
            "handoffs": 0,
            "orders": 0,
            "persistent_backlog": False,
            "note": "Observations alone are never ESCAPE candidates or HOT WATCH activations."}


if __name__ == "__main__":
    try:
        print(json.dumps(collect(), ensure_ascii=False, indent=2))
    except poly.PolymarketUnavailable:
        print(json.dumps({"status": "SOURCE_UNAVAILABLE", "handoffs": 0, "orders": 0}))
        sys.exit(1)
