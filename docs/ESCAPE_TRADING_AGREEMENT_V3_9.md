# ESCAPE — fælles aftale for Trading Radar, HOT WATCH, Codex og ESCAPE

**Aftalebaseline:** v3.9 med Night Intelligence-tillæg · **Dato:** 2026-11-03 · **Tillæg:** 2026-11-08 · **Status:** Dokumenteret aftalegrundlag, ikke dokumentation for færdig implementering.

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

- **Timevis global scanning og teknisk rapportering** også når datakilder fejler. Brugerrettede rapporter følger Night Intelligence-tillægget i afsnit 2a: ingen rutinerapporter kl. 23–06, kort morgenrapport kl. 07 og normal rapportering kl. 08–22, inklusive udvidede rapporter kl. **08, 14, 15 og 22 dansk tid**. Kritiske hændelser må meddeles straks.
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

## 2a. Tillæg — Night Intelligence Mode

**Gældende fra 8. november 2026. Alle klokkeslæt følger Europe/Copenhagen, inklusive sommer-/vintertid.** Trading Radar arbejder fortsat globalt og scanner hver time døgnet rundt.

### 1. Night Intelligence Mode — kl. 23.00–06.59 dansk tid

Kørslerne kl. 23, 00, 01, 02, 03, 04, 05 og 06 anvendes primært til informationsindsamling og tidlig identifikation af handelsmuligheder.

Prioritér:

- Selskabsnyheder, regnskaber, guidance og børsmeddelelser
- Eftermarkedet i USA og de asiatiske markeder
- Kommende katalysatorer og usædvanlig handelsaktivitet
- Analytikerændringer, sektorbevægelser og relevante rygter
- Verifikation og prioritering af kandidater til næste handelsdag

Bekræftede nyheder, ubekræftede rygter og analytiske hypoteser skal holdes adskilt.

### 2. Direkte overdragelse til ESCAPE

Finder Trading Radar en relevant, Pluto-verificeret HOT WATCH-kandidat om natten, skal den **afleveres til ESCAPE med det samme** via det eksisterende validerede rapport- og overdragelsesflow. Kandidaten må ikke vente til morgenrapporten.

ESCAPE overtager den tekniske overvågning, når en faktisk HOT WATCH-session er aktiveret og verificeret. Manglende aktivering rapporteres som `BLOCKED` eller `UNKNOWN`.

EARLY WATCH er ikke et købssignal, og ingen automatiske handler introduceres.

### 3. Rapportering

Fra kl. 23 til og med kl. 06 sendes **ingen rutinemæssige brugerrettede timesrapporter**. Væsentlige tidskritiske signaler, alvorlige driftsfejl og forhold, der kræver brugerens beslutning, må fortsat meddeles straks.

Teknisk rapportering, kandidatjournal, porteføljekontrol, ESCAPE-opdateringer og HOT WATCH-overdragelse fortsætter uændret.

Kl. 07 leveres en kort **Morning Intelligence-rapport** med nattens vigtigste dokumenterede fund, status på overdragede kandidater og relevante muligheder før europæisk børsåbning.

Fra kl. 08 til og med kl. 22 gælder den normale rapporteringsmodel, herunder de udvidede rapporter kl. 08, 14, 15 og 22.

### 4. Kontinuitet og sikkerhed

Nattens fund skal så vidt muligt gemmes i ESCAPEs eksisterende journal og rapportstruktur, så de kan genbruges ved efterfølgende kørsler. Manglende lagring eller verifikation skal oplyses tydeligt. Der må ikke antages, at information er bevaret, hvis det ikke kan bekræftes.

Alle eksisterende regler om Pluto-verifikation, datakvalitet, risikokontrol, handelsmandater, kandidat-ID'er og readback gælder uændret.

### 5. Forrang

Dette tillæg erstatter alene den tidligere bestemmelse om obligatoriske brugerrettede timesrapporter i tidsrummet 23.00–06.59. Alle øvrige bestemmelser i samarbejdsaftalen bevares.

**Formål:** Udnytte nattens scanninger til mere effektiv research og tidligere kandidatopdagelse uden at forsinke HOT WATCH-overdragelse eller belaste brugeren med unødvendige natrapporter.

Tillægget er aftalegrundlag. Indsættelsen dokumenterer ikke i sig selv, at den kørende radarautomatisering er opdateret eller verificeret.

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

