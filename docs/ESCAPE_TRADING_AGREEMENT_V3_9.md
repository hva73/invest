# ESCAPE — fælles aftale for Trading Radar, HOT WATCH, Codex og ESCAPE

**Aftalebaseline:** v3.9 · **Dato:** 2026-11-03 · **Status:** Dokumenteret aftalegrundlag, ikke dokumentation for færdig implementering.

> Dette dokument fastholder de krav og beslutninger, der er aftalt med ejeren. Det er en krav- og acceptkontrakt, ikke en påstand om at alle krav allerede er implementeret. Ved uoverensstemmelse med en teknisk kontrakt skal forskellen synliggøres og afklares med ejeren; ingen part må stiltiende ændre handelsmandater, datakrav eller rapportdækning.

## 1. Ændringskontrol og roller

- **Ejeren** godkender ændringer i aftalemodel, handelsmandater, produktionsinstallation og rigtige handler, hvor godkendelse kræves.
- **Trading Radar/ChatGPT** udfører den godkendte globale scanning, analyser, rapporter, kandidatjournal og præcise statusvisninger. Den må ikke forkorte, improvisere eller stiltiende fravige v3.9.
- **Codex** implementerer og tester kode på WIP, herunder HOT WATCH-motor, adaptere, scheduler, dashboard, kontrakter og regressionstests. Codex må ikke ændre strategi, mandat eller produktion på eget initiativ.
- **ESCAPE-backend** validerer, lagrer og viser rapporter og kandidatjournal; HOT WATCH-motoren er separat fra chatten. Brokerordrer/fills er kun bekræftet af Pluto.
- **EODHD** leverer supplerende markedsdata efter faktisk tilgængelige rettigheder. Pluto er operativ kilde til egne positioner, ordrer og anvendt Pluto-kurs.
- **ESCAPE Trading Lab** er en separat simulation med 100.000 fiktive ESC, aldrig rigtige Pluto-ordrer.

Ingen stiltiende regelændringer. Ændringer kræver eksplicit ejerbeslutning, versionsændring, ændringslog og relevante tests. Manglende efterlevelse skal markeres **FAIL/NOT RUN**, ikke skjules.

## 2. Rapportmodel v3.9 — obligatorisk

- **Timevis rapport** også når datakilder fejler. Detaljerede rapporter kl. **08, 14, 15 og 22 dansk tid**; øvrige timer kortere status, uden at udelade kritiske hændelser.
- **Kl. 22** er en fuld global gennemgang, inklusive **Asien/Stillehavsområdet** og næste handelsdags katalysatorer. Ingen region må forsvinde ved forkortelse.
- Regionsdækning: **Europa/Norden, USA/Canada, Asien/Stillehavsområdet og råvarer/metaller**; suppler med valuta, relevante sektorer og markedsforhold.
- Minimumsbørser: **CO, ST, OL, HE, LSE, US** plus relevante regionale markeder og rotation. Asien omfatter bl.a. **Tokyo, Shanghai/Shenzhen, Hongkong, Sydkorea, Taiwan, Indien, Singapore og Australien**.
- Angiv **OK / FAIL / NOT RUN** pr. relevant marked, datakilde og kritisk trin. Ingen falsk fuldstændighed.
- Discovery skal omfatte **nye** markedsmuligheder og officielle nyheder, ikke kun eksisterende positioner/watchlist eller aktier med størst markedsværdi.
- Katalysatorer: regnskab, guidance, selskabsmeddelelse, M&A, regulatorisk nyhed, finansiering, sektor-/makroændringer. Skeln **bekræftet nyhed / rygte / hypotese** og angiv kilde og tid.
- Op til **5 nye HOT WATCH-kandidater** og op til **3 handlingsrettede forslag**, kun når dokumentationen rækker; **KØB / AFVENT / FRAVÆLG**. Ingen opfundne signaler.
- Rapporten skal vise begge Pluto-porteføljer, samlet status, kontanter, investeret beløb, realiseret/urealiseret P/L, åbne positioner, aktive/afventende ordrer og risici, hvor felterne faktisk kan verificeres.
- For relevante tickere: **dagens +/- %**, **siden sidste sammenlignelige observation +/- %**, pris/valuta, kilde, tilgængeligt tidsstempel, trend og beslutning. Mangler sammenligneligt datagrundlag, vis **—**.
- Særskilt fremhæv beskyttelsesordrer, der ikke er bekræftet aktive, og ordrer uden fill.

