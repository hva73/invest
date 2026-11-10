# V2.2 — beslutninger, HOT WATCH og leveringsbeviser

> **Aktuel læsevejledning (10. november 2026):** Historiske workflows skal læses sammen med [masterkontrakten](ESCAPE_MASTER_CONTRACT.md) og den aktuelle kode; versionsnummeret dokumenterer ikke aktuel installation.

Dette er en additiv udvidelse af ESCAPE Invest, ikke et nyt rapportformat. `schema_version: 2`, eksisterende rapporttyper, report_id, source_ids, journal, analysis_for og analysis_urls er bevaret. Nye felter er valgfrie i den eksisterende rapport; hvis et nyt objekt leveres, gælder objektets fulde kontrakt. Ukendte værdier er null, aldrig konstruerede kurser. MCP-serverens versionsnummer er 2.4.0; dette er forskelligt fra rapportens schema_version og kravtillæggets navn V2.2.

## Rapportgeneratoren

Hent den aktuelle kontrakt med `GET /api/reports/schema` efter login, eller læs [JSON Schema](../examples/report-v2.schema.json). `validate_report` og `send_report` bruger samme struktur og referenceregler. Genforsøg kræver samme ID og identisk indhold; ændret indhold kræver nyt ID. Et ID kan ikke flyttes mellem test og drift.

Bevar det normale `escape-hourly-YYYYMMDD-HH00-v2`, `report_type: intraday`, `schema_version: 2`. Appen accepterer også eksisterende andre ID'er og rapporttyper af hensyn til kompatibilitet. Ingen scheduler er ændret.

### Kandidatbeslutning

Valgfrit `candidates[].decision` er null eller:

```json
{
  "status": "AFVENT",
  "decided_at": "2026-11-03T10:00:00Z",
  "reason": "Afvent den konkrete dokumenterede begivenhed",
  "next_trigger": "Offentlig meddelelse med kontrollerbar kilde",
  "deadline": "2026-11-03T12:00:00Z",
  "data_as_of": "2026-11-03T09:59:00Z",
  "source_ids": ["existing-source"],
  "reactivation_reason": null,
  "buy_plan": null
}
```

Status er præcis KØB/AFVENT/FRAVÆLG. AFVENT kræver konkret trigger, deadline og datatid og er aktiv. FRAVÆLG er hvilende; historik og ID bevares. Genaktivering kræver `reactivation_reason`, der dokumenterer en ny katalysator eller væsentlig kurs-/volumenændring. Samme kandidat og beslutningstid med andet beslutningsindhold er en konflikt. Identiske gentagelser giver ingen ekstra beslutningshændelse.

KØB kræver `buy_plan` med `max_limit_price` (pengeobjekt), `amount_dkk` (DKK-pengeobjekt), `horizon` (tekst), `expires_at` (tidsstempel), `risk_budget` (pengeobjekt), `upside`, `downside`, `exit_method` (tekster) og `approval` (proposed/awaiting_approval/approved/rejected/unknown). Udløbstid skal være efter beslutningen. Planen er ikke en ordre og giver ingen selvstændig handelsadgang. En udløbet plan mærkes udløbet og tæller ikke som et aktuelt købssignal.

Gamle `signal`-værdier læses fortsat som historiske signaler. De opgraderes ikke automatisk til nye beslutninger. Den aktive watchlist bevarer kandidater, selv hvis en senere hovedrapport udelader dem; eksplicit FRAVÆLG gør kandidaten hvilende. En gammel eller manglende beslutning i en senere rapport ophæver ikke den seneste dokumenterede beslutning. Positionshandlinger er separate: BEHOLD/OVERVÅG/AFVENT/REDUCÉR/SÆLG.

### Observationer leveres separat

Trading Radar kan sende én on-demand måling med MCP **`record_hot_watch`** (reports:write) eller autentificeret **`POST /api/reports/hot-watch`** med session og CSRF. Målingen opretter ingen kandidat; den skal referere til en eksisterende rapport, der indeholder samme candidate_id, på samme konto og i samme is_test-kategori. Ingen WebSocket-daemon eller ændret timeautomatisering.

