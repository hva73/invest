# Polymarket Prediction Intelligence — ESCAPE discovery adapter

This is a **read-only research input**, not an active ESCAPE HOT WATCH motor,
a Pluto connector, or an automated trading strategy.

## Use

```sh
python scripts/polymarket_discovery.py
python scripts/polymarket_smoke.py  # public Gamma/CLOB connectivity, read-only
python -m unittest tests.test_polymarket_intelligence -v
```

The runner scans up to 100 public active Gamma markets and requests 24-hour
YES-price history for at most eight liquid topic matches. It writes JSON to
standard output only; no database, report, automation or broker writes.

## Data contract

- `yes_price` is a contract's market price, **not** a verified event probability.
- `change_percentage_points` uses timestamped CLOB history, never the market
  creation date or a stale Gamma quote as an invented first observation.
- `volume_24h_usd` and `liquidity_usd` may be `null`; missing data fails the
  research liquidity gate rather than becoming zero-confirmed liquidity.
- `retrieved_at` differs from `provider_updated_at` and the individual history
  sample timestamps.
- `REVIEW` flags an exact whole-word topic (not substring noise), minimum
  volume/liquidity and >=10 percentage points between **two timestamps within
  the last 24 hours**; the newest sample must be at most three hours old.
  Older/incomplete/inconsistent history is `CONTEXT_ONLY`, never a
  fabricated new catalyst. It is **not** HOT WATCH-eligible and not BUY.
- The issuer, resolution criteria, event dates, primary sources, ticker/ISIN
  identity and exchange exposure must be verified independently before Pluto
  search_assets -> get_asset and any ESCAPE report/handoff.
- Do **not** enter Polymarket-only rows in ESCAPE candidates, positions, orders
  or candidate-linked journals. Describe them as external context in user text.
- No prediction market wallets, on-chain signing, API keys or orders.

## Scope and acceptance

This PR supplies the first safe, executable data adapter and research output.
It does **not** wire in scheduled ingestion, persistence, UI, report-v2 fields,
motor activation, or production deployment. Those require existing owner-approved
Codex integration and release controls. Keep the existing hourly Radar automation
unchanged. Before promotion: run unit tests, an authorized outbound API smoke test,
verify topic precision and pricing against actual Polymarket market pages, compare
timestamped signals against subsequent stock reactions without look-ahead, and
confirm the user never sees a prediction contract as a Pluto-tradable asset.

Docs: https://institute.polymarket.com/data and
https://github.com/Polymarket/agent-skills/blob/main/market-data.md

## Radar v5.1 research integration contract

The existing hourly `Fast markedstjek begge porteføljer` automation is the
**orchestrator**; this module is a standalone, bounded public-data adapter.
It must **not** be installed as a new HOT WATCH service, cron job, database
writer or independent scheduled process. When the authorized research
environment can execute Python, read the output of
`scripts/polymarket_discovery.py` and handle it as ephemeral **unverified
external context** only. Where code execution or outbound access is absent,
the radar may use a contemporaneous public Polymarket market page and
independently timestamped source links, and must report `NOT_CHECKED` if
no actual retrieval took place.

Radar work order: existing ESCAPE continuity readback **first** → Pluto
positions and existing watch risk → global news / catalysts → bounded
Polymarket context → independent official primary source verification →
precise `Pluto search_assets` and `get_asset` only if an actual listed
instrument is independently established → existing report-v2 validation
and HOT WATCH gating. A prediction-market market ID/token ID never becomes
`candidate_id`, `asset_id`, `trade_cycle_id`, watch, signal or an order.
No schema additions. No handoff from Polymarket-only evidence.

Report research coverage with actual retrieved/failed/not-checked status,
observed time, source link, market question, YES price as a **contract
price**, 24h timestamped change and provenance, liquidity and uncertainty.
An unresolved event or market move is not a company announcement, nor proof
that a stock price will move. Never use Polymarket quotes as price or
volume for a stock; never turn a research REVIEW into BUY.

If the external source is unavailable, continue the rest of the radar,
show a bounded `SOURCE_UNAVAILABLE` state and do not alter existing
candidate continuity. The adapter never uses wallets, private credentials,
broker writes or public guessing of company identity.

## CI and acceptance

Run synthetic negative tests and one authorized, bounded live API smoke
request. Smoke must demonstrate reachable Gamma and CLOB responses, not
simulate user trading or mean that cross-source/Pluto mapping is verified.
Before production acceptance independently check market-page identity,
resolution criteria and primary sources, and evaluate timing against
listed-equity reactions without look-ahead. Deployment and changes to the
hourly radar prompt remain separately auditable.
