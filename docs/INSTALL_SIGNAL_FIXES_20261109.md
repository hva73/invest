# ESCAPE – signaler, advarsler og kapacitet, 9. november 2026

Status: klar til installation efter lokale tests. Bygger på `659a68ff01cb96c41983c53c4f319699c8e84b4a`. Ingen produktionsændringer eller handler udført under udviklingen. Installation er ikke dokumentation for samlet LIVE PASS.

## Rettelser i denne pakke

- **Exit før fuld købs-warmup:** `hotwatch_strategy.calculate` vurderer de eksisterende exitreglers egne input. Købenes historik-, data- og risikokrav er bevaret. Stopbeskyttelse, bekræftelser, cooldown og signalgrænser er uændrede.
- **Pris og analysehistorik adskilt:** en gyldig markedsobservation gemmes, selv om valgfri medfølgende historik ikke kan bruges. Ugyldig historik indgår ikke i beregningen. Et stop-SELL udløber på sit faktiske pris-/markeds-/beholdningsgrundlag, ikke på en uvedkommende minutbar. Strukturelt ugyldige samples afvises stadig.
- **Aktuel trailing-pris:** kursen sammenlignes med toppen af det faktiske, sammenlignelige analysevindue. Barindikatorer bruger fortsat lukkede bars. Ingen nye trailing-tærskler eller kunstig fastholdelse af SELL. Featureimplementering er mærket 1.1.0; strategier og globale risikogrænser er uændrede.
- **Hurtig polling nulstiller ikke historikken:** ekstra EODHD-handler tættere end analyseintervallet vælges fra i indikatorrækken; faktiske tider og priser bevares. Reelle huller forbliver huller. Delvis verificeret historik kan bruges til regler, hvis nødvendige input faktisk findes. Der opfindes ingen bars eller volumen.
- **JDZG og andre advarsler:** seneste handlingshændelse vises særskilt med tidspunkt, begrundelse og AKTIVT / BORTFALDET / DATA MANGLER. En ikke-kvitteret historisk advarsel bliver i beholdningens opmærksomhedsoversigt. Kvittering journalføres på det konkrete event-ID med bruger-/sessionskontrol og CSRF. Den ændrer intet signal og opretter intet handelsforslag. En ny handlingshændelse er ikke automatisk kvitteret. Historikken bevares.
- **Kortere SQLite-skrivearbejde:** historiklæsning og ren featureberegning forberedes uden for skrivetransaktionen. Under den afsluttende transaktion genkontrolleres lease, session, request, strategi og sampleversion. Ved ændret historik genberegnes; signal, risiko og journal gemmes fortsat atomisk. Ikke-forfaldne account-refresh-checks tager ikke længere en skrivelås.
- **Kapacitet:** standarden er nu 2 scan-workers, begrænset af eksisterende CONCURRENCY. Eksplicitte serverindstillinger bevares. Sessionsloft er fortsat 40 som standard, men en eksplicit `ESCAPE_HW_CAPACITY` kan nu også hæve det; tilknyttede recovery-/batchopslag følger samme værdi. Der indføres ingen ny skjult buffer, og loftet hæves ikke automatisk på serveren.
- **Kalender:** vellykket refresh planlægges efter 60 sekunder frem for 300, så den ikke regelmæssigt falder uden for den eksisterende 120-sekunders gate.
- **Providerforbrug og drift:** `exchange-details` tælles som én dokumenteret API-enhed. HTTP-80 %-reglen er uændret. Eksisterende workerlog bevares privat og roteres ved 1 MiB, højst tre filer. Den indeholder due/claim/poll/ingest-tider samt WebSocket-genbrug, faktisk åbnede forbindelser og afsendte subscriptions. Afslutning af subscribe er ikke bevis for providerens accept. En mislykket capture kan derfor stadig have en åben forbindelse registreret. `sync_hot_watch` viser op til 30 relevante logposter for den pågældende bruger, testkategori og sessionsside samt workerens whitelistede driftsindstillinger. Ingen credentials i loggen.

## JDZG: faktisk aflæsning, ikke antagelse om følsomhed

Produktionsjournalen er læst frem til kl. 19.59 dansk tid. Den indeholder SELL kl. **19.32.39**, DATA_ERROR kl. 19.45.05, WAIT kl. **19.54.30** og nyt SELL kl. 19.56.42. Ved aflæsning omkring kl. 19.58 var JDZG ACTIVE/SELL med verificeret beholdning og frisk kurs.

Der er ikke et journalført WAIT få sekunder efter SELL kl. 19.32.39. Visningen kan derimod gøre signalet utilgængeligt mellem beregninger, når pris, bars, marked eller kontekst udløber. Rå beregningsinput for hver historisk overgang er ikke tilgængelige i den aktuelle forbindelse; den præcise årsag til hvert skærmskift kan derfor ikke fastslås retrospektivt. Vi ændrer ikke tærsklerne ud fra antagelser om støj. Den reproducerede bar-/stopfejl er rettet, og en advarsel forsvinder ikke længere fra beholdningens opmærksomhedsoversigt alene fordi dens aktuelle signal bortfalder.

