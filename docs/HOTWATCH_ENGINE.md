# HOT WATCH Engine — fase 1–2

Leverance 3. november 2026. Selvstændig, deterministisk observationsmotor til ESCAPE Invest v2.2. **Signaler er ikke ordrer.** Motorens Pluto-klient tillader kun læseværktøjer, også hvis et ukendt værktøj kalder sig read-only. Eksisterende worker og timeautomatisering er bevaret.

## Leverancestatus

| Funktion | Status |
|---|---|
| Persistente sessioner, idempotens, pause/resume/stop, kapacitet | Implementeret |
| Dataidentitet, valuta, timestamps, forældelse, kildeadskillelse | Implementeret |
| Feature-, baseline-, risiko-, anti-noise- og eventmotor | Implementeret og testet med syntetiske data |
| Permanent kandidatjournal og separate handelsforløb | Implementeret; se CANDIDATE_STATUS_MODEL.md |
| Versionsbestemt, begrænset deklarativ strategiport | Upload, opslag, skemakontrol og checksum implementeret; upload er inaktiv |
| Baseline escape_momentum 1.0.0 | Kan vælges ved sessionsstart; ingen dokumenteret profitabilitet |
| Historisk backtest, shadow, kvalifikation, aktivering og rollback af uploads | **Fase 3, ikke implementeret. API returnerer 501** |
| Dashboard, detaljer, alarmer, livscyklusfiltre, strategioversigt | Implementeret; strategiadministration har kun upload og visning |
| EODHD-abonnementsadgang, live feeds og fuld Pluto-datakvalitet | **Ikke verificeret** |
| Produktions-supervisor, belastningstest og notifikationskanaler | Ikke leveret/aktiveret |

Faserne er derfor ikke en fuld godkendelse af hele v1.0-specifikationen. Der udføres ingen køb, salg, ændringer/annullering af ordrer eller pengeoverførsler.

## WIP: kontrolleret hurtigere REST og worker

Historisk WIP-snapshot: EODHD mindst 300 sekunder og én scanning ad gangen. Den aktuelle kode har betingede WebSocket-/fast-feedveje og standard to samtidige scanarbejdere; se [kodeafstemningen](ESCAPE_MASTER_CONTRACT.md). Først efter særskilt driftsgodkendelse og verifikation af feedets rettigheder/kvoter kan operatøren sætte `ESCAPE_HW_EODHD_FAST_POLL_ENABLED=1` samt `ESCAPE_HW_EODHD_MIN_POLL_S` mellem 5 og 300. Profilen har fortsat sit eget mål: NORMAL 60 s, ACTIVE 15 s, CRITICAL 5 s og IDLE 300 s. Et kortere interval beviser ikke, at EODHD leverer friske data. `ESCAPE_HW_PARALLEL_SCANS` kan særskilt sættes til 1–10 og begrænses desuden af `ESCAPE_HW_CONCURRENCY` og kapaciteten; standard er 1. Det globale EODHD-requestbudget håndhæves stadig for hvert kald. Under uændret standard på 12 kald/minut kan 20 kandidater ikke alle opdateres hvert femte sekund.

Samme beskyttede miljøindstillinger skal være tilgængelige for webapp og selvstændig worker. Ingen flag aktiveres, worker startes eller abonnement ændres ved installation. Ændringen af indstillingerne påvirker eksisterende aktive EODHD-sessioners fremtidige scanninger og skal godkendes særskilt. Workerens heartbeat holdes opdateret også under langsomme opslag. Loggen kan skelne EODHD HTTP-tid, Pluto-konteksttid og kildetidsalder; ingen hemmeligheder logges.

Market-status er fortsat UNKNOWN, hvis kilden ikke giver verificerbar status. Risikogrænser og strategi er uændrede; gamle data og ukendt markedsstatus kan stadig give NO_DATA. Ingen WebSocket- eller bid/ask-rettighed er verificeret af disse ændringer.

EODHD REST-opslag fra installationen returnerede `volume`, men ingen `bid` eller `ask` for de afprøvede instrumenter. Volumen lagres nu som kildeoplyst med ukendt periode og vises i sessionsdetaljen; den indgår ikke i interval- eller relativvolumen. Eksisterende observationer ændres ikke ved gentagne tidsstempler. Felternes tilstedeværelse dokumenterer ikke datatidens friskhed eller rettigheder til andre feeds.

Sessionsvisningen indeholder nu separate `data_status`-felter for kurs, marked, momentum, bid/ask og signal. Den gamle `signal`-kontrakt og risikomotoren er uændrede. `DELAYED` bruges kun ved kildeoplyst forsinkelse; ellers markeres en for gammel kurs `STALE`. Tidsændringer for 1/5/15/30 minutter vises kun for faktiske, sammenlignelige observationer med verificeret markedssession og højst 5 sekunders afstand til det pågældende tidsmål. De er visningsmålinger og ændrer ikke handelsstrategien. Separate bid/ask-tider findes ikke i den aktuelle kontrakt og kan derfor ikke verificeres af adapteren.

