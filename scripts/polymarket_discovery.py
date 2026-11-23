"""Polymarket read-only discovery output for the existing ESCAPE Radar workflow.

Usage: python scripts/polymarket_discovery.py
Prints an ephemeral JSON research backlog; does not write ESCAPE, Pluto, or jobs.
A separate Radar run must verify official sources + exact Pluto instrument identity.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import polymarket_intelligence as poly


def collect(limit=100, max_histories=8):
    markets = poly.fetch_markets(limit=limit)
    prelim = [poly.triage(item) for item in markets]
    eligible = [item for item in prelim if item["relevant_topic"] and item["liquidity_gate"]]
    eligible.sort(key=lambda item: (item["volume_24h_usd"] or 0), reverse=True)
    selected = eligible[:max_histories]
    results = []
    errors = []
    for item in selected:
        try:
            history = poly.price_history(item)
            results.append(poly.triage(item, history))
        except poly.PolymarketUnavailable:
            results.append(item)
            errors.append({"market_id": item["market_id"], "reason": "HISTORY_UNAVAILABLE"})
    results.sort(key=lambda item: (item["research_priority"] != "REVIEW",
                                   -abs(item["change_percentage_points"] or 0)))
    return {"source": "Polymarket public Gamma/CLOB",
            "classification": "UNVERIFIED_PREDICTION_MARKET_CONTEXT",
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