## 3. Datadisciplin — ikke til forhandling

1. **Pluto er autoritativ for portefølje, beholdning, kontanter, ordrer, fills og operativ Pluto-pris.** Manglende tidsstempel på Pluto-kursen diskvalificerer ikke i sig selv kursen.
2. **EODHD** er supplement til handler, quotes, spread, volumen, momentum og nyheder; verificér faktisk markedsdato, session, kilde og forsinkelse.
3. **Bland aldrig Pluto- og EODHD-kurser i en 'siden sidst'-beregning.** Kun samme sammenlignelige kilde og instrument/valuta/session; ellers **—**.
4. EODHD EOD/screener-afkast er **sidste afsluttede session**, ikke automatisk intradag. Skeln sidste luk, premarket, after-hours, delayed og faktisk live.
5. Et signal er ikke en ordre. En afsendt ordre er ikke en gennemført handel. Kun brokerbekræftet **FILLED** er fill; 0 filled er ikke solgt.
6. Ukendte eller manglende data er **null/ukendt**, aldrig opdigtet eller erstattet stiltiende med gamle tal.
7. Dokumentér datakvalitet, kildefejl, markedets åbningstid og sammenligningsgrundlag.

## 4. Kandidatjournal og kontinuitet

- Kandidatmængden er unionen af seneste ESCAPE-journal, åbne Pluto-positioner og ordrer, manuelt overvågede tickere og nye fund.
- Identiteter og historik bevares append-only; kandidater slettes ikke blot fordi de mangler i en senere rapport.
- Rapporteret lifecycle: **OPDAGET → ANALYSERES → HOT_WATCH → AFVENTER_TRIGGER → KØBSSIGNAL → ORDRE_AFVENTER → POSITION_ÅBEN → EXIT_WATCH → LUKKET → ARKIVERET**. Analytisk beslutning, motorsignal, sessionsstatus og brokerstatus er forskellige dimensioner.
- Bevar eksisterende kandidater, herunder BLZE, INO, BAYN, TSLA, PHIA, LHA, SALM, MERC, AEHR, LSCC, GRAB, NBIX, HLIT, EVGO, PERI, IDXX, CBRAIN, SCHO, GMAB, MDLZ, PFE og AMD, når de findes i journal/overvågning; dette er **ikke** et automatisk købsmandat.
- Læring og efteranalyse baseres på reelle Pluto-**FILLED** handler, omkostninger, benchmark og opfølgning efter exit. Simulation må ikke sammenblandes med virkelige handler.

## 5. Rapport til ESCAPE — validering og readback

- Læs seneste produktionsrapport og kandidatjournal før ny rapport.
- Brug den aftalte **v2-rapportkontrakt** og stabilt ID-format `escape-hourly-YYYYMMDD-HH00-v2` (København), UTC-genereringstid, regioner, kilder, porteføljer, positioner, ordrer, kandidater og journal.
- Pengefelter som `{amount:"100.40",currency:"DKK"}` eller null. Verifikation `verified/unverified/unknown`; datalatens separat.
- **Valider hele payloaden**, send kun ved bestået validering, og **læs tilbage** fra ESCAPE for at kontrollere ID, version, regioner, positioner og kandidater. Ingen leveringspåstand uden verificeret readback.
- Hvis kontrakten eller integrationen mangler felter: vis **SCHEMA-GAP**. Trunkér aldrig kandidater eller regioner lydløst.

