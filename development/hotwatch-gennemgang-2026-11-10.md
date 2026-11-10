# ESCAPE HOT WATCH – uafhængig gennemgang

## Formål og rammer

Læs denne gennemgang og undersøg derefter den eksisterende kode på grenen `codex/escape-development`. Skriv konkrete fund og forslag i en ny fil i samme mappe, gerne med præcise fil- og funktionsnavne og relevante tests. Skeln mellem dokumenteret fejl, sandsynlig forklaring og det, som kræver produktionsdata. Foretag ingen handler eller handelsforslag.

Krav: Pluto er autoritet for beholdninger og ordrer; bevar risikoregler, fuld historik, originale kildetider og manuel godkendelse. Bid/ask er ikke en handel. Ingen ekstra motor, database eller kontrolhierarki. Foreslå små, konkrete ændringer.

## Målingen

- Produktiv commit ved læsningen: `d889aff3694ce3a783845826d61827a5101b9aa7`.
- 56 åbne sessioner, komplet pagineret statuslæsning. Statuslæsningen sluttede omkring 2026-11-10 11:29:07 UTC (12:29 dansk tid).
- Motoren havde været stoppet under installationen og startede 11:28:06 UTC. Efterfølgende ændrer situationen sig løbende; sammenligninger er ikke atomare. En observation, som er nyere end motorens sidst gemte kurs, er et undersøgelsesspor, ikke i sig selv bevis for tabte data.
- Direkte EODHD WebSocket-capture af amerikanske handler og quotes fandt sted ca. 11:28:40–11:28:46 UTC; europæiske feeds ca. 11:28:52 UTC. Felterne nedenfor viser kildens tidsstempel og alderen ved modtagelsen, afrundet i sekunder. 'Ikke fanget' betyder ingen observation i et kort capturevindue; det beviser ikke, at ingen handel fandtes på markedet.
- BTC blev kontrolleret særskilt via EODHD crypto-stream og havde friske BTC-USD-hændelser. Dette dokumenterer ikke handelsadgang hos Pluto eller identitet for PEPE.
- Statusfeltet `recovery` er senest gemte gendannelsesstatus, ikke nødvendigvis resultatet af en ny kontrol. `NO_TRIGGER`, `DATA_STALE` og manglende bekræftelse er ikke automatisk kodefejl.
- ESCAPE-plugin giver statusudsnit og begrænsede logdata; denne måling indeholder ikke fulde rå sessioner, Pluto-snapshots eller dokumentation for alle datakilders identitet.

## Prioriterede observationer til undersøgelse

1. **TTD:** frisk EODHD-handel og bid/ask; Pluto-session uden verificeret EODHD-match. Genopretning rapporterer `PROVIDER_RATE_BUDGET` og Pluto-kursen mangler kildetidspunkt. Undersøg hvorfor identitetskontrol ikke kommer igennem med ledigt EODHD-dagsbudget, og om Pluto-kapaciteten anvendes hensigtsmæssigt.
2. **RKLB:** EODHD og Endavu dokumenterede samme Nasdaq-notering og ISIN. Navnevarianten blev rettet i commit d889aff. Senere produktionslæsning viste `MATCHED`, provider EODHD og en verificeret handel kl. 11:28:23.669 UTC. Signalgrundlag afventede bl.a. `WARMUP` / `POSITION_CONTEXT_UNKNOWN`; det er adskilt fra kildematchet.
3. **WIX, IBRX, CRSP, AMZN:** direkte capture viste frisk handel og quote, mens motorens senest gemte handel ved læsningen var ældre. Undersøg kø, feed-cache, afvisninger og scanninger efter genstart før årsagen fastslås. IBRX viste desuden `WAITING_FOR_NEW_VERIFIED_QUOTE`.
4. **MSFT:** `sample_id_conflict` blev observeret i produktionsstatus før genstarten; senere viste sessionen `DATA_STALE`. Undersøg konflikter i selve journalen; sammenlign kildetid, sample-ID og indhold, og genbrug aldrig en konfliktende observation.
5. **CABA kandidat:** `HOLDING_SCOPE_OVERLAP` i Pluto-konteksten; undersøg faktisk depot- og collection-scope uden dobbeltoptælling. CABA har også en separat beholdningssession; stikprøven viste ingen frisk handel.
6. **ASML og ORCL:** frisk kildedata samtidig med `BAR_EVIDENCE_STALE` i visningen. ASML viste senere også `POSITION_CONTEXT_UNKNOWN`; undersøg disse forhold særskilt. Det er ikke dokumenteret, at bar-valideringen er forkert.
7. **PEPE:** foreløbig EODHD-reference er ikke tokenverificeret, og Pluto-kursen mangler kildetid. Bevar blokeringen, indtil identitet kan dokumenteres.
8. **JDZG:** trailing-exit-grundlag og `EXTENDED_HOURS_EXECUTION_UNCONFIRMED` / bekræftelsesafventning blev observeret. Gennemgå aktuel signalberegning, pushdeduplikering og eksekverbarhed hver for sig.

