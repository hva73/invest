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


### Produktionskontrol efter installation — 9. november kl. 07.47 dansk tid

Worker og supervisor viste running med frisk heartbeat ca. 71 sekunder efter seneste registrerede worker-start. Ingen nyere worker-exit var registreret. Dette er en kort kontrol, ikke bevis for vedvarende stabilitet, og den tidligere SQLite OperationalError er endnu ikke identificeret med præcis SQLite-fejlkode. MLYS, HIMS, FLY, LUNR og CABA havde sessioner, men ingen havde en `last_data_at`; MLYS viste `PLUTO_QUOTE_TIME_UNKNOWN` og HIMS `PROVIDER_OR_PROCESSING_ERROR`. Disse datablokeringer skal undersøges uden at slække på friskheds- eller risikokrav. Samlet live-test er ikke godkendt.


### Opfølgning kl. 07.54 dansk tid

Journalen har nu vist `worker_database_busy` med SQLite-kode 5 (`SQLITE_BUSY`) og efterfølgende `heartbeat_timeout` samt genstarter. En konkret fejl i supervisorens tidsberegning er rettet på udviklingsgrenen: 45 sekunders grænse måles fra begyndelsen af et sammenhængende manglende heartbeat, ikke fra workerens oprindelige start. Tests dækker både kortvarigt bortfald og vedvarende bortfald. Årsagen til databasekontentionen er endnu ikke identificeret; installation og længere produktionskontrol af rettelsen afventes. HIMS og CABA har nu gamle kursobservationer, der ikke er friske signaler. Øvrige kandidater har fortsat datablokeringer eller begrænset providerbudget. Risikokontroller og friskhedskrav er uændrede.


### Produktionskontrol 9. november kl. 08.01 dansk tid

Efter installation af heartbeat-rettelsen er worker og supervisor `running` med friskt heartbeat ca. 84 sekunder efter seneste start; ingen efterfølgende stop eller SQLITE_BUSY registreret. Dette er kun en kort observation, ikke bevis for varig stabilitet eller for at databasekontention er fjernet. Syv kandidatsessioner og 18 beholdningssessioner er til stede; alle er DEGRADED. HIMS, CABA og VIR har kun gamle EODHD-observationer; MLYS, FLY, LUNR og MANE mangler Pluto-kurstidspunkt. EODHD-kildegendannelse angiver budgetafventning for MLYS og MANE og utilgængelig US-reference for FLY og LUNR. Direkte read-only EODHD-opslag bekræfter ældre amerikanske data, og Pluto MLYS-svaret indeholder ingen kurstid. Friskhed, identitet og risikogates må ikke omgås. Næste skridt: fortsat stabilitetskontrol, undersøg US-referencens utilgængelighed og budget, og verificér friske markedsdata samt beholdning/exit og risiko før live-test.


### Integration og kapacitet — 9. november kl. 08.11

Produktionsreadback: alle otte rapportkandidater har særskilte motorsessioner. MLYS, HIMS, LUNR, CABA og VIR havde verificeret EODHD-identitet men forældede kursobservationer; FLY afventede kapacitet, MANE og BRK.B havde endnu ikke verificeret mapping. Alle var DEGRADED. Der var 18 separate beholdningssessioner, alle DEGRADED; friskhed og positionstilknytning er ikke generelt dokumenteret. Worker viste frisk heartbeat siden kl. 07.59.55, med et registreret SQLITE_BUSY kl. 08.08 men uden efterfølgende genstart ved kontrollen; længere stabilitet og årsagen til databasekontention er ukendt.

Udviklingsændring: Kandidater aktiveres uden at vente på EODHD-opslag; gyldigt gemt instrumentmatch genbruges, ellers sker identitetskontrol i eksisterende baggrundsflow. Uoverensstemmende valuta, børs eller oplyst ISIN afviser cache. Samtidige identiske EODHD-snapshots genbruges maksimalt fem sekunder inden for samme serverproces og samme credential, med oprindeligt kilde- og modtagelsestidspunkt; fejl caches ikke. Forfaldne exit-sessioner prioriteres i eksisterende kø. US-katalogets transportfejl kan skelnes uden at eksponere credentials. 253 relevante syntetiske/regressionstests PASS. Installeret produktion og friske observationer mangler verifikation; tidssensitiv katalysatorprioritering og batchopslag er ikke fuldt dokumenteret som implementeret. Fremtidig prioritering må ikke opfinde nyhedstidspunkt eller lempelse af risikokrav. Mobil og samlet live-test afventer ejerens gennemgang.


### Kontrol efter installation — 9. november kl. 08.18 dansk tid

Alle otte kandidater og 18 separate beholdningssessioner findes. MLYS, HIMS, FLY, LUNR, CABA og VIR har verificeret EODHD-mapping; MANE og BRK.B er fortsat uverificerede. Aktiekurserne er forældede. BTC-session har modtaget en frisk EODHD-observation kl. 08.18 dansk tid, men den pågældende session havde ikke samtidig verificeret beholdningskontekst; en anden BTC-session havde verificeret beholdning men forældet kurs. Worker og supervisor var running med friskt heartbeat efter opstart; SQLITE_BUSY var registreret kl. 08.17 og forårsagede ingen synlig umiddelbar genstart. Længere stabilitet, årsag til databasekontention, kandidatens friske markedskæde, købsgates, tidskritisk prioritet, batchopslag og exit-sammenhæng mangler stadig produktionsverifikation. Der er ikke sendt ordrer. HTTP-rapportopslag svarede ved kontrollen; tidligere 500-årsag er ukendt.