ESCAPE skal kunne vise den faktisk anvendte strategi og version samt begrundelsen særskilt fra ChatGPTs forslag. Ukendt eller utilgængelig strategi må ikke aktiveres automatisk. Early Catalyst er efter ejerens udtrykkelige ønske tilladt som mærket live-test; andre ukvalificerede strategier forbliver blokeret. Hvis der anvendes et standardvalg, skal fallback og begrundelse vises; eksisterende overvågninger beholder deres fastlåste version. En brugers private strategier er kun tilgængelige for denne bruger. Samtidige eller modstridende signaler må ikke i sig selv oprette konkurrerende ordrer.

**Aflevering og readback:** ChatGPT læser først `get_strategy_catalog`, vælger en konkret kvalificeret strategi, og anfører i kandidatens valgfri `strategy_proposal` felterne `strategy_id`, `version`, `reason`, `proposed_at` og `source_ids`. Et eventuelt `catalyst`-objekt har `kind`, `published_at`, `available_at` og `source_ids`. Kilder skal findes i rapportens kildeliste; offentliggørelse må ikke ligge efter tilgængelighed, og tilgængelighed må ikke ligge efter strategiforslaget eller rapporten. Gamle v2-rapporter uden feltet er fortsat gyldige.

Kør `validate_report`, og ret eventuelle fejl. `send_report` kvitterer for modtagelse med `strategy_proposals` og en kvalifikationsstatus pr. strategiforslag. `session_status=NOT_CONFIRMED` betyder, at kvitteringen ikke dokumenterer en motorstart. Læs rapporten tilbage, og kald `get_hot_watch` med `candidate_id` og korrekt `is_test`. Feltet `strategy_handoff` viser rapporten, den foreslåede strategi, kvalifikation, eventuelt opstartsforsøg og den faktiske sessions fastlåste strategi og status. `CREATED` og `VALIDATING` er ikke dokumentation for friske kursdata. ChatGPT må først sige, at HOT WATCH har overtaget, når readback viser den konkrete session og dens strategi.

En kvalificeret strategi eller en eksplicit tilladt Early Catalyst-live-test i en aktuel hovedrapport kan overtages af den eksisterende automatiske kandidatmotor, hvis den kører og kontrollen af identitet, marked, datagrundlag, kapacitet og gældende øvrige regler tillader det. Ukendt strategi eller en strategi uden tilladelse til live-test gemmes som rapportoplysning og blokerer automatisk opstart for kandidaten; der vælges ikke en anden strategi i stedet. Eksisterende sessioner ændres ikke, og en afvigelse vises i readback. Analyse-/testdata starter ikke automatisk driftsovervågning. `get_strategy_catalog` og `get_hot_watch` kræver den relevante læseadgang. Klienten skal genindlæse MCP-værktøjerne efter installation, før udvidelsen kan anvendes.

Early Catalyst er en skabelon til forskning. Live-piloten kan modtage afsenderens kildekontrol, men ESCAPE har endnu ingen uafhængigt verificeret live-katalysatorindgang, historisk vinder-/tabertest eller godkendelse til almindelig drift. Fiktive eksempler er ikke backtest, og en bestået regelprøve er ikke et købssignal. Globale risikogrænser og eksisterende kontrol af datakvalitet skal gælde uanset strategi.


## 10. Strategy Lab — afgrænset genafspilning

Strategy Lab kan sammenligne én til tre versionslåste strategier på op til 240 beregninger, som allerede er gemt for brugerens egen HOT WATCH-overvågning. Hver beregning bruger kun sin gemte observation, dens modtagelses-/beregningstid og den tidsstemplede risikokontekst; ugyldig eller fremtidig information springes over, og beregningsforløbet nulstilles. Aktive sessioner, ordrer og brokerdata ændres ikke. Test og drift holdes adskilt.

Resultatet er signaloptællinger og begrundelser, ikke dokumenteret afkast eller en simulering af handelsudførelse. Fuld historisk warmup, alle øvrige hændelser, nyhedskontekst, omkostninger og spreadhistorik er ikke nødvendigvis dækket, og manglende indikatorer skal vises. Et resultat er ikke automatisk kvalifikation til drift. ChatGPT må ikke omtale genafspilningen som dokumenteret historisk performance eller påstå, at en handel ville være gennemført.

## 11. Early Catalyst v1.0 — brugerens regler og teststatus

Ejeren har beskrevet en versionsstyret Early Catalyst-strategi med et EARLY WATCH-trin og et særskilt BUY READY-trin. Startværdierne er dokumenteret i `docs/EARLY_CATALYST_V1.md` og kan justeres i en privat kladde i Strategy Center. EARLY WATCH er overvågning og giver aldrig i sig selv ordre eller købssignal. Den eksisterende Momentum-version er uændret. Strategien kræver fortsat eksisterende risikogates og endelig særskilt brugergodkendelse i Pluto.