Kontrakten annonceres på MCP-værktøjet og eksporteres som [hot-watch.schema.json](../examples/hot-watch.schema.json). Et komplet syntetisk eksempel findes i [hot-watch-test.json](../examples/hot-watch-test.json); den tilhørende syntetiske rapport er [report-v2-positions-test.json](../examples/report-v2-positions-test.json). Eksemplerne er mærket test og skal ikke indlæses som driftsrapporter.

Envelope: `observation_id`, `report_id`, `candidate_id`, `is_test`, `observed_at`, `deadline`, `instrument`, `market`, `recent_trades`, `decision`, `next_trigger`, `position_ref`, `order_ids`, `position_action`, `sources`, `note`. Alle disse medlemmer kræves; nullable medlemmer bruger null.

- `instrument`: ticker, exchange, asset_id. De sidste to kan være null. Et verificeret Pluto-prisudsagn kræver aktiv-ID. Kendt stabil aktividentitet kan ikke skiftes lydløst.
- `market`: price/price_at, bid/bid_at, ask/ask_at, spread/spread_percent, volume/volume_at/volume_basis, intraday_percent, momentum, venue, feed_type, delay_seconds, verification, price_source, source_ids. Penge bruger `{amount: decimalstreng, currency: ISO-valuta}` eller null. Mængder og procenter bruger decimalstrenge eller null. price_source: pluto/eodhd/other/unknown. delay_seconds: heltal >= 0 eller null. Verificeret EODHD er tilladt med dokumenteret faktisk datatid; Pluto mærkes ikke automatisk forsinket.
- `momentum`: accelerating/decelerating/unknown; vises som afsenderens observation. Appen opfinder ikke acceleration mellem manglende målinger.
- `recent_trades`: markedsfeedets handler med trade_id, price, quantity, occurred_at, source_ids. Disse er ikke egne handelsfyldninger.
- `decision`: null eller samme beslutningsobjekt som ovenfor. null bevarer seneste dokumenterede beslutning.
- `position_ref`: null eller præcist portfolio_id + position_id fra den refererede rapport. `position_action` kræver denne reference og angiver action/reason/assessed_at/source_ids. SÆLG er en vurdering, aldrig bevis på salg.
- `order_ids`: referencer til ordreposter i samme rapport. Tilknyttede ordrer skal passe med kandidat og eventuelt depot.
- `sources`: observationens egne kildeposter. Alle source_ids refererer hertil, ikke til skjulte globale kilder.

Tidsstempler skal være RFC3339 med eksplicit tidszone. Markedsværdier kræver deres faktiske tid. Verificerede observationer kræver verificerede kilder. Ukendt/ubekræftet marked kræver null-værdier. Spread fra samtidige bid/ask skal stemme med differencen. Der interpoleres ikke. Kurs- og spreadændringer kræver samme valuta, verificeret grundlag og stigende datatid; spread kræver samtidige bid/ask på begge målinger. Volumenændring kræver samme eksplicitte volume_basis og stigende volumentid.

Maksimal canonical observation: 128 KiB. Validering viser strukturelle fejl samlet; cross-reference/evidence checks gennemføres, når strukturen er gyldig. Samme observation_id er idempotent; andet indhold eller kategori med samme ID giver 409, og intet overskrives.

Læsning: MCP **`get_hot_watch`** (reports:read), eller **`GET /api/reports/hot-watch?is_test=false&candidate_id=...`**. UI har særskilt HOT WATCH-side og kategori. Højst 500 målinger pr. forespørgsel; begrænsningen oplyses. En kandidatforespørgsel giver egen afgrænset historik. Tidspunkter vises både UTC og Europe/Copenhagen. Aktuel ordrestatus kan komme fra en nyere rapport end seneste observation og dateres med egen rapport-ID.

## Depot, likviditet og ordrer

Root inkluderer Collections og AI. Hoveddepot ekskl. AI beregnes kun ved ét entydigt root/AI-par, dokumenteret parent-reference og includes_collections, kendt samme valuta, præcis samme datatid, samme ikke-tomme `valuation_method` og verificerede kildereferencer. Ellers ukendt. Denne beregning er et rapportøjebliksbillede, ikke en ny brokerkontrol. Ingen sum af root + AI vises.

Valgfrit `portfolios[].liquidity`: objekt med `available`, `reserved`, `earmarked`, `unknown`, hver en liste af pengeobjekter eller null-poster. Tomme lister betyder ikke nul. Disponibel likviditet udledes ikke ved at fratrække reservationer/øremærkninger fra kontantbalance. Eksisterende Pluto-kontanter og faktiske Collection-specifikationer bevares.