### Instrumentmapping og kapacitet — 9. november kl. 08.25

Read-only Pluto og EODHD viser samme Berkshire B-aktie under henholdsvis BRK.B og BRK-B; EODHD-søgningen viser ISIN US0846707026. Udviklingskoden understøtter kun sikker punktum/bindestreg-alias med samme klasse og entydig uafhængig US-notering samt matchende EODHD-ISIN. Forkert klasse, modstridende ISIN, manglende ISIN for alias og flere matches afvises. Produktionsmatch kræver installation og normal referencekontrol; det er endnu ikke bekræftet. MANE har fortsat ukendt årsag til VERIFICATION_FAILED; supplerende sikre fejlkoder adskiller database-, felt- og typefejl uden exceptiontekst. Den faktiske EODHD-quoteadapter deler nu samtidige identiske svar i fem sekunder på tværs af sessioner uden at dele brokerkontekst eller ændre kildetider. Ingen fejl caches. 273 regressions- og integrationstests PASS. Batchopslag og eksplicit tidskritisk katalysatorprioritet er fortsat ikke færdigverificerede.

Kl. 08.20 viste én BTC-exit-session samtidigt FRESH kurs og holding_verified=true; senere var konteksten ikke længere frisk. Det bekræfter en tidsafgrænset observation, ikke kontinuerlig exitdækning. Worker havde frisk heartbeat kl. 08.25; databasekontentionens kilde er stadig ukendt. Ingen rigtige ordrer er sendt.


### Samlet MANE-, BRK.B- og køopdatering — 9. november

Read-only Pluto viser MANE som Veradermics på NYSE i USD; Pluto-opslaget giver ikke ISIN. EODHDs søgning og NYSE-referenceliste viser MANE med ISIN US9229671048, og en syntetisk integrationstest med disse observerede metadata bestod gennem den eksisterende uafhængige verificeringsvej. Det er ikke bevis for, at produktionssessionen er verificeret. Årsagen til MANEs hidtidige VERIFICATION_FAILED er fortsat ikke endeligt identificeret.

En potentiel køblokering er rettet: hvis en session får en lease mens dens foreløbige mapping verificeres, udskydes netop genforsøget kortvarigt, så samme række ikke gentagne gange kan blokere andre. Ingen stoppet eller ændret session aktiveres. Tidskritisk Early Catalyst-prioritet for nye automatiske sessioner gælder kun ved tidsstemplet, kildeunderstøttet afsenderpåstand om verified_news og udløber efter den valgte versions nyhedsvindue; den påvirker kun køen, ikke nyhedsverifikation, friskhed, strategi eller købsgates. Exit har fortsat køforrang. 298 lokale regressions- og integrationstests PASS; faktisk produktionsvirkning afventer installation, readback og ejerens efterfølgende gennemgang. Ny batchkurs-API er ikke indført; eksisterende afgrænsede fælles kurscache er bevaret. SQLite-låsenes ophav, mobilnotifikationer og sammenhængende live exit/risiko mangler fortsat.


### MANE og ældre instrumentbeviser — 9. november kl. 08.51

Efter installationen viste MANEs produktionssession EODHD-kurs med gammel observation, men `instrument_match_verified=false`, ingen vist match-evidens og en uændret genkontrolstatus fra kl. 08.09. Den eksisterende recovery håndterede primært Pluto-sessioner uden samples eller EODHD-sessioner med en foreløbig markering. En gammel EODHD-session uden dokumenteret match kan derfor falde uden for begge køer. Den eksakte tilstand i produktionsdatabasen kan ikke læses gennem statusadgangen, så den fulde årsag er ikke endeligt bekræftet.

Udviklingsrettelsen sætter aktive automatiske EODHD-sessioner med manglende, udløbet eller inkonsistent dokumentation i den eksisterende verifikationskø uden at slette historik. Adapter og motor afviser nye handelssignaler indtil et friskt match foreligger; readback viser uverificeret i stedet for at læne sig på en gammel samples verificeringsfelt. Den kræver samme asset, symbol, ticker, valuta, børs og aktuel dokumentation. Nødstop og pauserede sessioner respekteres. Syntetisk test dækker MANEs observerede metadata, historik, genkontrol og fejlagtig valutabinding; 299 regressions- og integrationstests PASS. Installation og produktionseffekt er ikke verificeret.

Kl. 08.47 var worker running med friskt heartbeat og begge BTC-beholdningssessioner viste samtidigt frisk kurs og verificeret beholdningskontekst; begge stod dog DEGRADED. BRK.B manglede fortsat verificeret reference; den amerikanske referencekilde var utilgængelig og providerbudgettet begrænset. SQLITE_BUSY forekommer fortsat, selv om ingen ny workerstart var registreret efter installationen. Længere stabilitet, årsagen til databasekontention, mobilnotifikation og samlet åben-marked-test er fortsat åbne.