## Arkitektur og tilstand

`hotwatch_service.py` kører adapter → datavalidering → `hotwatch_features.py` → `hotwatch_strategy.py` (regler, separat risikogate og signalstabilisering) → SQLite-journal i `hotwatch_engine.py`. `hotwatch_api.py` og `static/engine-ui.js` viser resultatet. Backend kræver ingen aktiv ChatGPT-session.

Tilstande: CREATED, VALIDATING, ACTIVE, PAUSED, DEGRADED, EXPIRED, COMPLETED, ERROR. Aktive/pausede sessioner deduplikeres på ejer, testkategori, kandidat og normaliseret formål. Sessioner, valgt strategipayload/checksum og signalstate overlever procesgenstart. Leases på 120 sekunder tillader genoptagelse efter nedbrud. Pause/kill genoptages kun eksplicit.

Markedsobservationer, kontekstændringer, beregninger og hændelser lagres separat. Beregninger inkluderer input-ID'er, algoritme-/feature-/risikoversion, risikogrænser og tidligere signalstate. Ingen retention-sletning er aktiveret; operatøren skal overvåge diskplads og fastlægge en retentionpolitik før større drift. Almindelig API har ingen slet/rediger-historikfunktion. Dette er applikationsmæssig append-only, ikke et kryptografisk eller databaseadministratorsikret arkiv.

## Data og kendte begrænsninger

Ejeren har oplyst **EODHD Active Trader**. Kontoens konkrete rettigheder, forsinkelse, endpointadgang og WebSocket-adgang er ikke testet. Ingen nye tjenester er købt. REST-læseren er som standard deaktiveret. Den kræver både servervariablerne `ESCAPE_HW_EODHD_REST_ENABLED=1` og `ESCAPE_EODHD_API_KEY`, eksplicit `provider_symbol` og `quote_currency`. Nøglen må kun sættes i serverens beskyttede miljø, aldrig i frontend, rapport eller uploadet strategi.

Aktiveringsformularen kan slå kandidatens ticker op via EODHD Search med serverens eksisterende nøgle og fælles requestbudget. Et enkelt match med identisk ticker, selskabsnavn og valuta kan udfyldes automatisk. Øvrige match, inklusive navnebaserede ticker-aliaser, kræver eksplicit instrumentvalg; modstridende eller uoplyst valuta afvises, når Pluto-valutaen er kendt. Søgningen garanterer ikke realtime-rettigheder. I ejerens read-only kontrol 4. november 2026 gav `NOVOB` kun et thailandsk søgeresultat, mens `Novo Nordisk` gav `NOVO-B.CO` i DKK; det fulde navn med skråstreg gav HTTP 404. EODHD-markedskoden og Plutos CHIX-venue bevares særskilt; intet markedsmatch påstås alene ud fra ticker.

EODHD bruger `/api/real-time/{symbol}`. Endpoints med utilstrækkelig instrument-/valutaverifikation afvises; der gættes ikke valuta. Når kursresponsen udelader valuta, bruges sessionens eksplicit angivne instrumentvaluta; dette fremgår af observationens feedtype. En oplyst, modstridende kildevaluta afvises. REST-quote bliver ikke automatisk klassificeret som regular session, tickdata eller en komplet OHLC-bar. Manglende bid/ask, fees, FX, handelsbarhed, position eller markedssession forbliver ukendt. Derfor kan de nuværende produktionsadaptere legitimt forblive NO_DATA/WAIT og er **ikke verificerede komplette input til nye BUY-signaler**. EODHD-adapteren kombinerer ikke selv en Pluto-position med kursen. Kilder lagres separat.

Pluto genbruger eksisterende læsekontrakter og ejede depotsnapshots. Manglende kurstid blokerer kursbehandling, men frisk verificeret positions-/ordrekontekst kan journalføres uden fiktivt kurstidspunkt. INACTIVE-ordreopslag er afgrænset til 50 rækker pr. depot/scope og er **ikke komplet handelshistorik**. Kendte fill-beviser skelnes fra accepterede ordrer; historiske fyldninger uden pålidelig tilknytning lukker ikke et nyt handelsforløb.

Rapport-inbox er afsenderdata og kan ikke alene give nye BUY. Syntetiske data accepteres kun i testkategori via administratorens test-endpoint. De er ikke MERC-markedsdata fra 3. november 2026.

## Frekvens og fejl

