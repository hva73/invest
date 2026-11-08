# ESCAPE — test og gennemgang før live-test, 8. november 2026

**Samlet resultat: BLOCKED for samlet live-accept.** De lokale kodekontroller består. Der er konstateret mangler i produktionshandoff og utilstrækkelig dokumentation for friske motorinput. Ingen strategi, risikogrænse, produktionskode, kontoindstilling, rapportpayload eller motorsession er ændret under gennemgangen. Ingen ordre eller handelsforslag er sendt.

## Afgrænsning og grundlag

- Testet kode: `63b74d684b39298ea98f0690af1ac27e749b5272`, `codex/escape-development`. GitHubs aktuelle branchhoved blev læst og matchede den lokale kode. Dette er kildekodeverifikation, ikke en ny kryptografisk måling af den installerede serverkode.
- Samarbejdsaftalen, Early Catalyst v1.0, den eksisterende købsplan, kandidataktivering, beholdnings-/exitkobling og installationsvejledningen er gennemgået før dokumentationsændringer.
- Liveopslag var read-only gennem de tilsluttede Pluto-, EODHD-, Endavu- og ESCAPE-forbindelser. Lokale integrationstests brugte midlertidige databaser og broker-mocks.
- Produktions-readback: bl.a. `sync_hot_watch.as_of=2026-11-08T22:47:05.187862+00:00`, senere kandidat-readbacks omkring 22:49 UTC. Den observerede rapport var `escape-radar-v51-20261108-2300-asia-brk-intelligence`, genereret 22:12:04 UTC.

## Kontroller

| Kontrol | Resultat | Faktisk evidens og begrænsning |
|---|---|---|
| Fuld Python-suite | PASS | 663 tests, 64,707 s, i det eksisterende testmiljø med projektets afhængigheder. Første kørsel med system-Python havde én miljøfejl: `requests` manglede. Ingen kodeændring var nødvendig. |
| Kritiske strategi-, købsplan-, handoff- og beholdningstests | PASS | 101 tests, 6,326 s; et målrettet supplement til den fulde suite, ikke 101 yderligere unikke tests. |
| JavaScript-regression | PASS | 8 `tests/test_*.js`-filer. |
| Købsplanens DOM-forløb | PASS | `browser_buy_plan_dom.cjs`: formular, read-only klargøring, fast LIMIT og eksplicit send med udelukkende mockede API'er. Dette er ikke en rigtig Pluto-afsendelse. |
| JavaScript-syntaks, Python-kompilering, whitespace | PASS | `node --check` på statiske JS-filer, `compileall` på relevante Python-moduler, `git diff --check`. |
| Brugerens syntetiske Early Catalyst-pakke | PASS | Uændret `run_in_repo.py` og `scenarios.json` fra den leverede ZIP: 15/15, se nedenfor. |
| Pluto-adgang og beholdninger | PASS for direkte opslag | Ét tilgængeligt hoveddepot, 13 direkte positioner og én Collection med 5 positioner. Collection indgår i hoveddepotets samlede værdi. BTC findes i begge scopes og må ikke lægges sammen til én position. |
| Aktuelle Pluto-ordrer | PASS for læseopslag | MDLZ STOP er `ACCEPTED`, `filledQuantity=0`; det er ikke et salg. Historikken viser separat FILLED MERC-salg og annullerede, ufyldte ordrer. |
| Read-only MARKET-estimater | PASS | PEPE, GMAB og LHA, hver med et diagnostisk testbeløb på 20 DKK. Gebyr-/afregningsvaluta og faktisk FX returneres. `quantity=null` ved beløbsordre er ikke et antal aktier. |
| LIMIT-estimat og købsplan-parser | PASS | GMAB/DKK og LHA/EUR: først beløbsestimat, dernæst beregnet, nedrundet antal og nyt brokerestimat. Eksisterende `hotwatch_buy_plan.quote` og `bounded` accepterede svarene. Ingen plan blev gemt på serveren. |
| Rettet probefilter på rigtige svar | PASS | Den aktuelle `shape()` blev kørt lokalt mod de fulde svar fra nye Pluto-estimater og ordrelisten. `estimate`-omslaget skjuler ikke længere valuta, gebyr og FX-struktur. Kun typer og valutakoder forlader filteret. |
| Hele `pluto_readonly_risk_probe.run()` på hostingserveren | NOT RUN | Ingen adgang til serverens beskyttede lokale appdatabase/OAuth-miljø i denne test. Connector-opslag og lokalt filter/parsercheck erstatter ikke en påstand om, at serverkommandoen er kørt. |
| EODHD | PARTIAL | GMAB.CO, AMD.US og BTC-USD.CC besvares; US-quote giver separate bid-/ask-tider. Aktiekurserne er weekendens historiske data. Ingen realtime- eller åbent-marked-accept. |
| Endavu | PASS som opslag | GMAB-søgning returnerer både dansk almindelig aktie og amerikansk ADR med forskellige ISIN/valuta/MIC. EOD-dato 6. november. Endavu beviser ikke Pluto-handelsbarhed eller et live-spread. |
| Rapportens kontrakt | PASS for skema | `validate_report` på den komplette eksisterende rapport: valid=true, 0 fejl/advarsler, 2 porteføljer, 18 positioner, 28 ordrer, 60 kandidater, 115 kilder, 4 regioner. Ingen rapport blev sendt eller ændret. Skemavaliditet beviser ikke et aktiverbart handoff. |
| Motorproces | PASS for heartbeat | Worker `running`, frisk heartbeat. Komplet liste over 18 åbne beholdningssessioner; 0 kandidatsessioner. Sessionspaginering var fuldstændig. |
| Frisk beholdningskontekst i motoren | UNKNOWN / ikke accepteret | Alle 18 sessioner viste `holding_verified=null`. Pluto-opslagene bekræfter beholdningerne direkte, men dokumenterer ikke, at frisk kontekst er modtaget i hver motorberegning. |
| Exit-adskillelse | PASS lokalt / PARTIAL i drift | Alle 18 observerede sessioner har `watch_kind=holding`, `watch_mode=exit`. Antal og tickerfordeling svarer til 13+5 positioner, herunder 2 BTC-sessioner. Statusadgangen viser ikke requests/depotbindinger; fuld scope- og fill-attribution er derfor ikke nyverificeret i drift. |
| Kandidat til aktiv HOT WATCH | BLOCKED | HIMS, FLY, LUNR og BRK.B findes i rapport/journal, men readback har ingen tidsstemplet struktureret beslutning, ingen strategiforslag og ingen session. `qualification=NOT_SPECIFIED`, `handoff_status=NOT_NEW`. |
| Early Catalyst som faktisk valgt live-strategi | NOT RUN / CAPABILITY GAP | Den nuværende forbindelse eksponerer ikke `get_strategy_catalog` eller detaljeret motorlæsning. `sync_hot_watch` returnerer `detail_level=status`. Ingen kvalifikation eller fastlåst Early Catalyst-version kan derfor nyverificeres via denne forbindelse. |
| Night Intelligence-konfiguration | PASS for instruktion | Den aktive radarautomation har timeplan og eksplicit natte-mode 23–06, straks-handoff, 07-brief og normal rapportering 08–22. Dette beviser konfigurationen, ikke næste kørsels udførelse eller aflevering. Automationen er ikke ændret. |
| Historisk eventaudit | PARTIAL | 1.300 hændelser læst; flere historiske sider findes. Der påstås ikke fuld historikaudit. Lokal pagineringstest og komplet aktuel sessionsliste er separate kontroller. |
| Native browser-regression | NOT RUN / miljøblokering | Den eksisterende profiltest blev forsøgt. Chromium kunne ikke starte pga. `socket() failed: Operation not permitted`. De øvrige native browserforløb blev derfor ikke kaldt bestået. DOM-testen ovenfor er ikke en erstatning for disse. |
| Fysisk mobilpush og samlet åbent-marked-test | NOT RUN | Ingen fysisk iPhone-/Android-leveringstest, frisk aktiequote-kæde, BUY→manuel Pluto-godkendelse eller reel fill/exit-test er gennemført. |

