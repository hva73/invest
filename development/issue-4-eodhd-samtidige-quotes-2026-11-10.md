# Issue #4: EODHD-quote med samme kildetid

Status: undersøgelse og syntetisk kodetest. Dette er ikke et afsluttet produktionsfix.

En samtidig stikprøve omkring 20:36 UTC viste to EODHD-quotes for ZETA med samme tidsstempel `1794342966200` og samme ask 34,46, men forskellig bid 34,16 og 34,27. Uden et kilde-sekvensnummer kan tidsstemplet alene ikke afgøre rækkefølgen. Disse quotes beviser ikke årsagen til fejlen i AAON eller øvrige sessioner.

I `EODHDAdapter.poll` kunne forskellige quotes med samme højeste kildetid vælges vilkårligt. I `refreshed_trade_evidence` kunne en forskellig quote med samme kildetid som tidligere quote føre til `sample_id_conflict`, selv når den underliggende handel var uændret. Den foreslåede ændring beholder handlens uændrede kildepris og -tid, markerer spredningen ukendt ved en tvetydig quote, og tillader først en senere quote at genoprette spredningen. En faktisk modstridende handel afvises fortsat. Ingen quote bliver en handel, og risikoregler eller handelsmandat ændres ikke.

Tests omfatter tvetydig quote i samme feedopsamling, tvetydig fornyelse af en allerede lagret handel, gentagelse, efterfølgende nyere quote, modstridende handel, købssikring ved ukendt spread samt uafhængigt gyldigt kritisk exit. Lokalt bestod 215 tests i `test_eodhd_feeds`, `test_signal_readiness` og `test_hotwatch_engine`; testdata er syntetiske.

En anden pagineret driftsaflæsning viste 55 åbne sessioner: 33 ACTIVE/WAIT, 2 ACTIVE/SELL, 11 DEGRADED/NO_DATA med DATA_STALE, 6 med manglende Pluto-kurstid, 2 med ukendt markedsstatus og 1 med `sample_id_conflict`. Aflæsningen var ikke atomisk og grupperne beskriver viste første tilstande, ikke dokumenterede grundårsager. For WIX, AMZN, IBRX, CRSP, ZETA, TLS og SANM viste det pågældende øjeblik friske data; det udelukker ikke tidligere eller senere problemer.

Før #4 kan afsluttes, kræves en samlet kilde-til-visning-gennemgang med readback pr. session og årsagsklassifikation samt review, relevante CI-tests og separat godkendt installation med produktionsreadback. Ændringen her forklarer ikke i sig selv alle DATA_STALE-tilfælde eller beviseligt AAON-konflikten.

## Pagineret readback ca. 20:48 UTC

55 åbne sessioner, hentet over flere sider og derfor ikke et atomisk øjebliksbillede. Kolonnerne viser tilstand og beregningens årsagskoder; de er ikke i sig selv bevis for den første tekniske grundfejl. Kildetiden er den seneste registrerede markedshændelse, ikke indhentningstidspunktet. Providerdiagnostik er udtrykkeligt fælles for provider og kan ikke bruges som dokumentation for den enkelte session.