Version 1.0.0 kan efter ejerens ønske vælges som **live-test, ikke historisk kvalificeret drift**: eksisterende leverandør- og motorinput leverer endnu ikke alle nødvendige tidsstemplede nyheds-, aktietype-, Pluto-, referencekurs- og opsætningsbeviser. Den medfølgende datapakke indeholder ikke de fulde historiske tidsserier, historisk bid/ask eller dokumenterede nyhedstider, og femminutterscandles kan ikke alene dokumentere treminuttersændring og 15 sekunders varighed. GOGO, STAK, KRMN, CIIT, Aelis Farma og Air France-KLM har derfor status **NOT RUN / utilstrækkelige data** for historiske aktiveringstidspunkter. Syntetisk regeltest er ikke dokumenteret markedsperformance. ChatGPT skal ikke opfinde de manglende resultater eller hævde, at et signal ville have ført til en handel.


For Early Catalyst er overophedningens reference den seneste verificerede ordinære lukkekurs før handelssessionen. Offentliggøres en katalysator efter luk, anvendes den seneste ordinære lukkekurs før offentliggørelsen. Under en igangværende session registreres også verificeret kurs umiddelbart før nyheden, så dagens samlede ændring og reaktionen på nyheden vises separat. Er kilde eller tidspunkt ukendt, må værdien ikke opfindes.


## 12. Early Catalyst: rapportformat og live-test

ChatGPT finder først en tilladt version med `get_strategy_catalog`. I en v2-kandidats `strategy_proposal` afleveres `strategy_id`, `version`, `reason`, `proposed_at` og `source_ids`. Ved nyhed afleveres `catalyst` med `kind`, `published_at`, `available_at` og `source_ids`. Derudover kan `news_check` indeholde `status` (`verified_news`, `no_verified_news` eller `unknown`), `checked_at` og `source_ids`; `reference_close` og `pre_news_price` indeholder hver `price` (`amount`, `currency`), `observed_at`, `available_at` og `source_ids`. `news_session` kan være `during_regular`, `after_close`, `before_open` eller `unknown`. Samtlige kilder skal findes i rapportens `sources`. Brug `null` eller udelad ukendte valgfrie oplysninger.

Ved `verified_news` kræves en dateret katalysator og mindst én fælles kilde i `news_check` og `catalyst`. For at motoren kan bruge nyhedsvurderingen, skal afsenderen have markeret kilden `verified` med `verified_at`, og kildens `published_at` skal passe til katalysatorens tidspunkt. Kildekontrollen er **ChatGPTs oplysning**; ESCAPE henter ikke uafhængigt nyhedens indhold og skal vise dette. En påstand om `no_verified_news` er også en rapporteret kontrol, ikke bevis for at alle nyheder er undersøgt. Instrumenttype og handelsbarhed skal bekræftes af Pluto. Referencekursen skal desuden stemme med lokalt modtagne providerdata og en gyldig børskalender; et rapporttal alene er ikke tilstrækkeligt. Nyhedens faktiske session bestemmes af børskalenderen, ikke af rapportens label. En pris før nyheden skal kunne genfindes i lokalt registrerede sammenlignelige kursdata. Fremtidige tidsstempler er ugyldige.

Ejerens tilladelse gælder live-test og almindeligt manuelt brugerflow til Pluto. Signaler og EARLY WATCH sender aldrig selv forslag eller handler; brugeren vælger beløb og sender eksplicit til Pluto, som kræver sin egen godkendelse. Testversionen er ikke historisk kvalificeret. Ingen globale risikogrænser eller datakrav lempes. Ukendt nyhedskontrol, utilstrækkeligt spread eller risikodata medfører afventning; overophedning kræver dokumenteret breakout/konsolidering eller ny opsætning efter de aftalte regler. Eksisterende automatiske kandidater har p.t. ikke automatisk verificeret antal, stop, valuta og gebyrer, og derfor kan købssignal blive blokeret med `RISK_INPUTS_UNKNOWN`, selv om analysekriterierne ellers er opfyldt. Dette må ikke beskrives som færdig verificeret ordreproduktion.

ChatGPT kører `validate_report` før `send_report`, læser rapporten tilbage og kontrollerer `get_hot_watch` med kandidat-ID. `qualification=PILOT` betyder kun, at en version er tilladt til ejerens live-test. En gemt rapport eller en oprettet session er ikke bevis for aktuelt signal, en afsendt ordre eller et gennemført køb.

