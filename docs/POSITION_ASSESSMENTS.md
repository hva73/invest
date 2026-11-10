# Individuelle positionsvurderinger

> **Aktuel læsevejledning (10. november 2026):** Se [masterkontrakten](ESCAPE_MASTER_CONTRACT.md) for vurdering kontra motor-/brokerstatus og kilde-/tidskrav.

Positionsvurderinger er et valgfrit, additivt lag i `schema_version: 2`. Gamle v1/v2-payloads, digest og rapport-ID'er ændres ikke. MCP-kontrakten og backend bruger det samme deklarative schema.

Rapportgeneratoren skal sende **alle faktiske positionsposter** i hovedrapportens `positions`. Positioner er ikke kandidater: `candidate_id` kan være null. Identiteten er `(portfolio_id, position_id)`; samme BTC i to depoter kan have egne vurderinger og ordrer. Et instrument må ikke skifte `asset_id` under samme positionsidentitet. Journalposter med et position_id, der gentages i flere depoter, skal også oplyse `portfolio_id`.

Nye valgfrie positionsfelter:

- `asset_id`, `asset_name`: string eller null.
- `assessment`: null eller objektet nedenfor. Alle medlemmer i objektet kræves, når objektet findes.
- `market`: null eller `{price, daily_change, daily_change_percent, price_as_of, change_as_of, verification, source_ids}`. Beløb er pengeobjekter eller null; procent er decimalstreng eller null. Ukendt/ubekræftet kursgrundlag kræver null-priser. Verificerede oplysninger kræver datatid og verificerede kilder.
- `unrealized_pnl`: signeret pengeobjekt eller null.
- `position_status`: open/closed/unknown.

```json
{
  "action": "OVERVÅG",
  "reason": "Konkret individuel begrundelse, ikke et genbrugt kandidatsignal",
  "risk_level": "medium",
  "next_action": "Kontrollér den dokumenterede begivenhed",
  "assessed_at": "2026-11-03T10:00:00Z",
  "source_ids": ["source-existing-in-this-report"],
  "data_quality": {
    "status": "mixed",
    "as_of": "2026-11-03T10:00:00Z",
    "note": "Forklar manglende oplysninger"
  }
}
```

`action`: BEHOLD, OVERVÅG, AFVENT, REDUCÉR eller SÆLG. Ingen analyse giver DATA MANGLER; ubekræftet/historisk analyse giver IKKE VURDERET. Der opfindes aldrig BEHOLD. Nye porteføljer og køb kommer automatisk med gennem positionslisten; ingen tickerliste er hardkodet i appen.

Quantity null betyder ukendt, ikke nul. Quantity 0 eller eksplicit closed flytter posten til tidligere positioner. En manglende position i næste rapport betegnes ikke automatisk solgt. En aktiv STOP-ordre ændrer aldrig antal. Oplyst fyldning og vurdering vises særskilt.

`deep_analysis` kan levere en senere individuel vurdering for samme positionsidentitet. Den overskriver ikke hovedrapportens beholdningsantal og genopliver ikke en lukket position. Kandidatuddybninger bevarer `analysis_for` og analysepakkerne.

Ændringslisten viser nye/lukkede/udeladte positioner, ændret handling/risiko, nye vurderinger, ændrede STOP-fyldninger og verificerede kursændringer på mindst 5 % med sammenlignelige valutaer og stigende kurstid. Gentaget uændret analyse bliver ikke en ny hændelse. 5 %-grænsen er en visningsregel, ikke et handelssignal.

SQLite-tabellen `report_position_links` indekserer immutable rapporter og backfilles additivt. Positionshistorik læses via det autentificerede `GET /api/reports/position-history?portfolio_id=...&position_id=...&is_test=false`. Andre brugeres eller kategoriernes positioner kan ikke læses.

Pluto-kurser læses særskilt via den eksisterende read-only kurskontrakt med rapport-ID og det præcise portfolio/position-par. To BTC-positioner kan dele aktivcache, men hverken vurdering eller depotidentitet. Ukendt kurstid betegnes ukendt; hentetid er en anden oplysning. Der oprettes ingen kandidater eller handler for at hente en positionskurs.