Profilernes mål er NORMAL 60s, ACTIVE 15s, CRITICAL 5s, IDLE 300s. Aktuelle adaptergulve er Pluto/EODHD **300s**, rapport-inbox 60s og syntetisk 5s. Hurtige profiler tilsidesætter ikke gulvet. Worker logger event→modtagelse, adapter→journal og provider-/computevarighed, når source event-time findes; ukendt tid forbliver null. Scheduler rykker motorens eksisterende CRITICAL-profil frem uden at ændre signalregler. Frontend opdaterer kun gemt status hvert 15. sekund; det er ikke dataleverandørens feedfrekvens.

Ved seneste dokumentationsreview bruger `capacity()` standard 60 for manglende `ESCAPE_HW_CAPACITY`, fallback 40 ved ugyldig værdi og ingen øvre clamp i funktionen; faktisk serverkonfiguration er ukendt. Concurrency er standard 2 (`ESCAPE_HW_CONCURRENCY`, 1–10). `ESCAPE_HW_REQUESTS_PER_MINUTE` er et kalender-minutbudget, standard 12, maksimum 120; EODHD deler budget på tværs af konti. Budgettet tæller faktiske adapterkald, ikke interne scheduler-claims, og erstatter ikke leverandørens kontraktlige begrænsninger. Hvert eget Pluto-RPC tæller, også initialize/tools. Gentagne identiske quotes skaber ikke nye bekræftelser. Fejl anvender backoff; HTTP Retry-After respekteres. Permanente identitetsfejl kræver manuel kontrol. Udfald giver DEGRADED/NO_DATA, aldrig køb på gamle data.

## Matematik og risiko

Features anvender højst de seneste 120 kronologiske observationer med samme kilde, instrument, valuta, venue, session, markedsfase og interval. Huller/intervalbrud nulstiller vinduet. Decimal-beregninger: intervalafkast, hastighed/acceleration, SMA/EMA, Wilder RSI, MACD, ATR når komplet OHLC findes, volatilitet, range/breakout og spread. EMA er initialiseret inden for det beholdte vindue.

`relative_volume` er forholdet til de foregående ti observerede intervaller i samme session, **ikke historisk tidspunktskorrigeret RVOL**. Kumuleret volumen omregnes kun til forskelle i sammenhængende session. Manglende værdier forbliver null. Bid/ask påstår ikke faktisk købs-/salgspres.

Baseline kræver som standard 34 observationer, momentum, acceleration, volumen, lavt spread/volatilitet, breakout, MACD, trend og RSI; tre bekræftelser, hysterese og cooldown reducerer støj. Se den præcise versionsbestemte baseline i `examples/hotwatch-strategy-baseline.json`. Confidence er et dokumenteret regelscore for datadækning, **ikke sandsynlighed eller afkastprognose**.

Risk Engine kan blokere strategiens BUY uafhængigt af reglerne: friskhed, position, marked, spread, fees/FX, notional, stopafstand/tab og eksponering. Globale lofter er 1.000 DKK notional, 100 DKK hypotetisk stoptab, 1% spread, 120s quotealder og 20% eksponering. Kritisk stop/deadline kan tilsidesætte almindelig cooldown ved friske gyldige input; lukket/pauseret marked bliver PAUSE. Ingen exit kan garanteres eksekverbar. Manglende risikoinput giver ingen ny BUY.

## API og autorisation

Base `/api/v1/hotwatch`. Cookie-login kræver CSRF på POST. MCP/OAuth-bearer kræver nye, eksplicit godkendte scopes `hotwatch:read` (GET) og `hotwatch:manage` (POST). Eksisterende rapportgrants opgraderes ikke automatisk. Alle resultater er ejer-/testisolerede. Rategrænse 120 API-kald pr. minut pr. bruger, JSON højst 128 KiB.

- GET `/schema`, `/providers`
- POST `/activation-requests`: eksplicit batch på 1–20 eksisterende kandidater; `request_id` er idempotensnøgle. Almindelig rapportstatus aktiverer ikke sessioner.
- POST/GET `/sessions`; GET `/sessions/{watch_id}`
- POST `/sessions/{watch_id}/pause`, `/resume`, `/stop`, body `{"is_test":true}`
- GET `/sessions/{watch_id}/signals`, `/metrics`, `/events`, `/history`, `/samples`
- GET `/candidates/{candidate_id}`, `/candidates/{candidate_id}/history`
- GET/POST `/strategies`; GET `/strategies/{id}/{version}`; POST `/strategies/{id}/{version}/validate`
- POST `/strategies/{id}/{version}/backtest`, `/shadow`, `/activate`, `/rollback`: 501, fase 3
- POST `/kill-switch`, body `{"enabled":true,"reason":"..."}`: manuel cookie-admin, denne kontos sessioner i begge kategorier
- POST `/sessions/{watch_id}/samples?is_test=true`: manuel cookie-admin, kun syntetiske testdata