Ved teknisk test skal strategiens vurdering, risikokontrol og manglende data læses hver for sig. `decision_diagnostics` beskriver den seneste beregning, mens den aktuelle status også kan være ændret på grund af forældede data. En frisk verificeret beholdning knyttes til separat exit-overvågning på depot + aktiv. Et accepteret købsforslag på samme aktiv er ikke tilstrækkeligt til at fastslå beholdningens oprindelige kandidat; forbindelsen til det faktiske køb kræver verificeret broker-evidens fra ordreintention til ordre/fill og forbliver ellers ukendt. Accept af forslaget er ikke bevis for en udført handel; fyldning og pris kræver særskilte Pluto-observationer. Exit kan bruge en anden, versionslåst strategi. Opstart af exit, faktisk position, ordrefyldning og et salgssignal må ikke omtales som samme hændelse.

## 13. Verifikationsstatus før samlet live-test — 8. november 2026

Dette er et statusbilag til de eksisterende krav, ikke en ændring af strategi, handelsmandat, risikogrænser eller godkendelsesmodel. Den fulde testmatrix, begrænsninger og udeståender står i [PRE_LIVE_REVIEW_20261108.md](PRE_LIVE_REVIEW_20261108.md). Testet kode er `63b74d6`.

- **Lokalt PASS:** 663 Python-tests, 8 JavaScript-regressionsfiler, købsplanens DOM-test og 15/15 uændrede syntetiske Early Catalyst-scenarier. Regeltest er fortsat ikke historisk performance eller live-accept.
- **Read-only Pluto PASS:** Nye MARKET-estimater og LIMIT-estimater returnerer eksplicitte gebyr-, valuta-, FX- og afregningsfelter. Det rettede probefilter og den eksisterende LIMIT-parser er kontrolleret på disse rigtige svar. Hele probe-kommandoen er ikke kørt på hostingserveren. Ingen ordre, forslag eller server-købsplan er oprettet i testen.
- **Kandidatflow BLOCKED:** Den observerede v5.1-rapport er skemavalid, men HIMS, FLY, LUNR og BRK.B mangler struktureret tidsstemplet beslutning og strategiforslag. Readback viser NOT_NEW uden session; den præcise reset-/currentness-årsag kræver mere motordiagnostik. Ingen sikkerhedsregel er omgået.
- **Drift PARTIAL/UNKNOWN:** Worker-heartbeat er frisk, og 18 exit-sessioner findes. Aktierne har gamle weekendkurser; frisk beholdningskontekst kan ikke bekræftes i motorreadback (`holding_verified=null`). Direkte Pluto-beholdninger er verificeret særskilt. Det er ikke bevis for, at de samme friske input findes i motoren.
- **Resterende NOT RUN:** Strategikatalog og detaljeret motorkontekst er ikke eksponeret i den aktuelle forbindelse; native browser-test er blokeret af miljøet; fysisk mobilpush, server-probekommando og den samlede åbent-marked-kæde er ikke accepteret.
- **Night Intelligence:** Den aktuelle radarautomation indeholder timeplan, natte-mode 23–06, straks-handoff og 07-brief. Konfigurationen er læst, ikke ændret; efterfølgende kørslers efterlevelse skal kontrolleres særskilt.
- **Dokumenteret forskel:** v5.1-instruktionen afviser et kunstigt loft på 3/5 HOT WATCH-kandidater, mens afsnit 2 sætter et loft på 5 nye kandidater; den aktuelle rapports ID afviger fra afsnit 5. Dette er ikke en ændring af loftet for handlingsrettede forslag. Forskellene er ikke stiltiende omsat til nye krav eller ændret mandat.

Samlet live-test afventer fortsat ejerens gennemgang af det konkrete resultat og afklaring af de dokumenterede blokeringer. Ingen globale risikoregler eller krav til manglende data lempes for at kunne skrive PASS.

### Nulstilling og ny vurdering — 9. november 2026

Efter ejerens udtrykkelige valg blev den aktive radarliste nulstillet. Rapporter og historik bevares, og de 18 observerede beholdningssessioner fortsatte. Den installerede version skjuler også efterfølgende rapporter med de gamle kandidat-ID'er; genafsendelse alene genstarter dem derfor ikke. Koderettelsen på udviklingsgrenen tillader samme stabile ID igen, når en ny hovedrapport indeholder en eksplicit, gyldig og tidsstemplet vurdering efter nulstillingen. Kopier uden ny vurdering forbliver skjult. Eksisterende stop-, identitets-, kapacitets- og risikokontroller gælder stadig. Rettelsen er først aktiv efter installation og dokumenteret readback; en gemt rapport er ikke en startet session.
