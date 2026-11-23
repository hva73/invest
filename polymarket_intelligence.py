"""Read-only Polymarket intelligence adapter for ESCAPE discovery.

No broker operations, trading signals, Pluto identities or HOT WATCH activation.
Data from prediction markets is hypothesis-level evidence, never issuer verification.
"""
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
MAX_BYTES = 2_000_000
USER_AGENT = "ESCAPE-Research/1.0"
KEYWORDS = ("fed", "interest rate", "inflation", "recession", "merger",
            "acquisition", "fda", "approval", "bitcoin", "ethereum",
            "oil", "tariff", "earnings", "sec", "regulation")


class PolymarketUnavailable(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PolymarketUnavailable("redirect refused")


def _get(base, path, params, opener=None):
    url = base + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                 "User-Agent": USER_AGENT})
    try:
        with (opener or urllib.request.build_opener(NoRedirect())).open(req, timeout=8) as response:
            if response.status != 200:
                raise PolymarketUnavailable("upstream HTTP error")
            raw = response.read(MAX_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise PolymarketUnavailable("upstream unavailable") from exc
    if len(raw) > MAX_BYTES:
        raise PolymarketUnavailable("response too large")
    try:
        return json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PolymarketUnavailable("invalid JSON") from exc


def _array(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def _finite_number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return timestamp.astimezone(timezone.utc).isoformat() if timestamp.tzinfo else None
    except ValueError:
        return None


def normalize_market(raw, observed_at):
    """Return strictly sourced metadata, not an implied fair-value estimate."""
    if not isinstance(raw, dict) or raw.get("closed") is True or raw.get("active") is False:
        return None
    market_id = str(raw.get("id", ""))
    question = raw.get("question")
    slug = raw.get("slug")
    outcomes, prices, tokens = (_array(raw.get(k)) for k in ("outcomes", "outcomePrices", "clobTokenIds"))
    if not market_id.isdigit() or not isinstance(question, str) or not question.strip():
        return None
    if not isinstance(slug, str) or not slug or len(slug) > 200:
        return None
    if len(outcomes) != 2 or len(prices) != 2 or len(tokens) != 2:
        return None
    if [str(x).casefold() for x in outcomes] != ["yes", "no"]:
        return None
    yes = _finite_number(prices[0])
    no = _finite_number(prices[1])
    volume = _finite_number(raw.get("volume24hr"))
    liquidity = _finite_number(raw.get("liquidityNum", raw.get("liquidity")))
    if yes is None or no is None or not (0 <= yes <= 1 and 0 <= no <= 1):
        return None
    if not all(isinstance(x, str) and x.isdigit() for x in tokens):
        return None
    return {
        "provider": "Polymarket", "market_id": market_id, "question": question[:500],
        "url": "https://polymarket.com/event/" + urllib.parse.quote(slug, safe="-"),
        "yes_token_id": tokens[0], "yes_price": yes, "no_price": no,
        "volume_24h_usd": volume if volume is not None and volume >= 0 else None,
        "liquidity_usd": liquidity if liquidity is not None and liquidity >= 0 else None,
        "event_end_at": _stamp(raw.get("endDate")),
        "provider_updated_at": _stamp(raw.get("updatedAt")),
        "retrieved_at": observed_at,
        "classification": "MARKET_EXPECTATION_UNVERIFIED",
        "pluto_verified": False, "candidate_eligible": False,
    }


def fetch_markets(limit=100, opener=None, now=None):
    """Fetch only public market metadata, with no persistent write or side effects."""
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    stamp = now.astimezone(timezone.utc).isoformat()
    data = _get(GAMMA, "/markets",
                {"active": "true", "closed": "false", "limit": limit,
                 "order": "volume24hr", "ascending": "false"}, opener=opener)
    if not isinstance(data, list):
        raise PolymarketUnavailable("invalid markets response")
    return [item for raw in data if (item := normalize_market(raw, stamp))]


def price_history(market, opener=None):
    """Sample YES price history; returns source timestamps, never synthetic prices."""
    token = market["yes_token_id"]
    if not isinstance(token, str) or not token.isdigit():
        raise ValueError("invalid token")
    data = _get(CLOB, "/prices-history",
                {"market": token, "interval": "1d", "fidelity": 10}, opener=opener)
    if not isinstance(data, dict) or not isinstance(data.get("history"), list):
        raise PolymarketUnavailable("invalid history response")
    samples = []
    for item in data["history"]:
        if not isinstance(item, dict):
            continue
        t, p = item.get("t"), _finite_number(item.get("p"))
        if isinstance(t, int) and t > 0 and p is not None and 0 <= p <= 1:
            samples.append({"timestamp": datetime.fromtimestamp(t, timezone.utc).isoformat(),
                            "yes_price": p})
    return sorted({sample["timestamp"]: sample for sample in samples}.values(),
                  key=lambda sample: sample["timestamp"])


def triage(market, history=None, min_liquidity_usd=10_000, min_volume_24h_usd=5_000):
    """Source-only discovery triage; never returns BUY or ESCAPE candidate payload."""
    relevant = any(word in market["question"].casefold() for word in KEYWORDS)
    liquid = (market["liquidity_usd"] is not None and
              market["liquidity_usd"] >= min_liquidity_usd and
              market["volume_24h_usd"] is not None and
              market["volume_24h_usd"] >= min_volume_24h_usd)
    delta = None
    if history and len(history) >= 2:
        delta = round((history[-1]["yes_price"] - history[0]["yes_price"]) * 100, 2)
    return {
        **market, "relevant_topic": relevant, "liquidity_gate": liquid,
        "change_percentage_points": delta,
        "research_priority": ("REVIEW" if relevant and liquid and delta is not None
                              and abs(delta) >= 10 else "CONTEXT_ONLY"),
        "status": "AFVENT_KILDEVERIFIKATION",
        "allowed_in_escape_candidate_payload": False,
        "note": "Prediction-market price is not an issuer announcement, broker quote or buy signal.",
    }