## 6. HOT WATCH — hvad der er aftalt, og hvad der er bevist

- HOT WATCH er en **selvstændig backendmotor**, der kan fungere uden aktiv chat. Sessionsstart kræver et **eksplicit autoriseret API/MCP-kald**; rapportstatus eller UI-visning starter ikke automatisk overvågning.
- Motorens eksisterende deklarative strategi, risikogates og sessions-/datakontrakter må ikke ændres uden særskilt beslutning. Motorens signal er **ikke** en brokerordre eller en automatisk handel.
- Batchaktivering af **20 kandidatsessioner** er syntetisk målt til **36 ms samlet / 21,7 ms i motoren**. Dette beviser kun oprettelse, **ikke** markedsdatadækning eller scanning.
- Senest rapporteret: **46/46 HOT WATCH-tests**, Python-kompilering og `git diff --check` bestået. Aktive adaptere har et rapporteret gulv på **300 sekunder**; EODHD realtime-/WebSocket-rettigheder **ikke verificeret**.
- Næste leverance: **installationsklar implementeringsfil/arkiv**, med præcist fuldt filnavn efter udpakning, afhængigheder, sikker konfiguration, opdaterings-/rollbackprocedure og testvejledning. Ingen credentials i arkivet.
- Codex kan ikke teste kontoens EODHD-rettigheder uden adgang. **Efter kontrolleret installation** tilsluttes eksisterende EODHD-adgang; mål så faktiske observationer, datalatens, scheduler, kvoter og overvågning af op til 20 kandidater.
- Manglende WebSocket-rettighed eller data skal vises som fejl/degradering med dokumenteret fallback, aldrig udgives som realtid.
- **Ingen deployment, ændring af produktionsopsætning eller rigtige handler uden særskilt godkendelse.** WIP er ikke live.

## 7. Acceptkriterier / regelkontrol

En v3.9-rapport kan **ikke** betegnes fuld, hvis et obligatorisk marked (især Asien kl. 22), en region, kildekontrol, journal, porteføljestatus eller validerings-/readbacktrin er sprunget over. Vis i stedet delvis status med konkrete FAIL/NOT RUN.

Regressionstest skal mindst afsløre:
- manglende Asien i kl. 22-rapporten;
- forkert 'siden sidst' ved blanding af Pluto og EODHD;
- fejlagtigt 'solgt' ved `filledQuantity=0`;
- tab af eksisterende kandidater ved ny rapport;
- manglende regioner/positioner ved ESCAPE-readback;
- falsk realtime-claim ved forsinket eller manglende feed;
- utilsigtet broker-write eller produktionsændring fra HOT WATCH;
- fejlagtig sammenblanding af fiktiv Trading Lab og rigtige porteføljer.

**Vigtigt:** Dokumentet alene håndhæver ikke reglerne. Codex skal på sigt indbygge maskinelle kontraktkontroller og tests (Rule Lock), så en ufuldstændig kørsel ikke kan fremstå som godkendt.

## 8. Relaterede dokumenter

- `docs/HOTWATCH_ENGINE_DATA_CONTRACT.md` — eksisterende implementeret sessions- og motor-kontrakt.
- `docs/HOTWATCH_ENGINE.md` — motorens tekniske beskrivelse.
- `docs/END_TO_END_DATA_CONTRACT.md` — eksisterende end-to-end datakontrakt.

**Ændringspolitik:** Nye versioner kræver en dokumenteret ændringsliste, ejerens udtrykkelige godkendelse og opdaterede regressionstests. Uafklarede krav må ikke fortolkes som tilladelse til at ændre strategien.

## 9. Strategivalg i samarbejdet med ChatGPT — tillæg 2026-11-08

Dette tillæg beskriver den aftalte aflevering via en bagudkompatibel, valgfri udvidelse af v2-rapportskemaet. Det giver ikke mandat til at sende ordrer. ChatGPT foreslår en strategi; ESCAPE kontrollerer selv identitet, version, tilgængelighed og kvalifikation. Brugeren bevarer den eksisterende manuelle godkendelse af handelsforslag, og Pluto afgør endelig godkendelse.