## De 15 syntetiske scenarier

Tiderne er pakkens syntetiske 9. november 2026, dansk tid (UTC+1). De er ikke faktiske signaler fra produktionen. Strategi og forventninger er ikke ændret under denne gennemgang.

| # | Scenarie | Tid | Faktisk signal | Risikostatus | Resultat |
|---|---|---|---|---|---|
| 01 | Nyhed, utilstrækkeligt momentum | 15.30 | WAIT | NOT_EVALUATED | PASS |
| 02 | Første købsbekræftelse | 15.32 | WAIT | PASSED | PASS |
| 03 | Anden købsbekræftelse | 15.34 | BUY | PASSED | PASS |
| 04 | Gebyr mangler | 15.36 | WAIT | MISSING_DATA | PASS |
| 05 | For stort spread | 15.38 | WAIT | BLOCKED | PASS |
| 06 | Nyheden udløbet | 15.40 | WAIT | NOT_EVALUATED | PASS |
| 07 | Pluto-gate fejler | 15.42 | WAIT | NOT_EVALUATED | PASS |
| 08 | Volumen uden verificeret nyhed | 15.44 | WAIT | PASSED | PASS |
| 09 | Overophedning 20 % | 15.46 | WAIT | NOT_EVALUATED | PASS |
| 10 | 20 % og breakout | 15.48 | WAIT | PASSED | PASS |
| 11 | Overophedning 31 % | 15.50 | WAIT | NOT_EVALUATED | PASS |
| 12 | 31 % og ny opsætning | 15.52 | WAIT | PASSED | PASS |
| 13 | Spread mangler | 15.54 | WAIT | MISSING_DATA | PASS |
| 14 | Første trailing-exit-bekræftelse | 15.56 | WAIT | NOT_EVALUATED | PASS |
| 15 | Stop brudt | 15.58 | SELL | NOT_EVALUATED | PASS |