| Watch-slutning | Instrument | Formål | Motorstatus / signal | Visning | Seneste beregning | Kontekstdiagnose | Seneste kildetid UTC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| d75d3e46 | NOVOB | automatic holding watch | DEGRADED / NO_DATA | MARKED LUKKET (ORDINÆR HANDEL) | WARMUP, DATA_STALE, MARKET_STATUS_UNKNOWN | — | 2026-11-10T15:59:00+00:00 |
| fc2302b8 | ASML | automatic holding watch | DEGRADED / NO_DATA | MARKED LUKKET (ORDINÆR HANDEL) | WARMUP, DATA_STALE, MARKET_STATUS_UNKNOWN | — | 2026-11-10T16:39:00+00:00 |
| 01e47a9e | MSFT | automatic holding watch | ACTIVE / WAIT | AFVENT | NO_TRIGGER | — | 2026-11-10T20:47:49.826000+00:00 |
| 5f929d9d | BTC | automatic holding watch | DEGRADED / NO_DATA | KURS MODTAGET · MARKEDSSTATUS UKENDT | MARKET_STATUS_UNKNOWN | — | 2026-11-10T20:47:00+00:00 |
| 201f502a | TSM | automatic holding watch | ACTIVE / WAIT | AFVENT | NO_TRIGGER | — | 2026-11-10T20:47:55.776000+00:00 |
| 47589e91 | LHA | automatic holding watch | DEGRADED / NO_DATA | MARKED LUKKET (ORDINÆR HANDEL) | WARMUP, DATA_STALE, MARKET_STATUS_UNKNOWN, POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T16:35:00+00:00 |
| 2fcce32e | AMZN | automatic holding watch | ACTIVE / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | NO_TRIGGER | — | 2026-11-10T20:47:51.382000+00:00 |
| 93db1b99 | MPWR | automatic holding watch | ACTIVE / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | NO_TRIGGER | — | 2026-11-10T20:47:32.005000+00:00 |
| 15178c69 | ORCL | automatic holding watch | ACTIVE / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | NO_TRIGGER | — | 2026-11-10T20:47:40.215000+00:00 |
| 17846b7c | ETN | automatic holding watch | DEGRADED / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:47:27.919000+00:00 |
| 4573b6ad | VRT | automatic holding watch | DEGRADED / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | POSITION_CONTEXT_UNKNOWN | BROKER_CONTEXT_UNAVAILABLE | 2026-11-10T20:47:30.033000+00:00 |
| 459cd1b5 | PEPE | automatic holding watch | DEGRADED / NO_DATA | KURSTID MANGLER | PLUTO_QUOTE_TIME_UNKNOWN | — | — |
| 1743c5ce | BTC | automatic holding watch | DEGRADED / NO_DATA | KURS MODTAGET · MARKEDSSTATUS UKENDT | MARKET_STATUS_UNKNOWN | — | 2026-11-10T20:47:00+00:00 |
| ff970020 | AMGN | automatic holding watch | ACTIVE / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | NO_TRIGGER | — | 2026-11-10T20:47:21.571000+00:00 |
| 888cadf0 | MDLZ | automatic holding watch | DEGRADED / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:48:06.002000+00:00 |
| 0b40a92e | FCX | automatic holding watch | ACTIVE / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | NO_TRIGGER | — | 2026-11-10T20:47:47.950000+00:00 |
| 9f3c5eea | GMAB | automatic holding watch | DEGRADED / NO_DATA | MARKED LUKKET (ORDINÆR HANDEL) | DATA_STALE | — | 2026-11-10T15:59:00+00:00 |
| bf0b78e9 | HIMS | automatic discovery | ACTIVE / NO_DATA | REVURDERING FORFALDET | RISK_INPUTS_UNKNOWN | — | 2026-11-10T20:46:53.470000+00:00 |
| 39dfab54 | BRK.B | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:47:47.169000+00:00 |
| d2fff6ef | GD | automatic holding watch | DEGRADED / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | WARMUP, POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:47:52.601000+00:00 |
| 6073fe50 | CABA | automatic holding watch | DEGRADED / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:47:39.522000+00:00 |
| 74f21dee | JDZG | automatic holding watch | DEGRADED / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | POSITION_CONTEXT_UNKNOWN | BROKER_CONTEXT_UNAVAILABLE | 2026-11-10T20:47:21.591000+00:00 |
| 79185f54 | NRG | automatic holding watch | ACTIVE / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | NO_TRIGGER | — | 2026-11-10T20:46:05.606000+00:00 |
| 6c360108 | VRDN | automatic discovery | ACTIVE / NO_DATA | REVURDERING FORFALDET | FEATURES_INSUFFICIENT, RISK_INPUTS_UNKNOWN | — | 2026-11-10T20:46:46.606000+00:00 |
| 0ecc9701 | CELC | automatic discovery | DEGRADED / NO_DATA | KURSTID MANGLER | PLUTO_QUOTE_TIME_UNKNOWN | — | — |
| 5d1bc107 | IBRX | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:48:09.571000+00:00 |
| 84211ead | CRSP | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:47:38.510000+00:00 |
| 4538aa04 | KMDA | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | DATA_STALE | — | 2026-11-10T20:40:55.857000+00:00 |
| 9402fb63 | TTD | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | BROKER_CONTEXT_UNAVAILABLE | 2026-11-10T20:47:32.501000+00:00 |
| 1eb376c9 | ZETA | automatic holding watch | ACTIVE / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | TRAILING_EXIT | — | 2026-11-10T20:47:17.926000+00:00 |
| 329f25ce | OXY | automatic holding watch | DEGRADED / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:47:39.287000+00:00 |
| 80b52f74 | RKLB | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | BROKER_CONTEXT_UNAVAILABLE | 2026-11-10T20:47:32.051000+00:00 |
| fb81fb9b | ASTS | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | BROKER_CONTEXT_UNAVAILABLE | 2026-11-10T20:47:31.196000+00:00 |
| 8754e066 | GFR | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | DATA_STALE | — | 2026-11-10T20:40:01.364000+00:00 |
| 136422d7 | TTWO | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:48:16.356000+00:00 |
| 32f45e5b | QXO | automatic discovery | ACTIVE / NO_DATA | REVURDERING FORFALDET | RISK_INPUTS_UNKNOWN | — | 2026-11-10T20:47:00.232000+00:00 |
| 699eb083 | TLS | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:47:18.314000+00:00 |
| b616f253 | DCTH | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:48:06.429000+00:00 |
| e29fb832 | ZYME | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | BROKER_CONTEXT_UNAVAILABLE | 2026-11-10T20:47:27.059000+00:00 |
| 5fca3c4b | CRWV | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:48:06.216000+00:00 |
| 2d2298d9 | SANM | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | BROKER_CONTEXT_UNAVAILABLE | 2026-11-10T20:46:39.282000+00:00 |
| d36e580d | QLYS | automatic discovery | ACTIVE / NO_DATA | REVURDERING FORFALDET | TRADABILITY_UNCONFIRMED, RISK_INPUTS_UNKNOWN | — | 2026-11-10T20:47:11.176000+00:00 |
| 03ef140e | SHOT | automatic discovery | DEGRADED / NO_DATA | KURSTID MANGLER | PLUTO_QUOTE_TIME_UNKNOWN | — | — |
| d683468b | IFX | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | DATA_STALE, MARKET_STATUS_UNKNOWN, POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T16:40:00+00:00 |
| 7e5d60df | WIX | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:46:31.589000+00:00 |
| 7043bd78 | HSAI | automatic discovery | DEGRADED / NO_DATA | KURSTID MANGLER | PLUTO_QUOTE_TIME_UNKNOWN | — | — |
| c55b2106 | EXK | automatic discovery | ACTIVE / NO_DATA | REVURDERING FORFALDET | FEATURES_INSUFFICIENT, RISK_INPUTS_UNKNOWN | — | 2026-11-10T20:46:11.793000+00:00 |
| d62c8b3e | SMC | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | DATA_STALE | — | 2026-11-10T20:43:32.741000+00:00 |
| 5dea96d8 | HAG | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | WARMUP, DATA_STALE, MARKET_STATUS_UNKNOWN, POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T16:35:00+00:00 |
| 7a09d92e | VOD | automatic discovery | DEGRADED / NO_DATA | KURSTID MANGLER | PLUTO_QUOTE_TIME_UNKNOWN | — | — |
| 9a46f712 | VG | automatic discovery | ACTIVE / NO_DATA | REVURDERING FORFALDET | FEATURES_INSUFFICIENT, RISK_INPUTS_UNKNOWN | — | 2026-11-10T20:46:33.166000+00:00 |
| 5866817e | SECZ | automatic discovery | DEGRADED / NO_DATA | REVURDERING FORFALDET | POSITION_CONTEXT_UNKNOWN | BROKER_CONTEXT_UNAVAILABLE | 2026-11-10T20:47:27.101000+00:00 |
| cfbb142c | AAON | automatic discovery | DEGRADED / NO_DATA | BID/ASK MODTAGET · SIGNAL AFVENTER | POSITION_CONTEXT_UNKNOWN | — | 2026-11-10T20:47:56.957000+00:00 |
| 6038e64d | EMBJ | automatic discovery | DEGRADED / NO_DATA | KURSTID MANGLER | PLUTO_QUOTE_TIME_UNKNOWN | — | — |
| e75729ee | TURB | automatic discovery | DEGRADED / NO_DATA | DATA FOR GAMLE | WARMUP, DATA_STALE, MARKET_STATUS_UNKNOWN | — | 2026-11-10T20:20:00+00:00 |

