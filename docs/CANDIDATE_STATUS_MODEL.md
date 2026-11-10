# Permanent HOT WATCH-kandidatstatus v1.0

> **Aktuel læsevejledning (10. november 2026):** Se [masterkontrakten](ESCAPE_MASTER_CONTRACT.md) for samlet mapping, motorsessionernes selvstændige status og nyere kode-/driftsforbehold.

Kandidatens identitet og rapporthistorik bevares, også når senere rapporter ikke nævner kandidaten. Indlæsning af gamle rapporter opbygger en separat, append-only statusjournal uden at omskrive oprindelige rapportpayloads eller checksums.

Tre dimensioner vises særskilt:

| Dimension | Værdier/kilde |
|---|---|
| Lifecycle | DISCOVERED, ANALYZING, HOT_WATCH, WAITING_TRIGGER, BUY_SIGNAL, ORDER_PENDING, POSITION_OPEN, EXIT_WATCH, CLOSED, ARCHIVED |
| Decision | BUY / WAIT / REJECT, mappet fra eksisterende KØB / AFVENT / FRAVÆLG |
| Execution | Separat verificeret Pluto-ordrestatus; indsendt rapportstatus er ikke fyldningsbevis |

Statusrækkefølgen er ikke lineær. REJECT for nye køb kan eksistere samtidig med en faktisk åben position. Arkiverede/lukkede kandidater kræver en begrundelse ved genaktivering. Nyt handelsforløb bruger nyt `trade_cycle_id`, mens `candidate_id` består. Portefølje, position og ordreferencer må ikke forveksles med kandidatidentiteten.

## Bagudkompatible v2-felter

Alle nye kandidatfelter er valgfrie: `asset_id`, `exchange`, `reactivation_reason` og `lifecycle`. Lifecycle indeholder `status`, `changed_at`, `reason`, `source_ids`, `trade_cycle_id`. Positioner, ordrer og journalposter kan have `trade_cycle_id`. Se regenereret `examples/report-v2.schema.json`. Brug den fælles validator før afsendelse, så referencefejl og tidskonflikter opdages før lagring.

Eksisterende danske decision-felter og gamle v1/v2-rapporter bevares. Engelsk normaliseret decision vises i projektionen. Ingen recommendation opfindes, hvis den mangler i kildedata.

Rapportafsenderen kan rapportere POSITION_OPEN/EXIT_WATCH eller FILLED, men det bliver ikke autoritativ Pluto-bekræftelse alene ved at sætte et source-felt. Rapportindlæsningen returnerer advarsel om manglende bekræftelse. Den oprindelige rapportpåstand kan stadig læses som `reported_status`; den verificerede dimension er separat.

## Pluto-bekræftelse

Serverens læseadapter verificerer ejede depoter, instrument og friske fuldstændige positionssnapshots. ACCEPTED bliver SUBMITTED, positiv delvis fyldning PARTIALLY_FILLED, og positiv komplet fyldning med tilsvarende slutstatus FILLED. Fravær af position alene beviser ikke et salg. CLOSED på udført salg kræver samtidig relevant fyldt salgsordre og ingen position i den kontrollerede depotkontekst.

Først observerede historiske fyldninger uden pålidelig tid/forløbsbinding journalføres uden at lukke et nyt handelsforløb. Inaktive ordreopslag er begrænsede og udgør ikke komplet brokerhistorik. Syntetiske testbeviser er mærket `synthetic_test`, aldrig præsenteret som en rigtig handel.

## Journal, læsning og filtre

`candidate_lifecycle_events`, `candidate_execution_events` og `candidate_trade_cycles` er separate tabeller. Status-/ordrehændelser appendes og idempotente gentagelser deduplikeres. Tidskonflikter med forskelligt indhold afvises. Alle opslag filtreres på ejer og testkategori. Tider gemmes i UTC; UI viser lokal tid efter appens konvention.

Brug `GET /api/v1/hotwatch/candidates/{candidate_id}` og `/history?is_test=true&limit=50`. Historik bruger `next_cursor` som efterfølgende `before`-parameter. Samme projektion findes via MCP `get_hot_watch_engine` med `kind=candidate` og det nye læsescope.

UI har aktiv, afventende, åben position, lukket, arkiveret og alle. Arkiverede kandidater er skjult i standardfilteret, men slettes ikke. Kandidater med bekræftet position kan findes under åben position, selv når nykøbsanbefalingen er REJECT.

## Test og afgrænsning

Testforløb dækker opret → statusændring → rapportlagring → identisk readback → journal, gentagen rapport, udeladt kandidat, genaktivering med ny cycle, rapportpåstand uden Pluto-bekræftelse og separat accepteret/delvist/helt fyldt ordre. Urealiseret/realiseret resultat beregnes ikke ud fra gættede fills; eksisterende verificerede positionsværdier bevares, men en komplet flerhandels P/L-ledger er ikke leveret i denne fase.