## Status for alle sessioner

Senest observeret motor- og kildedata. `sidste` og kildetider er UTC. 'Beholdning' og 'Kandidat' angiver sessionens formål. To BTC-sessioner og to CABA-sessioner er særskilte.

| Instrument | Formål | Provider | Motorstatus / signal | Seneste motordata UTC | EODHD-handel UTC | EODHD bid/ask UTC | Sidste fejl | Beregningsårsager | Aktuelle visningsårsager | Depotdiagnose | Recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| NOVOB | Beholdning | eodhd | ACTIVE / WAIT | 2026-11-10T11:28:52.432000+00:00 | 2026-11-10T11:28:06.062Z (alder 46 s) | 2026-11-10T11:28:28.734Z (alder 24 s) | — | NO_TRIGGER | — | — | MATCHED |
| ASML | Beholdning | eodhd | ACTIVE / NO_DATA | 2026-11-10T11:27:52.607000+00:00 | 2026-11-10T11:28:48.526Z (alder 4 s) | 2026-11-10T11:28:50.491Z (alder 2 s) | — | NO_TRIGGER | BAR_EVIDENCE_STALE | — | MATCHED |
| MSFT | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:26:40.313000+00:00 | 2026-11-10T11:26:40.313Z (alder 120 s) | 2026-11-10T11:27:14.598Z (alder 92 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| BTC | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:28:00+00:00 | Ikke fanget | Ikke fanget | — | MARKET_STATUS_UNKNOWN | — | — | MATCHED |
| TSM | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:26:09.909000+00:00 | 2026-11-10T11:26:15.427Z (alder 145 s) | 2026-11-10T11:27:42.032Z (alder 64 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| LHA | Beholdning | eodhd | ACTIVE / WAIT | 2026-11-10T11:28:23.744000+00:00 | 2026-11-10T11:28:23.744Z (alder 29 s) | 2026-11-10T11:28:43.016Z (alder 9 s) | — | NO_TRIGGER | — | — | MATCHED |
| AMZN | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:26:00+00:00 | 2026-11-10T11:27:59.635Z (alder 41 s) | 2026-11-10T11:28:33.896Z (alder 12 s) | — | WARMUP, DATA_STALE, MARKET_STATUS_UNKNOWN | DATA_STALE | — | MATCHED |
| MPWR | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:00:57.533000+00:00 | 2026-11-10T11:00:57.533Z (alder 1663 s) | 2026-11-10T11:13:11.071Z (alder 935 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| ORCL | Beholdning | eodhd | ACTIVE / NO_DATA | 2026-11-10T11:27:31.500000+00:00 | 2026-11-10T11:27:31.500Z (alder 69 s) | 2026-11-10T11:28:07.263Z (alder 39 s) | — | NO_TRIGGER | BAR_EVIDENCE_STALE | — | MATCHED |
| ETN | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:18:36.784000+00:00 | 2026-11-10T11:18:36.784Z (alder 604 s) | 2026-11-10T11:25:50.173Z (alder 176 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| VRT | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:22:53.729000+00:00 | 2026-11-10T11:22:53.729Z (alder 347 s) | 2026-11-10T11:26:41.139Z (alder 125 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| PEPE | Beholdning | pluto | DEGRADED / NO_DATA | — | Ikke fanget | Ikke fanget | PLUTO_QUOTE_TIME_UNKNOWN | PLUTO_QUOTE_TIME_UNKNOWN | PLUTO_QUOTE_TIME_UNKNOWN | — | CRYPTO_IDENTITY_UNVERIFIED |
| BTC | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:28:00+00:00 | Ikke fanget | Ikke fanget | — | MARKET_STATUS_UNKNOWN | — | — | EODHD_IDENTITY_UNCERTAIN |
| AMGN | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T10:03:34.648000+00:00 | 2026-11-10T10:03:34.648Z (alder 5106 s) | 2026-11-10T10:04:27.176Z (alder 5059 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| MDLZ | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T00:31:00+00:00 | Ikke fanget | 2026-11-10T11:11:02.994Z (alder 1063 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| FCX | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T10:22:33.048000+00:00 | 2026-11-10T10:22:33.048Z (alder 3967 s) | 2026-11-10T11:26:55.923Z (alder 110 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| GMAB | Beholdning | eodhd | ACTIVE / NO_DATA | 2026-11-10T11:27:00.906000+00:00 | 2026-11-10T11:28:45.266Z (alder 7 s) | 2026-11-10T11:28:45.297Z (alder 7 s) | — | NO_TRIGGER | DATA_STALE | — | MATCHED |
| MLYS | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T10:43:10.184000+00:00 | 2026-11-10T10:43:10.184Z (alder 2730 s) | 2026-11-10T10:43:11.187Z (alder 2735 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| HIMS | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:27:05.731000+00:00 | 2026-11-10T11:27:05.731Z (alder 95 s) | 2026-11-10T11:28:07.748Z (alder 39 s) | — | WARMUP, TRADABILITY_UNCONFIRMED, OUTSIDE_REGULAR_SESSION, FEATURES_INSUFFICIENT, RISK_INPUTS_UNKNOWN | — | — | MATCHED |
| FLY | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:26:00.440000+00:00 | 2026-11-10T11:26:00.440Z (alder 160 s) | 2026-11-10T11:28:21.885Z (alder 25 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| LUNR | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:24:53.483000+00:00 | 2026-11-10T11:24:53.483Z (alder 227 s) | 2026-11-10T11:28:04.837Z (alder 42 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| CABA | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T00:53:00+00:00 | Ikke fanget | 2026-11-10T09:01:31.575Z (alder 8835 s) | DATA_STALE | DATA_STALE | DATA_STALE | HOLDING_SCOPE_OVERLAP | MATCHED |
| VIR | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T10:29:44.594000+00:00 | 2026-11-10T10:29:44.594Z (alder 3536 s) | 2026-11-10T10:54:40.506Z (alder 2046 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| MANE | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T10:45:15.393000+00:00 | 2026-11-10T10:45:15.393Z (alder 2605 s) | 2026-11-10T10:48:04.215Z (alder 2442 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| BRK.B | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:08:12.967000+00:00 | 2026-11-10T11:08:12.967Z (alder 1227 s) | 2026-11-10T11:16:30.573Z (alder 736 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| GD | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:08:03.024000+00:00 | 2026-11-10T11:08:03.024Z (alder 1237 s) | 2026-11-10T11:08:03.278Z (alder 1243 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| CABA | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T00:53:00+00:00 | Ikke fanget | 2026-11-10T09:01:31.575Z (alder 8835 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | — |
| JDZG | Beholdning | eodhd | ACTIVE / WAIT | 2026-11-10T11:27:36.524000+00:00 | 2026-11-10T11:27:36.524Z (alder 64 s) | 2026-11-10T11:28:23.836Z (alder 23 s) | — | TRAILING_EXIT, EXTENDED_HOURS_EXECUTION_UNCONFIRMED, CONFIRMATION_PENDING | — | — | MATCHED |
| NRG | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:08:19.382000+00:00 | 2026-11-10T11:08:19.382Z (alder 1221 s) | 2026-11-10T11:14:15.830Z (alder 871 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| KKR | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T10:46:40.602000+00:00 | 2026-11-10T10:46:40.602Z (alder 2520 s) | 2026-11-10T11:27:11.050Z (alder 95 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| CEG | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:20:05.791000+00:00 | 2026-11-10T11:25:44.442Z (alder 176 s) | 2026-11-10T11:28:01.080Z (alder 45 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| FERG | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T00:41:00+00:00 | Ikke fanget | 2026-11-10T09:00:16.665Z (alder 8910 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| VRDN | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T00:30:00+00:00 | Ikke fanget | 2026-11-10T09:00:00Z (alder 8926 s) | — | WARMUP, DATA_STALE, MARKET_STATUS_UNKNOWN | DATA_STALE | — | MATCHED |
| CELC | Kandidat | pluto | DEGRADED / NO_DATA | — | Ikke fanget | 2026-11-10T09:51:46.689Z (alder 5820 s) | PROVIDER_RATE_BUDGET | PROVIDER_RATE_BUDGET | PROVIDER_RATE_BUDGET | — | PROVIDER_RATE_BUDGET |
| IBRX | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:15:38.970000+00:00 | 2026-11-10T11:26:47.640Z (alder 113 s) | 2026-11-10T11:28:30.295Z (alder 16 s) | DATA_STALE | DATA_STALE | DATA_STALE, WAITING_FOR_NEW_VERIFIED_QUOTE | — | MATCHED |
| CRSP | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T10:53:30.294000+00:00 | 2026-11-10T11:26:51.349Z (alder 109 s) | 2026-11-10T11:26:51.349Z (alder 115 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| KMDA | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T09:10:53.853000+00:00 | 2026-11-10T09:10:53.853Z (alder 8266 s) | 2026-11-10T10:46:53.893Z (alder 2513 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| TTD | Kandidat | pluto | DEGRADED / NO_DATA | — | 2026-11-10T11:27:47.479Z (alder 53 s) | 2026-11-10T11:28:45.515Z (alder 1 s) | PLUTO_QUOTE_TIME_UNKNOWN | PLUTO_QUOTE_TIME_UNKNOWN | PLUTO_QUOTE_TIME_UNKNOWN | — | PROVIDER_RATE_BUDGET |
| ZETA | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:09:12.113000+00:00 | 2026-11-10T11:09:12.113Z (alder 1168 s) | 2026-11-10T11:27:52.769Z (alder 54 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| OXY | Beholdning | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:01:16.205000+00:00 | 2026-11-10T11:01:16.205Z (alder 1644 s) | 2026-11-10T11:16:10.835Z (alder 755 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| RKLB | Kandidat | eodhd | DEGRADED / NO_DATA | — | 2026-11-10T11:28:23.669Z (alder 17 s) | 2026-11-10T11:28:38.595Z (alder 8 s) | PLUTO_QUOTE_TIME_UNKNOWN | PLUTO_QUOTE_TIME_UNKNOWN | PLUTO_QUOTE_TIME_UNKNOWN, WAITING_FOR_NEW_VERIFIED_QUOTE | — | MATCHED |
| ASTS | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:23:09.860000+00:00 | 2026-11-10T11:25:35.200Z (alder 185 s) | 2026-11-10T11:26:31.991Z (alder 134 s) | DATA_STALE | DATA_STALE | DATA_STALE | BROKER_CONTEXT_UNAVAILABLE | MATCHED |
| GFR | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:00:36.752000+00:00 | 2026-11-10T11:00:36.752Z (alder 1684 s) | 2026-11-10T11:20:06.169Z (alder 520 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| TTWO | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:25:01.321000+00:00 | 2026-11-10T11:25:01.321Z (alder 219 s) | 2026-11-10T11:26:39.156Z (alder 127 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| QXO | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:11:56.562000+00:00 | 2026-11-10T11:11:56.562Z (alder 1004 s) | 2026-11-10T11:11:56.619Z (alder 1010 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| TLS | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:11:47.887000+00:00 | 2026-11-10T11:11:47.887Z (alder 1013 s) | 2026-11-10T11:28:43.291Z (alder 3 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| DCTH | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T09:20:25.585000+00:00 | 2026-11-10T09:20:25.585Z (alder 7695 s) | 2026-11-10T09:20:25.589Z (alder 7701 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| ZYME | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T00:30:00+00:00 | Ikke fanget | 2026-11-10T11:03:54.823Z (alder 1491 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| CRWV | Kandidat | eodhd | ACTIVE / NO_DATA | 2026-11-10T11:27:05.056000+00:00 | 2026-11-10T11:27:05.056Z (alder 95 s) | 2026-11-10T11:28:41.642Z (alder 5 s) | — | TRADABILITY_UNCONFIRMED, OUTSIDE_REGULAR_SESSION, RISK_INPUTS_UNKNOWN | DATA_STALE | — | MATCHED |
| SANM | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:05:55.817000+00:00 | 2026-11-10T11:05:55.817Z (alder 1364 s) | 2026-11-10T11:28:21.809Z (alder 25 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| QLYS | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T00:58:00+00:00 | Ikke fanget | 2026-11-10T10:22:07.883Z (alder 3999 s) | DATA_STALE | DATA_STALE | DATA_STALE | — | MATCHED |
| SHOT | Kandidat | pluto | DEGRADED / NO_DATA | — | Ikke fanget | Ikke fanget | PROVIDER_RATE_BUDGET | PROVIDER_RATE_BUDGET | PROVIDER_RATE_BUDGET | — | PROVIDER_RATE_BUDGET |
| IFX | Kandidat | eodhd | ACTIVE / WAIT | 2026-11-10T11:28:04.416000+00:00 | 2026-11-10T11:28:39.354Z (alder 13 s) | 2026-11-10T11:28:39.360Z (alder 13 s) | — | TRADABILITY_UNCONFIRMED, RISK_INPUTS_UNKNOWN | — | — | MATCHED |
| WIX | Kandidat | eodhd | DEGRADED / NO_DATA | 2026-11-10T11:06:00+00:00 | 2026-11-10T11:28:32.993Z (alder 7 s) | 2026-11-10T11:28:33.005Z (alder 13 s) | — | WARMUP, DATA_STALE, MARKET_STATUS_UNKNOWN | DATA_STALE | — | MATCHED |
| HSAI | Kandidat | pluto | DEGRADED / NO_DATA | — | 2026-11-10T11:23:51.787Z (alder 289 s) | 2026-11-10T11:26:45.013Z (alder 121 s) | PLUTO_QUOTE_TIME_UNKNOWN | PLUTO_QUOTE_TIME_UNKNOWN | PLUTO_QUOTE_TIME_UNKNOWN | — | EODHD_IDENTITY_UNCERTAIN |
| EXK | Kandidat | pluto | DEGRADED / NO_DATA | — | 2026-11-10T11:16:10.824Z (alder 749 s) | 2026-11-10T11:21:59.313Z (alder 407 s) | PROVIDER_RATE_BUDGET | PROVIDER_RATE_BUDGET | PROVIDER_RATE_BUDGET | — | PROVIDER_RATE_BUDGET |

Bemærk: En senere kontrol efter tabellen viste, at RKLB havde modtaget en verificeret EODHD-observation; tabellens tidligere `PLUTO_QUOTE_TIME_UNKNOWN` kan derfor være en ældre fejl, der endnu ikke var ryddet ved selve læsningen. Status for andre instrumenter kan ligeledes have ændret sig.

## Budget under testen

EODHDs officielle normale dagsgrænse er 100.000 enheder. Brugeren har købt ekstra saldo og kun godkendt manuel anvendelse som nødreserve for 10. november UTC. Commit d889aff har en tidsafgrænset undtagelse på højst 200.000 enheder og læser leverandørens resterende ekstra saldo. Fra 11. november 00:00 UTC skal den normale budgetstyring gælde igen. Ekstrasaldi må ikke automatisk bruges på kommende dage.

## Ønsket tilbagemelding

- Hvilke af punkterne kan dokumenteres ud fra kode og tilgængelige data?
- Hvilke konkrete funktioner og linjer forårsager dem?
- Hvilke minimale rettelser og meningsfulde regressionstests anbefales?
- Hvad kræver yderligere produktionslog eller verificering efter installation?
- Kan den fulde datakæde vurderes uden at svække identitets- eller risikokontrol?
