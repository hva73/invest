# ESCAPE Invest — velkomst og faste arbejdsinstrukser til Codex

> **Læs dette ved starten af enhver ny Codex-chat eller arbejdssession i dette repository.** Dette er både projektkort, onboarding og ejerens arbejdsprincipper. Formålet er, at ejeren ikke skal gentage de samme aftaler for hver ny agent.
>
> **Status:** 10. november 2026. Dynamiske detaljer (Issues, PR'er, installeret commit, live-sessioner) skal altid genlæses. Denne fil er ikke et bevis på, at et design er installeret, eller at en opgave er færdig.

## 1. Hvad bygger vi?

**ESCAPE Invest** er et globalt, dansk-orienteret Trading Command Center, der hjælper ejeren med at finde *tidlige* markedsmuligheder, verificere dem og følge dem teknisk frem mod en forståelig beslutning. Systemet omfatter:

- **Global Trading Radar / ChatGPT:** løbende discovery på tværs af Norden, Europa, USA, Canada og Asien samt sektor-, råvare- og nyhedsbegivenheder. Særligt nyheder, regnskaber, guidance, eftermarked, premarket, usædvanlig volumen og begyndende momentum.
- **Nåleøjet:** vi søger det lovende signal **før** en stor del af bevægelsen er sket. Kandidater prioriteres efter katalysator, timing, verificerbarhed, likviditet, risici, faktisk handelbarhed og potentiale — ikke kun de største allerede eksploderede vindere. En interessant kandidat kan gå til **EARLY WATCH / AFVENT** før fuld købsdokumentation, men ikke kaldes et risikogodkendt KØB.
- **Pluto Gate:** det præcise instrument og det relevante depot skal verificeres hos Pluto før faktisk HOT WATCH-aktivering eller handelsforslag. Pluto er autoritet for aktiver, depot, ordrer og fills; et accepteret forslag er ikke et fill.
- **ESCAPE HOT WATCH:** vedvarende kandidatsessioner, markedsobservationer via bl.a. EODHD, features, versionslåste strategier, risikogates og konkrete KØB/AFVENT/SÆLG-/EXIT-vurderinger. Kandidat-watch og faktisk beholdnings-exit-watch er **to forskellige formål** og må ikke sammenblandes.
- **Mobil- og desktopapp:** en enkel, flot og hurtig beslutningsflade. Graf og relevante nøgletal før lange forklaringer; tydelige aktuelle datatider; ingen opdigtede kurser. På mobil skal de eksisterende flydende/sticky handlingsknapper forblive synlige også under scroll.
- **Trading Lab:** særskilt fiktiv simulation med 100.000 ESC; aldrig rigtige handler eller produktions-HOT WATCH-writes.

Den logiske kæde er **DISCOVERY → NÅLEØJET → PLUTO GATE → RAPPORT/JOURNAL → HOT WATCH → DATABEKRÆFTET SIGNAL + RISIKO → HANDELSBESLUTNING EFTER GÆLDENDE DEPOTMANDAT/PLUTO → BEHOLDNINGS-EXIT-WATCH**. Tidlige observationer og endelige købs-/salgsbeslutninger har forskellige krav.

## 2. Sådan arbejder vi — ejerens vigtigste instrukser

**Vores succeskriterium er færdige funktioner, der virker — ikke flest mulige planer, prototyper, analyser, kontrollister eller dokumenter.**

1. **Gør opgaven færdig.** Læs relevant kode, forstå den bestående kæde, implementér, kør målrettede tests, ret fundne fejl og aflever én samlet funktionel løsning. Stop ikke efter en analyse, en halv prototype eller et PR, hvis den bestilte og autoriserede opgave også omfatter resten. Arbejd videre inden for den aktuelle sessions faktiske rammer, indtil opgaven er færdig eller en *reel* ekstern blocker kræver ejerens handling. Du kan ikke arbejde asynkront efter sessionens ophør; lad aldrig som om du gør.
2. **Én sammenhængende leverance.** Del gerne arbejdet teknisk op internt, men undgå at aflevere naturligt sammenhængende UX, backend, push, dataflow og tests som en lang række små faser. Integrér og test hele brugerrejsen på én gang. Opret ikke ekstra Issues for dele, der logisk hører til den eksisterende opgave.
3. **Plug and play som udgangspunkt.** Genbrug eksisterende systemer, adaptere, komponenter, konfigurationer, credentials via korrekt secret-håndtering og installationsflow. Minimal manuel opsætning for ejeren. Hvis en betjeningsvej er nødvendig, skal den være enkel og konkret. Undgå nye parallelle motorer, unødvendige afhængigheder, komplekse framework-skift og ekstra dashboards kun for dokumentation.
4. **Ingen 'livrem og seler' uden konkret grund.** Hold dokumentation, formaliteter og statusbeskeder korte. Test og kontroller dér, hvor de faktisk beskytter data, handel, drift eller funktion; stop med at gentage samme dry-run i nye indpakninger, når forholdet er demonstreret. En reversibel GitHub Project-status er ikke en banktransaktion. Prioritér at få fejl rettet og brugerfunktioner færdige.
5. **Tag selvstændigt ansvar inden for mandatet.** Opsøg relevante filer, logik, eksisterende Issues/PR'er og tidligere beslutninger; stil ikke spørgsmål, der allerede er besvaret. Vælg rimelige tekniske standardløsninger uden at bede ejeren om godkendelse af hvert lille skridt. Spørg kun om et *reelt* mandatvalg, nødvendige manglende oplysninger eller væsentlig risiko. Hvis noget er blokeret, beskriv præcist hvad, og gør alt andet færdigt.
6. **Dokumentér resultat, ikke processtøj.** Kort slutstatus: hvad virker, hvilke filer/PR/Issue, tests med resultat, hvad der eventuelt mangler for *faktisk live-accept*. Påstå aldrig LIVE PASS alene på basis af lokalt grønt testresultat. Undgå lange generiske sikkerhedsudredninger og gentagne handoff-rapporter.
7. **Design til daglig brug.** Danske, korte, entydige tekster; farvekodede relevante tal; ingen spamnotifikationer. På telefon er realtidsrelevans og ergonomi vigtigere end tekstmængde. Signalnotifikationer skal kun komme ved en faktisk ny eller væsentligt ændret hændelse; brugeren må ikke blive alarmtræt.

**Vigtigt:** Pragmatisk udvikling ændrer **ikke** ejerens beslutningsret: Codex må ikke på eget initiativ ændre handelsmandat, globale risikogrænser eller strategi, udføre reelle brokerhandler, aktivere nye broker-write-rettigheder eller installere i produktion uden særskilt godkendelse. Bevar secrets, brugerdata og SQLite-database; udfør ikke destruktive ændringer for at spare en test. En *konkret* sikkerhedsrisiko er grund til målrettet kontrol, ikke til at blokere almindeligt arbejde med hypotetiske kontrolrunder.

## 3. Fælles arbejdsflade

- Repo: **`hva73/invest`**. Primær udviklingsgren: **`codex/escape-development`** (genlæs aktuel branche-/PR-status).
- GitHub Project: **`https://github.com/users/hva73/projects/1/views/1`** — én fælles tavle til ChatGPT, Codex og ejeren.
- Arbejdet styres af **eksisterende Issues** med reel status: Backlog / Ready / In progress / In review / Done. Læs det Issue, du er blevet bedt om at løse, inklusive nyeste kommentarer. Opdatér fremdrift og audit på *samme* Issue frem for at skabe dubletter.
- Beskyttet udviklingsgren: ændringer sendes via PR; merge når review/krav faktisk tillader det. Et grønt PR er ikke en produktionsinstallation.
- Projekttavlens automatiske statusbro beskrives i `development/GITHUB_PROJECTS_GENERAL_BRIDGE.md` og Issue **#11**. Tjek **aktuel** aktivering og rettigheder før statusændringer. En gennemført enkeltstående test på Issue #4 er ikke det samme som generel skriveautorisation. Agenternes GitHub-identitet er ikke en pålidelig individuel afsenderidentitet.
- **Issue #1**: samlet masterkontrakt og dokumentationsreview/ajourføring af alle data-, samarbejds-, UI-, Projects- og releaseaftaler. Læs seneste tilføjelse til #1, og hjælp med at holde denne onboarding i sync. **Issue #13**: P0 gentagne SELL-push **og** mobil signalvisning er én integreret opgave. **Issue #14**: SQLite busy/scheduling. **Issue #16**: fremtidigt GitHub Actions → Nordicway SSH-deployment. Andre aktuelle prioriteter og opgavetekster findes på tavlen — genlæs dem i stedet for at stole på dette øjebliksbillede.
- Når chatten bliver fuld: **start en ny**, læs denne fil, gældende aftaler, aktivt Issue, PR-diff og seneste kommentarer. Fortsæt fra faktiske GitHub-artefakter. Kræv ikke genfortælling fra ejeren.

## 3a. GitHub Projects, fælles agentarbejde og automatiseret releasevej

**Målet er én sammenhængende kæde:** Ejer eller ChatGPT beskriver en opgave på Projects → Codex læser den og implementerer → kode gennemgås/testes via Pull Request → godkendt version installeres på Nordicway via GitHub Actions + SSH → system og data kontrolleres på den kørende installation → Issue og Projects opdateres med den faktiske status. Ejerens arbejdsgang skal være **plug-and-play**, uden ZIP-upload, manuel kopiering af 71 filer eller gentagne cPanel-kommandoer for hver release.

### A. GitHub Projects er fælles arbejdsrum
- **Project:** `https://github.com/users/hva73/projects/1/views/1` (`hva73/1`); repo `hva73/invest`, Issues og PR'er er sandhedskilde for opgaver og kode.
- **Arbejdsmodel:** Én konkret opgave pr. sammenhængende funktion i eksisterende Issue, korte løbende resultater/kommentarer på samme Issue, én samlet gennemtestet PR hvor muligt, og Projects-status som arbejdsoverblik. Læs issue-body **og nyeste kommentarer**, for de kan indeholde nyere godkendelser end det oprindelige Issue.
- **Automationsbro #11:** `development/GITHUB_PROJECTS_GENERAL_BRIDGE.md` og workflows i `.github/workflows/` beskriver Issue-kommentar → GitHub Actions → Projects-status → journal/audit/readback. Den godkendte tilbageflytning af #4 til In progress er gennemført og læst tilbage. Den generelle bro er aktiveret og har desuden behandlet Codex’ reelle #11-anmodning med journal og readback. Kontrollér altid aktuel tavlestatus og nyeste Actions.
- **Vigtig statusgrænse pr. 10. november:** Den generelle Projects-statuswriter er aktiv for de eksisterende Issues #1 og #3–#16, med særlig begrænsning på #3; se Issue #11 og brovejledningen. Både Codex’ og ChatGPTs faktiske anmodninger via den generelle writer er dokumenteret på #11; GitHub-identiteten er fælles. ChatGPT og Codex bruger samme GitHub App/brugeridentitet, så påstå ikke, at GitHub kan skelne de to agenter kryptografisk.
- **Rettigheder:** Reversibel Projects-status kan kun ændres gennem en autoriseret og faktisk aktiveret bro. Statusændring er **ikke** tilladelse til merge, deployment eller handel. Ingen unødvendige nye projekter, Issue-dubletter eller parallelle opgaveregistre.

### B. GitHub → Nordicway: ønsket automatisk installation af godkendte versioner
- **Deployment-Issue:** [#16](https://github.com/hva73/invest/issues/16) er den aktuelle tekniske opgave og overdragelse, herunder host, eksisterende scripts og kendte driftsrisici. Læs seneste kommentarer og PR'er; denne onboarding er ikke installationsinstruks.
- **Hosting:** Nordicway/cPanel CloudLinux Setup Python App (Python 3.11), SSH-host `cp14.nordicway.dk`, ekstern SSH-port **33**, bruger `nordicr4`. Produktionsroot `/home/nordicr4/escape_app`; separat Git-checkout `/home/nordicr4/escape_deploy/invest`; eksisterende Python-virtualenv `/home/nordicr4/virtualenv/escape_app/3.11/`. Den installerede `BUILD_COMMIT` og Git-checkout SHA er forskellige snapshots og skal **altid** læses på ny.
- **SSH-forbindelse:** En deploy-nøgle er oprettet/importeret og autoriseret, men **uafhængig verificering af serverens SSH-host-fingerprint og faktisk ekstern nøglelogin var endnu ikke dokumenteret gennemført** ved seneste gennemgang. Supportafklaring skal kontrolleres. Gem aldrig privatnøgle eller tokens i repo, Issues eller chat; brug et begrænset GitHub Actions-secret/Environment efter godkendelse. Anvend ikke blind host-key-accept.
- **Nuværende release:** Produktion har ikke `.git`; en frisk clone i `escape_deploy/invest` er **ikke** en installeret version. Eksisterende `apply_update.py` tager kode-/SQLite-backup og erstatter kendte filer, men **gennemfører ikke alene** fuldt verificeret Passenger/HOT WATCH-stop/genstart, migrationsrollback, dependencies og health/readback. En automatiseret release må derfor ikke bare kalde det eksisterende script og antage LIVE PASS.
- **Mål for plug-and-play:** Et kontrolleret GitHub Actions-workflow, der tager et **specifikt godkendt commit/artifact**, transporterer det til serveren via verificeret SSH, foretager relevant konsistent backup, installerer nødvendige filer/afhængigheder og migrationer, håndterer Passenger samt supervisor/worker, og verificerer kørende version, health, HOT WATCH og rapportstatus. Ved fejl standses flowet med konkret resultat og en afprøvet recovery/rollbackvej. Begræns databaselåsning og unødvendige backups; bevar produktionsdata og nøgler.
- **Aktiveringspolitik:** **Automatisk upload/installation er målet, ikke en påstand om en færdig aktiveret funktion.** Ingen deploy på hvert push/merge til udviklingsgrenen og ingen ændring af produktionsmiljøet uden ejerens udtrykkelige godkendelse. Efter ejeren godkender release-workflow og den konkrete version, skal den manuelle indsats ideelt være én enkel godkendelse/knap, ikke en ny lang installvejledning.
- **Adskillelse:** Projects-automationssecret `ESCAPE_PROJECTS_TOKEN` er ikke en deploynøgle. GitHub Projects-automatik må aldrig i sig selv aktivere produktionsdeployment, brokerordre, nye handelsrettigheder eller ændre risikostrategier.

**Definition af fuldført integration:** Et testet, godkendt end-to-end flow fra Issue/PR til faktisk verificeret kørende version og korrekt status på Projects, med så få brugertrin som praktisk muligt. Rapporter ærligt, hvilke led der er implementeret, testet, aktiveret og godkendt — uden flere selvstændige leverancefaser for én naturligt sammenhængende funktion.

## 4. Teknisk oversigt og dataprincipper

- Python-backend og HOT WATCH-service, SQLite, responsiv JavaScript/PWA-frontend. Centrale filer omfatter `app.py`, `hotwatch_engine.py`, `hotwatch_service.py`, `hotwatch_adapters.py`, `hotwatch_supervisor.py`, `web_push.py`, `static/app.js` og `static/sw.js`. Kontroller altid det *aktuelle* tree og faktiske funktionsnavne før rettelser.
- Hosted hos **Nordicway/cPanel**, bruger `nordicr4`. Produktionsapp under `/home/nordicr4/escape_app/`; adskilt checkout under `/home/nordicr4/escape_deploy/invest` kan anvendes, når det er verificeret. SSH-host `cp14.nordicway.dk` port **33**. Publicér aldrig nøgler, tokens, abonnementspayloads eller kundedata. Verificér uafhængigt serverens SSH-hostnøgle før ny tillid.
- Produktion og checkout er **ikke samme directory**. Eksisterende opdateringsscript `apply_update.py` og `setup_runtime.py` har afgrænsninger: kodetransport/backup er ikke det samme som verificeret restart, migrationsrollback og health. Deployment kræver en udtrykkelig ejerbeslutning og faktisk test/readback efter installation.
- EODHD leverer quotes/trades/OHLCV inden for kontoens faktiske rettigheder; Pluto giver depot-/ordreautoritet og pris, men ikke nødvendigvis en kurstidsstempling. Bland ikke feeds eller tidsstempler uden eksplicit semantik. Gæt ikke priser, volumen, FX, fill eller stopordrer.
- Separér **datafejl**, **manglende signalbetingelser**, **risikoblokering**, **faktisk signal**, **ordreintention**, **ordrestatuser** og **bekræftet fill**. En PRICE/STOP-exit må ikke blokeres af irrelevant fuld købsanalyse.
- Kandidatens `candidate_id`, faktisk `watch_id` og depot+Pluto asset-ID bruges konsekvent; genbrug sessioner, hvor formålet er det samme. Historik bevares; en udeladt kandidat er ikke automatisk slettet. Datakilde-/eventtid bevares, så ingen gammel pris fremstår som frisk.
- Optimer for få egentlige fejl og korrekte kritiske signaler: SQLite-låse, queue-forsinkelser, vedvarende websockets/broker-cache, EODHD-kvoter, mapping og push-deduplikering skal vurderes på reel måling frem for formodninger.

## 5. Dokumenter i autoritetsrækkefølge

1. **`docs/ESCAPE_MASTER_CONTRACT.md`** – samlet indgang, kodeevidens og åbne konflikter; selve ejeraftalen er `docs/ESCAPE_TRADING_AGREEMENT_V3_9.md`.
2. **`docs/ESCAPE_TRADING_AGREEMENT_V3_9.md`** – gældende fælles aftale inkl. senere godkendte tillæg, global scanning, Night Intelligence, risikogrænser og roller. **Læs den før beslutning om strategi/mandat.** Ikke alle beskrevne krav er implementeret.
2. **`docs/HOTWATCH_SAMARBEJDSAFTALE.md`** – konkret radar → Pluto → HOT WATCH → signal → beslutning → exit-flow og grænsen mellem EARLY WATCH og BUY READY.
3. **`docs/END_TO_END_DATA_CONTRACT.md`**, **`docs/HOTWATCH_ENGINE_DATA_CONTRACT.md`**, gældende skemaer og test – faktisk teknisk semantik.
4. **`development/ESCAPE_arkitektur_og_arbejdsmodel_2026-11-10.md`** – vigtig arkitektur-/fejlfindingsguide, men et *arbejdsudkast*, ikke et nyt handelsmandat.
5. **`docs/NOTIFICATIONS_STRATEGY_DA.md`** og relevante aktuelle Issues/PR'er – mobil-push, Strategy Center og igangværende opgaver.
6. **`README.md`** og `docs/STATUS.md` – generel opsætning og funktioner; genlæs live-status og aktuelle commits, da dokumenterne kan halte efter produktion.

Hvis nyere ejerbeslutninger eller aktive driftsinstruktioner afviger fra v3.9 (f.eks. kandidattal, rapport-ID eller radarversion v5.1), **identificér præcis konflikt og få kun det reelle mandatvalg afklaret**. Gør ikke en gammel dokumentgrænse til en skjult teknisk blokering eller ændr den stille.

## 5a. Obligatorisk kontraktmatch før ændringer

**Alle ændringer skal matche den dokumenterede data- og samarbejdskæde.** Start ved `docs/ESCAPE_MASTER_CONTRACT.md` for opdateret kodeevidens og uafklarede forskelle. Ingen agent må optimere én komponent isoleret og stiltiende bryde en eksisterende kontrakt, dataautoritet, livscyklus eller aftalt arbejdsdeling. Læs de relevante filer **og sammenhold konkret input → output → lagring → visning → readback** mod dem, inden du ændrer kode eller påstår, at funktionen er færdig.

**Fast referencesæt — læs efter arbejdets type:**

| Område | Aftaler/kontrakter, der skal matches |
| --- | --- |
| Overordnet aftale, mandat, radar, natdrift, risiko | `docs/ESCAPE_TRADING_AGREEMENT_V3_9.md` inkl. tillæg; `docs/HOTWATCH_SAMARBEJDSAFTALE.md` |
| Fælles dataflow og hver parts ansvar | `docs/END_TO_END_DATA_CONTRACT.md`; `docs/HOTWATCH_ENGINE_DATA_CONTRACT.md`; `development/ESCAPE_arkitektur_og_arbejdsmodel_2026-11-10.md` (vejledende udkast) |
| HOT WATCH-status, sessioner, signaler og drift | `docs/HOTWATCH_ENGINE.md`; `docs/CANDIDATE_STATUS_MODEL.md`; `docs/HOTWATCH_AUTOSTART.md` |
| Strategi, Early Catalyst, risiko og køb/exit | `docs/EARLY_CATALYST_V1.md`; `docs/HOTWATCH_SAMARBEJDSAFTALE.md`; relevante kodekontrakter og regressionstests |
| Rapporter, kandidater, validering og MCP | `docs/REPORT_V2.md`; `docs/REPORT_VALIDATION.md`; `docs/REPORT_INGEST.md`; `docs/MCP_REPORTS.md`; `docs/MCP_DELIVERY.md` |
| Pluto, ordrer, positionsvisning og vurderinger | `docs/PLUTO.md`; `docs/TRADING.md`; `docs/POSITION_ASSESSMENTS.md`; `docs/V2_2_WORKFLOWS.md` |
| Mobil UX, grafer, notifikationer og eksisterende design | `docs/MARKET_CHARTS.md`; `docs/NOTIFICATIONS_STRATEGY_DA.md`; `docs/DESIGN_STATUS_SPEC_V1_DA.md`; `docs/DESIGN_V1_ACCEPTANCE_MATRIX_DA.md` |
| Release, installation og faktisk drift | `docs/UPDATE.md`; `docs/HOTWATCH_INSTALL_TEST_DA.md`; `docs/INSTALL_SIGNAL_FIXES_20261109.md`; relevante Issues/PR'er |

**Match-regel i praksis:** Identificér før kodning de berørte kontrakter og eksisterende tests; implementér derefter hele den sammenhængende funktion i den eksisterende arkitektur; kontrollér de relevante grænseflader og kontraktinvarianter med få men dækkende tests. Bevar `source_ids`, timestamps, `asset_id`, `candidate_id`, `watch_id`, strategi/version, risikostatus og ordre-/fill-semantik, hvor de er relevante. Sikr at skærmbilledet fortæller samme sandhed som motoren, rapporten og Pluto. **Ingen syntetiske live-data, ingen stille fallback og ingen ny parallel status-/signalmotor.**

**Hvis dokumenter er indbyrdes uenige:** Vis den **konkrete** uoverensstemmelse (fil/afsnit/felt og konsekvens), undersøg seneste ejerbeslutning og eksisterende kode/tests, og afklar kun et faktisk mandatvalg med ejeren. Undlad at opfinde en ny regel eller automatisk vælge det dokument, der er nemmest at kode efter. Opdater relevante kontraktreferencer sammen med implementeringen, så dokumentation og løsning fortsat passer. Det er en **kort, teknisk konsistenskontrol**, ikke en ny bureaukratisk analysefase.

**Definition af færdig:** Hele flowet virker og er testet op imod både **aftalerne, datakontrakterne, UI/UX og faktiske readbacks** i det omfang miljøet tillader. Grønne unittests eller en færdig PR er ikke i sig selv dokumentation for LIVE PASS. Ejergodkendt produktion og handler er særskilte handlinger.

## 6. Praktisk startprocedure for ny agent

1. Læs **denne `AGENTS.md`** og det Issue/PR ejeren henviser til.
2. Læs seneste kommentarer, relevante dokumenter og gældende kode for det berørte flow; se efter allerede påbegyndt arbejde og undgå dubletter.
3. Fastlæg **den samlede færdige brugeroplevelse**, ikke et isoleret teknisk delprodukt.
4. Implementér hele opgaven på egen arbejdsgren → passende målrettede tests → ret fejl → PR/review efter grenregler → kort dokumenteret readback. Arbejd videre uden mellemspørgsmål, når mandatet rækker.
5. Stop kun for en faktisk tilladelse/blocker, f.eks. live-deploy eller rigtig brokerordre. Aflever i så fald det færdige, testede arbejde klar til den ene nødvendige beslutning.
6. Kort afslutning til ejeren: **FÆRDIG / KLAR TIL GODKENDELSE / BLOKERET**, link til Issue/PR, hvad der faktisk virker og den ene nødvendige næste handling. Ingen tomme løfter om senere baggrundsarbejde.

**Projektmotto:** *Find det tidligt. Brug rigtige data. Byg det samlet. Gør det færdigt. Gør det enkelt at bruge.*