Eksempelvis havde AMZN, ZETA og SANM modtaget kursdata, mens en positionskontekst var ukendt; for SANM oplyste diagnosen `BROKER_CONTEXT_UNAVAILABLE`. Denne generiske diagnose kan repræsentere flere fejl i depotopslag og fastslår ikke alene en årsag. For ZETA var seneste beregning `TRAILING_EXIT`, mens den aktuelle visning rapporterede manglende positionskontekst: de to tidspunkter/lag må ikke sammenblandes til et aktuelt salgssignal.

## Præcisering af diagnostik

I arbejdssporet er den hidtidige generiske fejldiagnose suppleret med faste kategorier for database-, netværks-, depotlæse- og opsætningsfejl. Alle efterlader positionskonteksten ukendt og bevarer de eksisterende risikogates; de indeholder aldrig selve fejlteksten. Depotlæsefejl er en bred kategori og beviser ikke, at Plutos dataformat er årsagen. Denne ændring kan først hjælpe med at identificere en eventuel fremtidig fejl efter en særskilt godkendt installation; den kan ikke diagnosticere hændelsen bagudrettet.

Sammenligning af quote-tider bruger desuden faktiske tidspunkter, også når det samme tidspunkt er skrevet med `Z` eller `+00:00`. Samme quote i to formater giver ingen ny observation; forskellige quotes med samme faktiske kildetid bliver fortsat markeret tvetydige.