GET bruger `is_test=false|true`, `after=0`, `limit=1..100`, `order=asc|desc`. Kandidathistorik bruger et opakt `before`-cursor i stedet. Brug serverens `next_cursor`. POST sessions har testkategori i body. Fejl indeholder `ok:false`, `code`, eventuelt præcise inputfejl; 401/403 auth, 409 konflikt, 429 budget, 501 udskudt funktion. Kontrakter og eksempel findes i `examples/hotwatch-*.json`.

Strategier har eksakt parameter-/feltliste, whitelistede indikatorer/operatorer, højst 64 regelknuder, dybde 4 og 12 børn pr. knude. Ingen eval, shell eller dynamisk strategiimport. Versionspayloads overskrives ikke. Upload kræver manuel admin, giver inaktiv version og kan ikke tildele produktionssignaler. Runtime-begrænsning er strukturel, ikke en separat proces-sandbox.

## Drift og installation

Installér via det eksisterende `apply_update.py`-flow mens appen er stoppet; genstart derefter. Tag privat SQLite-backup som beskrevet i UPDATE.md. Ved første appstart oprettes tabeller og bagudkompatibel kandidatjournal. Gamle rapportpayloads/digests omskrives ikke. Der startes **ingen HOT WATCH-service automatisk**.

Kør med samme virtuelle Pythonmiljø, database, krypteringsnøgle og OAuth-konfiguration som webappen. Konfigurationsdiagnosen laver ingen netværkskald:

```sh
python hotwatch_service.py --diagnose
```

Ved workerstart logges de konfigurerede dataveje. EODHD-nøgle/feature-flag kan kontrolleres lokalt; abonnementstilladelse og endpointadgang bekræftes først på første almindelige, planlagte læsning. Den læsning registrerer endpointfejl, faktisk kildetid, adaptermodtagelse, journalføringstid og tilgængelige felter. Manglende tid er `null`; ingen delay eller markedsværdi estimeres. Seneste måling vises i provider-health; hver scanning logges struktureret.

Første rigtige feedtest begrænses til én eksplicit valgt session:

```sh
python hotwatch_service.py --once --watch-id <WATCH_ID>
```

Kommandoen bruger den almindelige adapter og gemmer den reelle observation. Kør ikke bred `--once`, hvis andre forfaldne sessioner ikke skal behandles.

Kontinuerlig proces, når hostens tilladelse og supervisor er verificeret:

```sh
python hotwatch_service.py --interval 2
```

En supervisor skal bruge appmappen som working directory, genstarte ved fejl, stoppe med SIGTERM, beskytte miljøvariabler og logadgang samt overvåge heartbeat/disk. cPanel/Passenger alene garanterer ikke en vedvarende worker. **Hostingens understøttelse er ikke verificeret.** Ændr ikke det eksisterende `worker.py`-cronjob. Ingen infrastruktur er bestilt.

Central kill switch for serveroperatøren:

```sh
python hotwatch_service.py --kill-switch on --reason "Datakilde undersøges"
python hotwatch_service.py --kill-switch off --reason "Kontrol afsluttet"
```

Deaktivering genoptager ikke sessioner. Genoptag dem eksplicit efter validering af nye data. Kill sletter ingen historik. Account-kill i UI påvirker kun den aktuelle bruger; den centrale operatørkontrol gælder alle.

## Godkendelse og næste faser

Tests anvender midlertidige databaser, syntetisk MERC, simulerede adaptersvar og browserforløb. Ingen faktisk Pluto-handel eller live EODHD-konto er testet. Fase 3 skal tilføje kausal backtesting med fees/slippage og begrænsninger, shadow-resultater, testkvalifikation, manuelt autoriseret aktivering og versionsrollback. Fase 5 kræver produktionsfeed-verifikation, hostkontrol, belastnings-/recoveryprøver og driftsgodkendelse. Der må ikke markedsføres verificerede handelssignaler før de nødvendige input faktisk er dokumenteret tilgængelige.

Automatisk beholdningsovervågning kontrollerer ét aktiv ad gangen i baggrunden. En frisk og komplet Pluto-beholdning, entydig ISIN/valuta-kobling til EODHD og ledig sessionskapacitet kræves. Kun exit-overvågning startes; en manuelt afsluttet session startes ikke automatisk igen. Fejl og uafklarede koblinger vises på beholdningen og forsøges senere. Sæt ESCAPE_HW_HOLDINGS_AUTOWATCH=0 for at deaktivere automatisk oprettelse. Flere sessioner øger ikke leverandørens kvote; under standardbudgettet på 12 EODHD-kald pr. minut kan intervallerne blive væsentligt længere end 60 sekunder.
