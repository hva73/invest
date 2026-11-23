# Polymarket Prediction Intelligence — ESCAPE discovery adapter

This is a **read-only research input**, not an active ESCAPE HOT WATCH motor,
a Pluto connector, or an automated trading strategy.

## Use

```sh
python scripts/polymarket_discovery.py
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
- `REVIEW` flags a topic with minimum volume/liquidity and >=10 percentage
  points of observed movement. It is **not** HOT WATCH-eligible and not BUY.
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