Ingen afvigelser i denne kørsel. Scenarie 05 og 13 var risikostatusafvigelser mod det tidligere `69d1279`; denne kørsel gælder `63b74d6`. Breakout/ny opsætning i pakken er syntetiske input, ikke bevis for et selvstændigt verificeret live-feed.

## Rigtige estimater, uden ordre

| Test | Aktivvaluta | Afregning | Gebyr | FX fra broker | Kvantitet |
|---|---|---|---|---|---|
| PEPE MARKET, beløb 20 | USD | DKK | 0,20 DKK | USD/DKK 6,723231 | null |
| GMAB MARKET, beløb 20 | DKK | DKK | 0 DKK | DKK/DKK 1 | null |
| LHA MARKET, beløb 20 | EUR | DKK | 0 DKK | EUR/DKK 7,489881 | null |
| GMAB LIMIT 3527, antal | DKK | DKK | 0 DKK | DKK/DKK 1 | 0,00567054 |
| LHA LIMIT 8,44, antal | EUR | DKK | 0 DKK | EUR/DKK 7,490188 | 0,31636607 |

LIMIT-antal er afgrænsede diagnostiske beregninger fra det første LIMIT-estimat, ikke et beløb valgt til en handel eller et anbefalet stop. Ingen priser her er live-signaler. Ved antalestimat returnerede Pluto `accountNotional=0`, men `filledAccountNotional=20 DKK`; parseren bruger det eksplicitte afregningsbeløb og kontrollerer konsistens. Det fjerner den konkrete tomme-svar-usikkerhed; det beviser ikke et komplet risikogrundlag for automatisk oprettede kandidater. Aktuelle beløbsestimater leverer stadig ikke et antal eller et stop.

## Udeståender før samlet live-test

1. **Kandidatformat og årsag til NOT_NEW.** Afsenderen skal levere en reel, struktureret `decision` med `status`, `decided_at`, kildehenvisninger og en faktisk næste trigger/friskhed, samt et konkret strategiforslag fra den tilgængelige strategikatalogversion, når Early Catalyst ønskes. Fritekst `signal=OVERVÅG` er ikke den strukturerede beslutning. Genafsend ikke gamle kandidater som nye eller omgå en bruger-reset. Kodens reset-/currentness-gates kan give NOT_NEW; den præcise produktionsgren kan ikke afgøres af statusadgangen alene. Ingen reset- eller stopregel skal lempes for at få testen grøn.
2. **Katalog og motordetaljer.** Kontrollér klientens faktisk indlæste værktøjer og den autoriserede læseadgang. Genindlæs den eksisterende forbindelse efter behov; en ny eller bredere adgang må ikke antages allerede givet. En kandidatreadback skal efter den almindelige aflevering vise konkret `watch_id`, strategi/version og sessionstilstand. Dette er ikke gjort ved at skrive denne rapport.
3. **Frisk brokerkontekst og identitet.** Undersøg serverens egne Pluto-opslag, cachealder og motorens kontekst/diagnostik. Direkte connector-beholdninger må ikke indføres som opdigtede serverobservationer. NOVOB var `unverified`; PEPE havde ukendt kursfriskhed. Begge kræver fortsat særskilt verifikation. To BTC-scopes skal kunne læses og bevises som adskilte depot+aktiv-bindinger.
4. **Brugervalgt købsgrundlag.** Før et handlingsrettet købssignal skal en konkret kandidats beløb/LIMIT, analytiske stop, antal og aktuelle brokeromkostninger være valgt/verificeret via det eksisterende købsplanflow. Mangler noget, er korrekt resultat MISSING_DATA/BLOCKED. Der er ingen tilladelse til at gætte beløb, stop, gebyr eller FX.
5. **Åbent marked og mobil.** Efter ejerens gennemgang: én kontrolleret kandidat, første friske observation, nødvendigt warmup og tidsbekræftelser, risikodiagnostik, separat beholdningskontekst og notification-test på en rigtig telefon. Udvid først derefter inden for den faktisk konfigurerede kapacitet. Rigtige ordrer kræver fortsat særskilt ejerhandling og Pluto-godkendelse.

## Aftale- og instruktionsforskelle fundet

Den aktive v5.1-radar siger ingen kunstig grænse på 3/5 HOT WATCH-kandidater, mens aftalens afsnit 2 stadig siger op til 5 nye kandidater og op til 3 forslag. Aftalens faste `escape-hourly-…`-ID-format svarer heller ikke til den observerede v5.1-rapports ID. Disse forskelle er dokumenteret, ikke stiltiende løst ved at ændre mandat eller kontrakt. Natte-mode er derimod til stede i den aktuelle automation.

**Accept:** Lokale regel- og integrationstests PASS. Leveret rapport skemavalid. Produktionshandoff BLOCKED. Frisk signal-/risiko-/beholdningskæde UNKNOWN/NOT RUN. Samlet live-test er ikke startet, og drift er ikke erklæret klar.