For hver kandidat med et strategiforslag skal den strukturerede aflevering indeholde kandidatens stabile ID, foreslået `strategy_id` og præcis `version`, en kort dansk begrundelse, datakilder og deres tidspunkt samt, når relevant, katalysatorens type, offentliggørelsestid og tidspunktet hvor oplysningen blev tilgængelig. Oplys om data er verificerede, ukendte eller mangler, og hvad der mangler for en vurdering. Ingen nyhed, kurs, volumen, spread eller senere observation må fremstilles som kendt før sit faktiske tilgængelighedstidspunkt. Et rapporteret strategiforslag er hverken en ordre, en garanti for afkast eller en tilladelse til at aktivere en ikke-kvalificeret strategi.

ESCAPE skal kunne vise den faktisk anvendte strategi og version samt begrundelsen særskilt fra ChatGPTs forslag. Ukendt, utilgængelig eller ukvalificeret strategi må ikke aktiveres automatisk. Hvis der anvendes et standardvalg, skal fallback og begrundelse vises; eksisterende overvågninger beholder deres fastlåste version. En brugers private strategier er kun tilgængelige for denne bruger. Samtidige eller modstridende signaler må ikke i sig selv oprette konkurrerende ordrer.

**Aflevering og readback:** ChatGPT læser først `get_strategy_catalog`, vælger en konkret kvalificeret strategi, og anfører i kandidatens valgfri `strategy_proposal` felterne `strategy_id`, `version`, `reason`, `proposed_at` og `source_ids`. Et eventuelt `catalyst`-objekt har `kind`, `published_at`, `available_at` og `source_ids`. Kilder skal findes i rapportens kildeliste; offentliggørelse må ikke ligge efter tilgængelighed, og tilgængelighed må ikke ligge efter strategiforslaget eller rapporten. Gamle v2-rapporter uden feltet er fortsat gyldige.

Kør `validate_report`, og ret eventuelle fejl. `send_report` kvitterer for modtagelse med `strategy_proposals` og en kvalifikationsstatus pr. strategiforslag. `session_status=NOT_CONFIRMED` betyder, at kvitteringen ikke dokumenterer en motorstart. Læs rapporten tilbage, og kald `get_hot_watch` med `candidate_id` og korrekt `is_test`. Feltet `strategy_handoff` viser rapporten, den foreslåede strategi, kvalifikation, eventuelt opstartsforsøg og den faktiske sessions fastlåste strategi og status. `CREATED` og `VALIDATING` er ikke dokumentation for friske kursdata. ChatGPT må først sige, at HOT WATCH har overtaget, når readback viser den konkrete session og dens strategi.

En kvalificeret strategi i en aktuel hovedrapport kan overtages af den eksisterende automatiske kandidatmotor, hvis den kører og kontrollen af identitet, marked, datagrundlag, kapacitet og gældende øvrige regler tillader det. Ukendt eller ukvalificeret strategi gemmes som rapportoplysning og blokerer automatisk opstart for kandidaten; der vælges ikke en anden strategi i stedet. Eksisterende sessioner ændres ikke, og en afvigelse vises i readback. Analyse-/testdata starter ikke automatisk driftsovervågning. `get_strategy_catalog` og `get_hot_watch` kræver den relevante læseadgang. Klienten skal genindlæse MCP-værktøjerne efter installation, før udvidelsen kan anvendes.

Early Catalyst er en skabelon til forskning. Den har endnu ingen verificeret live-katalysatorindgang, historisk vinder-/tabertest eller godkendelse til drift. Fiktive eksempler er ikke backtest, og en bestået regelprøve er ikke et købssignal. Globale risikogrænser og eksisterende kontrol af datakvalitet skal gælde uanset strategi.
