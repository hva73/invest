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

### Motorjournal — 9. november

Udviklingsversionen registrerer et begrænset antal strukturerede supervisorhændelser i databasen og viser dem sammen med supervisorstatus i `sync_hot_watch`. Journalen indeholder kun fastlagte hændelsestyper og numeriske exit-/signals- eller fejlkoder, aldrig exceptiontekst eller hemmeligheder. En test kontrollerer adgang via MCP og en anden begrænsning og tilladte hændelser. Journalen kan ikke genskabe tidligere hændelser; en brat drab af både supervisor og worker, fejl før databaseadgang eller en databasefejl kan efterlade et hul. Manglende hændelser beviser ikke normal drift. Motorens stopårsag er stadig UKENDT, indtil installeret kode og efterfølgende readback giver evidens.

Produktionsreadback kl. 07.36 viste gentagne `worker_exited` med kode 1 og supervisor `restarting`; det beviser en procesfejl men ikke typen. En ny kodeændring registrerer ubehandlede exceptions som klassekode (1 SQLite OperationalError, 2 IntegrityError, 3 KeyError, 4 ValueError, 5 TypeError, 6 AttributeError, 7 RuntimeError, 8 OSError, 0 anden) samt kendt lokal filkategori og linjenummer, uden fejltekst, variable eller credentials. Diagnose skal installeres og verificeres. HTTP 500 i HOT WATCH-visning er også observeret; rapportopslag lykkedes efterfølgende, men årsagen til fejlen er ikke dokumenteret.

Kl. 07.42 viste journalen gentagne SQLite OperationalError ved `claim` i `hotwatch_engine.py` linje 877–878. Den præcise SQLite-fejlkode kendes ikke fra denne version; låsekonkurrence er en hypotese, ikke en konstateret årsag. Ny kode genforsøger efter de specifikke SQLite BUSY/LOCKED-koder uden at dræbe motoren og journalfører fejlkoden. Andre databasefejl slipper fortsat igennem og får separat numerisk fejlkode i journalen. Test med en faktisk holdt SQLite-skrivelås bestået. Installation, stabilitet og faktisk produktionsårsag skal fortsat verificeres.


### Kontrol efter diagnostikinstallation — 9. november kl. 09.30 dansk tid

Worker har frisk heartbeat; supervisor skifter kortvarigt mellem running og restarting/waiting_for_heartbeat. SQLite BUSY, kode 5, er stadig observeret efter installationen, senest kl. 09.29.53. Den proces eller transaktion, der holder låsen, er ikke fastslået. Den nye per-sessionsdiagnostik har ikke givet en ny klassificeret behandlingsfejl ved denne kontrol; FLYs generelle fejl stammer fra en ældre behandling og må ikke fortolkes som et nyt resultat.

Alle otte kandidater har motorsessioner med dokumenteret instrumentmatch, inklusive MANE og BRK.B, men står DEGRADED uden frisk motorkurs ved kontrollen. MANEs sidst gemte fejl var fra før det dokumenterede match, og BRK.B afventede provider-budget. GMAB havde en frisk tidsstemplet motorobservation og verificeret beholdningskontekst; det er ikke bevis for, at alle exit-sessioner er dækket eller at et exitsignal kan beregnes. NOVOB og LHA havde fortsat forældede observationer. Manglende friske kurser for amerikanske aktier før markedets åbning er ikke i sig selv bevis på feedfejl.

Fortsat åbent: spor SQLite-låsen til den konkrete transaktion; undersøg næste faktiske behandlingsfejl med den nye diagnostik; kontrollér ny indlæsning efter MANEs match og BRK.Bs ratebegrænsning; kontrollér friskhed, kontekst og exit særskilt for alle beholdninger; dokumentér risikogrundlaget og kandidatnyhedernes tidspunkter. Mobilnotifikationer og samlet live-test afventer gennemgang. Ingen ordre oprettet i kontrollen.