## Tests

- **809 Python-tests bestået**, herunder nye regressioner for exit-input, trailing/rebound, udløb, gemt ubrugelig historik, samtidighed, ejerskab, CSRF, kvittering, logadgang og uændret ordreantal.
- **13 JavaScript-testfiler bestået**, herunder fælles status/hjælp i begge tabeller og historiske advarsler uden handelsknap.
- Installationstesten bygger en isoleret installation, starter Passenger uden kildecheckout på importstien, kontrollerer modulafhængigheder og bevarer databaseindhold. Ingen nye Python-runtimeafhængigheder i denne pakke.
- Eftertest: 150 sessioner / 4 workers / 0,1 s simuleret provider tog 6,42 s for 150 scanninger og dækkede 149 forskellige sessioner. 40 sessioner / 2 workers / 3 s provider tog 60,74 s og dækkede 34 forskellige sessioner. Gentagne prioriterede exits indgår; et drain-budget er ikke lig med én tur til hver session. Ingen registrerede databasefejl, heartbeat-fejl eller brokerforslag. Det er lokale tests, ikke en kapacitetsgaranti for hostingserveren.
- Med 120 historiske bars pr. session: 150 sessioner / 4 workers / 0,25 s provider gav 150 scanninger på 13,67 s, dækkede 148 forskellige sessioner og havde 46,9 ms p95 for statuslæsning. Maksimal målt ventetid på den fælles databaselås var 51,0 ms; ingen registrerede fejl. Disse tal er også fra lokal simulation.
- Browsertesten er forberedt, men Chromium kunne ikke starte i dette miljø (`socket(): Operation not permitted`). Visning og kliklogik er testet direkte med JavaScript; pixel-/mobilkontrol efter installation står fortsat åben.

## Installation

Brug ZIP for den præcise commit på `codex/escape-development`. Udpak under den eksisterende `escape_app/opdatering`, stop Python-appen, og kør pakkens `apply_update.py` på samme måde som tidligere. Installationsscriptet kontrollerer alle forventede filer, tager privat backup og venter på, at HOT WATCH stopper, før kodefiler udskiftes. Databasen erstattes ikke.

Følg scriptets efterfølgende besked om requirements og `setup_runtime.py`, og start appen igen. Ingen ændring af API-nøgler eller handelsmandater er nødvendig. Genindlæs siden, så ny JavaScript indlæses.

## Det kontrollerer vi efter installation

1. Sitet og HOT WATCH åbner uden HTTP 500. Aktuelle signaler og historiske advarsler vises adskilt; samme event kan kvitteres uden at ændre overvågningen.
2. `sync_hot_watch` viser frisk worker/supervisor, faktisk worker-konfiguration, nye scanlogposter og friske input til sessionernes beregninger. Hvis en eksplicit servervariabel stadig sætter én worker, skal den vurderes ud fra de nye målinger.
3. Mål køforsinkelse, feedgenbrug og SQLite-ventetid på serveren. Bekræft installerede og kørende versioner samt mobilpush. Tidligere målinger identificerer ikke en nuværende SQLite-låseholder. Denne pakke påstår ikke, at alle sådanne produktionsforhold er bevist løst.

Manglende markedsdata, lukkede markeder eller utilstrækkelig faktisk indikatorhistorik kan fortsat give NO_DATA. Det er ikke gjort købsklart med gættede data. Ingen automatisk ordre eller Pluto-handelsforslag introduceres.

## Efterfølgende layoutrettelse – sidemenu

Brugerens skærmbillede efter installation af `050cd0f` dokumenterede, at signaladvarslen lå oven på navigationen. Årsagen var de generelle `aside`-selektorer i `static/style.css`: de ramte både den faste sidemenu og de nye semantiske advarselselementer. Alle ti relevante selektorer er nu afgrænset til `body > aside`. De eksisterende regler er rettet direkte; der er ingen modvirkende position-overrides og ingen ændring i signalberegningen.

`node tests/test_sidebar_scope.js` fejler på CSS fra `050cd0f` og består på rettelsen. Alle 12 `tests/test_*.js`-filer og de 9 installationstests består. Browsertesten kontrollerer nu også advarslernes placering i statusfeltet og fravær af side-overflow. En selvstændig offline-visuel test kan genereres med `node tests/render_signal_layout.cjs`; den bruger de faktiske renderere og CSS med syntetiske data for Overblik og HOT WATCH i 390 og 1280 pixels.

Visuel udførelse af den lokale test er fortsat ikke bekræftet i dette miljø: Chromium-processen får `socket(): Operation not permitted`, og den fælles browser tillader ikke `file:`-URL'er. Loginvisningen på produktion er åbnet; den indloggede fejl er verificeret fra brugerens skærmbillede. Efter installation og genindlæsning skal menuen igen stå frit, og advarslerne skal blive ved de relevante statusfelter.