Valgfrie ordrefelter: asset_id, side, order_type, stop_price, limit_price, approval_status, average_fill_price, created_at, status_changed_at, expires_at, realized_pnl, execution_source (pluto/other/unknown). lifecycle understøtter også expired. Beløb er pengeobjekter eller null; datoer kan være null. requested_quantity og filled_quantity er separate.

Visningsregler: fyldning > 0 kræves før udførelseslabel; fuldt udført kræver lifecycle filled og præcis samme positive bestilte/fyldte antal. Delvis fyldning vises særskilt. ACCEPTED/ACTIVE med 0 eller ukendt fyldning bliver ikke et salg. Rå status og kildetype vises ved siden af afledt label. Resultater vises kun, når de er leveret; ukendt kostpris eller gebyrer udløser ikke et beregnet realiseret resultat. En rapporteret pluto-kilde er afsenderens oplysning, ikke automatisk liveverifikation.

## Regioner og kildekvalitet

Valgfrit `summary.regions[].coverage`: exchanges (liste), status (OK/FEJL/IKKE KØRT), screening_count, data_at, news_checked_at, new_signals, pluto_verified, excluded, gaps (liste), basis (intraday/previous_close/unknown). Antal er ikke-negative heltal eller null. Generatoren skal sende de fire regioner Europa/Norden, USA/Canada, Asien/Stillehav og Råvarer/Metaller; gamle regionnavne og rapporter læses fortsat. Manglende struktureret dækning betegnes ukendt. Previous_close vises eksplicit som senest afsluttede handelsdag. Appen erklærer ikke automatisk global dækning gennemført.

Kilder kan additivt oplyse data_at, venue, feed_type, delay_seconds, primary_news_url. Alle URL'er kontrolleres som HTTPS uden credentials. Eksisterende analysis_urls og Grav dybere er bevaret. Intet eksternt link opfindes, hvis analysen ikke er leveret.

## Levering og grænser for diagnostik

Rapportkvittering indeholder report_id, schema_version, counts, warnings og delivery_status. Ny lagring registrerer received/validated/stored i en separat metadata-tabel i samme transaktion. Eksplicit GET item eller MCP/latest kontrollerer immutable payloads SHA256 før readback_verified registreres. Intern rapportlæsning i forretningslogik skriver ikke kvitteringer. Serverens tilbageslæsning beviser ikke, at klienten har modtaget svaret; dette vises i UI.

Id-konflikt: 409 + delivery_status id_conflict. MCP-valideringsafvisning: konkrete paths og delivery_status rejected_validation. HTTP-import viser alle leverede fejl i resultatfeltet. Netværksfejl uden kvittering vises som ukendt levering; kontrollér arkiv før et sikkert identisk genforsøg. Eksisterende private WSGI-spor skelner modtaget, valideringsafvist, konflikt, lagret og serverfejl uden at logge rapportindhold eller tokens.

**En OpenAI-blokering før serverkontakt efterlader ikke et sikkert serverbevis.** UI kan derfor ikke fastslå dens årsag eller kalde den en servervalideringsfejl. Historiske rapporter uden nye kvitteringer vises med ukendt evidens frem for fabrikerede gamle modtagelses-/valideringstidspunkter. Ingen sikkerhedskontrol omgås.

## Migration og installation

Additive SQLite-tabeller: report_position_links, candidate_decision_events, hot_watch_observations, report_delivery_evidence. Gamle positioner backfilles i indeks; beslutninger indekseres fra eventuelt eksisterende nye felter. Historiske rapportpayloads og digest omskrives ikke. Ejerskab og is_test indgår i alle opslag. Nye observationer og beslutninger giver ingen broker-/scheduler-writes.

Installationspakken indeholder de nye Python- og JS-filer via apply_update.py. Ingen nye produktionsafhængigheder. Genindlæs MCP-værktøjerne i ChatGPT efter manuel installation, så de valgfrie v2-felter og record_hot_watch/get_hot_watch annonceres. Generatoren skal faktisk sende de nye felter/målinger; UI frembringer ikke analyser selv. Der er ikke foretaget automatisk produktionsinstallation eller live MERC-test.
