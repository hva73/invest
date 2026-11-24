"""Bounded, public, read-only Polymarket API smoke; no account or trade access."""
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import polymarket_intelligence as poly


def main():
    at = datetime.now(timezone.utc)
    markets = poly.fetch_markets(limit=20, now=at)
    if not markets:
        raise poly.PolymarketUnavailable("no valid active markets")
    first = markets[0]
    history = poly.price_history(first, now=at)
    if not isinstance(history, list):
        raise poly.PolymarketUnavailable("invalid history")
    # Only source metadata is exposed; never print token IDs or contract prices
    # as if they were ESCAPE trade signals.
    print(json.dumps({
        "status": "PASS",
        "retrieved_at": at.isoformat(),
        "gamma_markets_validated": len(markets),
        "clob_history_response_valid": True,
        "clob_history_observations": len(history),
        "orders": 0,
        "candidate_handoffs": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except poly.PolymarketUnavailable:
        print(json.dumps({"status": "SOURCE_UNAVAILABLE", "orders": 0, "candidate_handoffs": 0}))
        raise SystemExit(1) from None
