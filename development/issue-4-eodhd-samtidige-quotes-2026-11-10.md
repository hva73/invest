# Issue #4: EODHD-quote med samme kildetid

Status: undersøgelse og syntetisk kodetest. Dette er ikke et afsluttet produktionsfix.

En samtidig stikprøve omkring 20:36 UTC viste to EODHD-quotes for ZETA med samme tidsstempel `1794342966200` og samme ask 34,46, men forskellig bid 34,16 og 34,27. Uden et kilde-sekvensnummer kan tidsstemplet alene ikke afgøre rækkefølgen. Disse quotes beviser ikke årsagen til fejlen i AAON eller øvrige sessioner.

I `EODHDAdapter.poll` kunne forskellige quotes med samme højeste kildetid vælges vilkårligt. I `refreshed_trade_evidence` kunne en forskellig quote med samme kildetid som tidligere quote føre til `sample_id_conflict`, selv når den underliggende handel var uændret. Den foreslåede ændring beholder handlens uændrede kildepris og -tid, markerer spredningen ukendt ved en tvetydig quote, og tillader først en senere quote at genoprette spredningen. En faktisk modstridende handel afvises fortsat. Ingen quote bliver en handel, og risikoregler eller handelsmandat ændres ikke.

Tests omfatter tvetydig quote i samme feedopsamling, tvetydig fornyelse af en allerede lagret handel, gentagelse, efterfølgende nyere quote, modstridende handel, købssikring ved ukendt spread samt uafhængigt gyldigt kritisk exit. Lokalt bestod 215 tests i `test_eodhd_feeds`, `test_signal_readiness` og `test_hotwatch_engine`; testdata er syntetiske.

En anden pagineret driftsaflæsning viste 55 åbne sessioner: 33 ACTIVE/WAIT, 2 ACTIVE/SELL, 11 DEGRADED/NO_DATA med DATA_STALE, 6 med manglende Pluto-kurstid, 2 med ukendt markedsstatus og 1 med `sample_id_conflict`. Aflæsningen var ikke atomisk og grupperne beskriver viste første tilstande, ikke dokumenterede grundårsager. For WIX, AMZN, IBRX, CRSP, ZETA, TLS og SANM viste det pågældende øjeblik friske data; det udelukker ikke tidligere eller senere problemer.

Før #4 kan afsluttes, kræves en samlet kilde-til-visning-gennemgang med readback pr. session og årsagsklassifikation samt review, relevante CI-tests og separat godkendt installation med produktionsreadback. Ændringen her forklarer ikke i sig selv alle DATA_STALE-tilfælde eller beviseligt AAON-konflikten.
