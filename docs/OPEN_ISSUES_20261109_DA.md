# ESCAPE — åbne fejl og verifikationer

Senest gennemgået 9. november 2026. Listen er et arbejdsredskab: ændr status med dato, evidens og næste skridt. En lokal rettelse er ikke det samme som en installeret og verificeret rettelse.

| Prioritet | Forhold og seneste evidens | Status og næste skridt |
| --- | --- | --- |
| Kritisk | HOT WATCH-worker rapporterede `stopped`, seneste heartbeat kl. 07.05 dansk tid; kl. 07.12 var heartbeat forældet. | ÅBEN: Find årsagen til stop og få sikker, nyttig driftsdiagnostik. Supervisorens start afleder stdout/stderr til DEVNULL; det beviser ikke, hvorfor processen stopper. De modtagne logs fastslår ikke årsagen. Verificér stabil drift efter installation. |
| Kritisk | MLYS var `VALIDATING`, HIMS og FLY `CREATED` uden observation ved readback kl. 07.12. Fem andre rapportkandidater ventede ifølge visningen. | DELVIST: Overdragelse har oprettet tre sessioner; det beviser ikke aktive signaler. Undersøg worker, kandidaternes særskilte blokeringer og frisk observation. Omgå ikke gates. |
| Høj | Adgangsloggen viser HTTP 500 på `/mcp` kl. 06.57–07.00 den 9. november. | ÅBEN: Find konkret årsag og sammenhæng med motoren. Ingen årsag eller sammenhæng er endnu bevist. |
| Høj | Nogle beholdningssessioner havde forældede kurser eller ikke-verificeret beholdningskontekst ved kontrol. | ÅBEN: Kontrollér frisk Pluto-kontekst, identitet, depotbinding og separat exit-overvågning med aktuelle data. Weekendkurser alene beviser ikke feedfejl. |
| Høj | Automatisk kandidat giver ikke i sig selv et fuldt risikogrundlag. | ÅBEN: Verificér brugervalgt beløb, stop, antal, valuta/FX og gebyrer i eksisterende flow; mangler vises som manglende data eller blokering. Ingen værdier gættes. |
| Høj | Tidligere rapporter manglede struktureret beslutning; senere gyldig aflevering førte til tre sessioner. `NOT_NEW` og `AWAITING_DISCOVERY` har flere mulige årsager. | DELVIST: Kontrollér alle otte kandidaters individuelle status og at genaflevering efter nulstilling fortsat respekterer stop, identitet og friskhed. |
| Høj | Fire aftenfund mangler ifølge afsenderen præcise nyhedstidspunkter. | ÅBEN: Find uafhængigt verificerbare tidspunkter før fuld Early Catalyst-kvalifikation; ellers manglende data. |
| Før live-test | Mobilnotifikation, samlet kæde ved åbent marked, serverens Pluto-probe og faktisk kapacitet er ikke dokumenteret i denne gennemgang. | IKKE GODKENDT: Udfør kontrolleret test efter ejerens gennemgang; ingen rigtige ordrer under test. |
| Før live-test | Aftalen og radarinstruktionen indeholder dokumenterede forskelle om kandidatloft og rapport-ID. | ÅBEN: Afklar med ejeren før eventuel ændring af mandat eller aftale. |

Behandlede ændringer: `1153f10` om genvurdering efter reset og `8dcc08a` om verificeret Pluto-kontekst findes på udviklingsgrenen; faktisk installeret version og fuld produktionsvirkning skal verificeres. Syntetiske tests beviser ikke live-drift. Se også `PRE_LIVE_REVIEW_20261108.md` for tidligere testresultater og detaljer.
