# ESCAPE – samlet driftsmodel, dataverifikation og arbejdsbeskrivelse

> **Aktuel læsevejledning:** Dette er et arbejdsudkast, ikke et nyt handelsmandat. Se [samlet kontrakt og kodeafstemning](../docs/ESCAPE_MASTER_CONTRACT.md), aktive Issues og faktiske readbacks for nyere beslutninger.

**Arbejdsudkast til fælles gennemgang med Codex og ChatGPT · 10. november 2026**  
**Grundlag:** `docs/ESCAPE_TRADING_AGREEMENT_V3_9.md` (inkl. Night Intelligence og afsnit 9–16), `docs/HOTWATCH_SAMARBEJDSAFTALE.md`, `docs/HOTWATCH_ENGINE_DATA_CONTRACT.md`, `docs/END_TO_END_DATA_CONTRACT.md` og dokumenterede installationsnotater.  
**Afgrænsning:** Dokumentet er en *foreslået implementerings- og fejlfindingsmodel*, ikke en ændring af gældende aftale, strategi, risikoparametre, rettigheder eller driftsmandat. Den nye fejlrapport i udviklingsroden er **ikke læst** ved udarbejdelsen. Faktiske kode-/produktionsfakta skal verificeres mod den version, der er installeret.

## 0. Formål og succeskriterium

ESCAPE skal opdage relevante muligheder globalt, følge dem med verificerbare data og give **tidlige, forklarlige og anvendelige observationer**. Et formelt BUY/SELL-signal skal fortsat opfylde den versionslåste strategi og alle nødvendige risiko- og handelskontroller. Systemet skal kunne følge eksisterende beholdninger særskilt, også når kandidatens købsovervågning er lukket. Ingen automatisk broker-write fra HOT WATCH.

Succes er **ikke** 50 BUY-signaler eller 50 ACTIVE-sessioner. Succes er, at hver registreret session har:
- en korrekt, stabil instrument- og depotidentitet eller en *præcis* identitetsblokering;
- korrekt tidsstemplet kilde- og markedsstatus uden at opfinde data;
- en teknisk fungerende observation-/beregningsvej eller en konkret, dokumenteret ekstern begrænsning;
- en brugbar forklaring, også når et egentlig handelssignal ikke kan afgives;
- dokumenteret ansvar for kandidat-, positions-, signal- og ordrestatus.

**Overordnet designregel:** *Én autoritet pr. sandhed, én eksisterende kæde, mål kun det relevante, beregn kun på gyldige inputs, vis altid den præcise blokering.*

## 1. Aftale- og beslutningshierarki

1. **Ejerens eksplicitte beslutninger og gældende samarbejdsaftale v3.9 med senere godkendte tillæg** styrer roller, handelsmandat, rapportering og ændringer.
2. **Tekniske, versionslåste maskinkontrakter** (`report_v2`, `report_validation`, `hotwatch_contract`, `pluto_trade_contract`) styrer faktisk accepterede felter, data- og motorsemantik. Afvigelser mellem aftale og skema synliggøres; de gættes ikke væk.
3. **Versionslåste strategier og globale risikogates** styrer formelle BUY/SELL/REDUCE-signaler. Visning eller nyhedsresearch må ikke omgå dem.
4. **Observeret produktion** beviser driftsvirkning; GitHub-commit og lokale PASS-tests gør det ikke alene.
5. **Dette dokument er underordnet ovenstående** og foreslår implementeringsprincipper samt arbejdssekvens. Det autoriserer ikke deployment, ekstra brokerrettigheder eller handler.

**Kendte, udestående aftaleafvigelser:** v3.9 angiver højst fem nye HOT WATCH-kandidater og et bestemt `escape-hourly-YYYYMMDD-HH00-v2`-rapport-ID; nyere radarinstruktion har afvigende kandidatpraksis og rapport-ID. Disse forskelle kræver ejerafklaring før normativ ændring. Samme gælder eventuelle nyere ændringer af driftens sessionsloft, hvis de ikke er særskilt godkendt og verificeret. Ingen tilfældig kodeversion bestemmer alene aftalens indhold.

## 2. Ansvarsfordeling – ingen konkurrerende sandheder

| Ansvar | Kilde/system | Skal producere | Må ikke foregive |
|---|---|---|---|
| Global discovery, katalysator, analytisk KØB/AFVENT/FRAVÆLG | Trading Radar / ChatGPT | Kandidat-ID, kilde og tid, argument, prioritet, strategi-forslag, næste trigger og revurdering | Faktisk brokerfill, motorens aktuelle signal eller uafhængig nyhedsverifikation fra ESCAPE |
| Instrumentklasse, handelsmuligheder, konto, kontanter, beholdninger, ordrer, FILLED og operativ Pluto-kurs | Pluto | Eksakt asset-ID, depot-ID, mængder, status, gebyr-/FX-estimat når tilgængeligt | Dateret markedsfeed når Pluto-kurstid ikke er oplyst |
| Markedshandler, quotes, OHLCV, kalender, volumendata, kilde-/forskydningstider | EODHD | Dokumenterede markedshændelser med korrekt venue/session | Bekræftelse af faktisk Pluto-beholdning eller brokerordre |
| Validering, rapportmodtagelse, historik, kandidater og readback | ESCAPE | Stabil journal, sessionreferencer, korrekte projektioner | At modtaget rapport automatisk er startet HOT WATCH |
| Verificerede observationer → features → fastlåst strategi → risikogates → signal | HOT WATCH | Tidsstemplet matematisk vurdering, separate årsagskoder og revisionsspor | Ordreforslag, automatisk ordre eller et løfte om profit |
| Implementering, relevante tests, sikker installation efter godkendelse | Codex | Dokumenteret rettelse, test, faktisk produktions-readback | At lokalt PASS er live PASS |
| Strategy/Trading Lab | Isoleret simulation | Versionslåste hypotetiske signaler og begrænsninger | Virkelige handler, fills eller dokumenteret historisk profit |

## 3. Den logiske kæde fra nyhed til afsluttet handel

**A. DISCOVERY:** Global radar scanner med aftalt timeplan; natkl. 23–06.59 prioriteres research, eftermarked og Asien. Officiel nyhed / rygte / hypotese holdes adskilt. Tidlig kandidat må opstå *før* fuldt risikogrundlag. Ingen ekstra administrativ research-blokering af verificeret EARLY WATCH.

**B. PLUTO-ID GATE:** `search_assets → get_asset` verificerer entydigt handelsinstrument (asset-ID, ticker, aktivtype, børs/valuta). Ukendt eller flerentydig identitet blokerer **aktivering**, ikke journalføring af interesse. Markedstilgængelighed er særskilt fra instrumentidentitet.

**C. RAPPORT + PERSISTENS:** Læs seneste rapport og journal, valider faktisk v2-payload, afsend gennem godkendt flow, læs den eksakte rapport tilbage. Samme kandidat-ID genbruges ved samme idé/instrument; forskellige depotpositioner og kandidat-watch må ikke sammenblandes. Ingen automatisk sletning ved udeladelse af en kandidat.

**D. AKTIVERING:** Gennem eksisterende autoriseret start/automatisk kandidatflow, ikke gennem en UI-label. Readback kontrollerer konkret `watch_id`, `candidate_id`, `asset_id`, strategi/version, formål og status. `CREATED`/`VALIDATING` er ikke et bevis på friske signaler. Eksplicit stop/pause respekteres.

**E. OBSERVATION:** Adapter verificerer instrumentmapping, kilde/venue, valuta, originale tider og handelsfase. Historiske observationer opbevares, men kildens seneste receive-tid må ikke forny markeds-eventtid. `NO_MESSAGES` betyder ingen ny besked i det observerede vindue, ikke at feed eller instrument permanent er utilgængeligt.

**F. FEATURES + STRATEGI:** Beregn kun features, for hvilke faktisk sammenlignelige data findes. Vurder kun de nødvendige inputs for den relevante regel. Indgang og exit er forskellige regelfamilier; en gyldig stop-/prisbaseret exit må ikke blokeres af manglende indgangs-MACD eller volumebars. Formelle signaler følger fastlåst strategi og alle relevante gates.

**G. HANDELSFORSLAG:** Brugeren vælger beløb/andel. Pluto read-only-estimat verificerer antal, currency/FX, gebyrer, limit og nødvendigt risikogrundlag. En analytisk stoppris er ikke en faktisk stopordre. Kun udtrykkeligt autoriseret forslag sendes til Pluto og brugeren godkender dér. `CONFIRMED/ACCEPTED` er ikke `FILLED`.

**H. POSITION/EXIT:** Faktisk, frisk og komplet Pluto-beholdning i eksakt depot+asset opretter/genbruger separat exit-watch; det er uafhængigt af kandidatens revurderingsfrist og FRAVÆLG. `filledQuantity=0` dokumenterer ikke salg. Ved usikker position behold exit-watch og vis manglende afstemning; luk først ved faktisk komplett brokerbevis.

**I. FEEDBACK/LÆRING:** ESCAPE journalfører event, stabilt ID og datatid. Radar læser ændringer ved næste kørsel; eventuel tidligere notifikation må kun hævdes, hvis kanal er dokumenteret. Efteranalyse følger faktiske fills og efterfølgende sammenlignelige priser; hypoteser og simulation holdes adskilt.

## 4. Kritisk design: Fem *uafhængige* statusdimensioner

Systemet bør danne én let read-only-projektion fra allerede gemte felter; **ikke** en ny statusmotor. Interne API-felter ændres kun gennem aftalt additive/versionsstyret kontrakt.

| Dimension | Eksempel | Hvad den besvarer |
|---|---|---|
| 1. Instrument- og depotidentitet | VERIFIED / UNRESOLVED / CONFLICT | Følger vi præcis det samme værdipapir og den rigtige konto? |
| 2. Marked / execution | REGULAR / PRE / AFTER / CLOSED / HALTED / UNKNOWN + Pluto handel mulig ja/nej/ukendt | Kan aktivet handles gennem broker *nu*? |
| 3. Markedsobservation | frisk verificeret trade, frisk quote-only, historiske bars, stale, no-message, provider-error | Hvad ved vi faktisk om markedet? |
| 4. Matematik og risiko | featureklar, mangler volumen, strategi NOT_MET, confirmations pending, risk blocked, BUY/SELL/WAIT | Hvorfor er/er der ikke et signal? |
| 5. Session/lifecycle/ordre | ACTIVE/DEGRADED/PAUSED; kandidat-review; Pluto PROPOSED/FILLED | Hvad er overvåget, og hvad er faktisk handlet? |

**F.eks.** Et korrekt resultat kan være: `HOT WATCH kører · USA AFTER · frisk BID/ASK kl. 00.38 · sidste trade 00.28 for gammel · momentum ikke klar · WAIT/NO_DATA til formelt køb · Pluto extended-hours SELL ikke verificeret`. Dette er mere nyttigt end én stor rød `DEGRADED`, uden at udstede et falsk signal.

Brugerrettede, afledte *observationstekster* (ikke nye motor-signaler):
- **AKTIV EFTERMARKEDSHANDEL** – frisk verificeret trade, faktisk after-hours.
- **FRISK BID/ASK – SIGNAL AFVENTER** – quotes med egne tider, men utilstrækkelig trade/feature-evidens.
- **INTERESSANT UDVIKLING** – konkret verificeret tidlig katalysator/momentumobservation, men ikke formelt BUY.
- **MARKED LUKKET / DVALE** – kalender verificeret og ingen relevant brokerhandel i øjeblikket.
- **SIGNAL BLOKERET: [præcis årsag]** – manglende obligatorisk datakilde, identitet, datatid eller risikoinput.

Kilde-/handelstid, beregningstid og UI's læsetid er separate. Skeln `DATA_STALE` fra børs lukket; skeln normal signal-`WAIT` fra en teknisk `DEGRADED`.

## 5. Let, korrekt instrumentmatching – verificér én gang og genbrug sikkert

### 5.1 Grundregel

Instrumentets primære nøgle er **Pluto asset-ID i den relevante ejerkontekst**, *ikke* ticker alene. For beholdninger: **(ejer, Pluto depot-ID, Pluto asset-ID)**. En kandidat må have stabilt `candidate_id`, men dens faktiske handelbare identitet bindes til verificeret `asset_id`.

### 5.2 Deterministisk match-hierarki

1. Hent allerede verificeret Pluto asset-ID og metadata. Ret ikke data ved at opfinde et alternativt ticker.
2. Se efter en eksisterende **verificeret** EODHD-link i den eksisterende mapping-cache for samme ejer, asset-ID, valuta, faktisk børs/marked og eventuelt ISIN. Genbrug kun inden for dokumenteret TTL og uden konflikt i nye autoritative metadata.
3. Hvis ISIN findes i begge kilder: kontroller eksakt match og valuta/aktivtype, samt hvilken børsnotering/handelslinje der er tale om. ISIN alene kan dække flere venues/valutaer; kræv relevant venue-link. Hvis et felt er ukendt: markér ukendt, ikke automatisk mismatch.
4. Mangler verificeret cache: ét målrettet metadataopslag hos EODHD og kontroller unik match mod Pluto. Sæt negativ cache/retryfrist på entydige fejl; prøv ikke alle tickervarianter på hvert scan.
5. Ved **identitetskonflikt**: afvis EODHD-kurser for denne sessions signal, journalfør præcis feltdifference, undersøg én gang ved ændret bevis eller planlagt retry; bevar Pluto-positions-watch og tilgængelig brokerkontekst.
6. Ved **provider utilgængelig / manglende adgang**: skeln transport, planrettighed, rate/budget, forkert exchange-symbol, tom session og faktisk ukendt mapping. Forsøg kun sikkert dokumenteret fallback; ingen uverificeret ticker-substitution.

### 5.3 Mismatch er et målrettet diagnostisk resultat

Følgende skal adskilles: `ASSET_NOT_FOUND`, `MULTIPLE_MATCHES`, `ISIN_CONFLICT`, `CURRENCY_CONFLICT`, `EXCHANGE_MISMATCH`, `SECURITY_TYPE_UNSUPPORTED`, `PROVIDER_PERMISSION`, `TRANSPORT_ERROR`, `MAPPING_NOT_ATTEMPTED`, `CACHE_EXPIRED` og `MARKET_CLOSED`. Implementér som eksisterende årsagskoder/projektion hvor muligt; foreslå kun nye felt-/enumtilføjelser efter kontraktreview. Hvis der allerede findes ækvivalente eksisterende koder, genbrug dem. En samlet `UNVERIFIED` uden delårsag er utilstrækkelig for udviklingsfejlfinding.

### 5.4 Pluto-reconciliation

- Hent eller genbrug et **komplet, frisk** depot-snapshot med original broker-kildetid/fetch-tid og observeret resultat.
- Tæl Collections korrekt: root summerer Collection-værdier; individuelle positioner må ikke tælles dobbelt. En position i Collection kan have særskilt salgsmekanisme.
- Bind korrekt depot- og aktiv-ID; sammenlæg ikke beholdninger på ticker alene.
- Status `held`, `none` og `unknown` har forskellig betydning. Et manglende/ufuldstændigt snapshot beviser **aldrig** `none`.
- Ordreintention, godkendelse, åben ordre, delvist fill og faktisk fill er adskilte; delvis fill bevarer faktisk mængde.
- Brokerkontekst kan opdateres uafhængigt af en EODHD-kursfejl, men må ikke gøres til et nyt markeds-event eller forny priser.

## 6. Datamotor: få korrekt signal af de nødvendige data

### 6.1 Første gate: integritet

For hver observation skal validere: kilde, identitet, venue, valuta, faktisk eventtid, received-time, handelssession, feed-type, mulighed for forsinkelse og pris/volumen/bid/ask-integritet. EODHD kan levere både trade og quote; de er separate typer. Kildetider må hverken fornyes med cache eller tidsstemples med genhentningstid. Fravær af ny trade er ikke i sig selv manglende quotes.

### 6.2 Anden gate: brugbar observation

Gem og vis det **faktisk tilgængelige**. Et verificeret, dateret after-hours trade kan vises uden en fuld 34-observationers featurehistorik. En frisk quote-only kan vises uden at påstå ny trade. En historisk OHLC-bar er ikke et nyt live-event; ukendte minutter/intervaller udfyldes ikke. Analytiske sammenligninger bruger kun samme instrument/kilde/venue/valuta/session og passende tidsvindue; ellers `—`.

### 6.3 Tredje gate: features efter behov

Ikke alle signalregler kræver alle features. Vurder en regels *egne* nødvendige input; manglende MACD for indgang må ikke blokere en ellers verificeret stopbaseret exit. Sparsomme bars bevares. Barbaserede perioder tæller reelle bars; tidsbaseret momentum/acceleration kræver korrekt faktisk tidsafstand. Reelle tids- og sessionshuller forbliver huller. Valgfrie historiske bars, som er ubrugelige, må ikke korrumpere en gyldig trade-observation.

### 6.4 Fjerde gate: strategi og risiko

- Aktuel strategi og checksum låses pr. session; ændring kræver version og særskilt ejerbeslutning.
- Formaliserede BUY-signaler følger *den eksisterende* `escape_momentum` eller autoriseret Early Catalyst PILOT; pilotstatus er ikke historisk kvalifikation.
- Køb: anvend faktiske spread/volumen/trend/momentum/confirmations og komplet risikogrundlag når den relevante strategi kræver dem. Aftalte globale loft er max 1.000 DKK notional, max 100 DKK tab, 1 % global spreadgate, 120 s maksimal quotealder, max 20 % positionseksponering; sessionsregler må være strengere. Ingen løsere signal-/risikogates gennem dette dokument.
- Exit: vurder prisbaserede risici uafhængigt af fuld købs-warmup, under den gældende strategis øvrige kontroller. `TRAILING_EXIT` er fald fra analysevindues-toppen, ikke P/L siden køb og ikke faktisk Pluto-stopordre.
- Normal signalbekræftelse, cooldown og kritisk override bevares. Ny quote til samme trade giver ikke en ekstra signalbekræftelse.
- Risikoberegning på beløb kræver brugerens valgte DKK-budget, limit, analytisk stop, faktisk antal, verificeret FX/gebyrer og frisk portefølje-/eksponeringskontekst. Beløbsmangel må ikke forhindre EARLY WATCH eller interessante observationer, men blokerer et fuldt købsklart signal.

### 6.5 Beslutningsdiagnostik frem for bare NO_DATA

Ud fra eksisterende `reason_codes` og `decision_diagnostics` vises i denne rækkefølge: (a) faktisk kilde-/identitetsproblem, (b) manglende specifikt feature-input, (c) strategy NOT_MET og nøjagtig regel, (d) risk BLOCKED og manglende inputs, (e) confirmation pending, (f) endelig handling. Vis flere samtidige årsager, uden at lade status lagres som en ny kilde til sandhed.

## 7. Global kalender, Market Sleep/Wake og budget

**Skel:** Trading Radar skal fortsætte sin aftalte globale nyheds-/katalysatorscanning hver time, også når en bestemt børs er lukket; *kurs-polling for et instrument* kan reduceres, uden at radaren slukkes.

1. Brug verificeret markeds-/helligdagskalender, tidzone og faktisk Pluto-handelsadgang **for relevant session og ordretype**. Plutos støtte til LIMIT/GTC betyder ikke nødvendigvis støtte til extended-hours i det pågældende aktiv; faktisk ordreestimat/afvisning kan være autoritativ evidens om handelsmulighed.
2. Ved verificeret lukket marked + verificeret ingen Pluto-handel i vinduet: sæt unødvendige hyppige **kurskald** i dvale, bevar watch/session, deadline, journal, relevante nyheder og beholdnings-/ordrekontrol. Genoptag automatisk før næste faktiske handelsvindue.
3. Ved åbent marked eller verificeret pre/after med handelsmulighed: relevant profil og risikoprioritet. Ved ukendt kalender/brokerunderstøttelse: reduceret, sikker verifikationspolling, **ikke** automatisk permanent dvale.
4. Eftermarked uden Plutohandelsmulighed kan stadig have *informationsværdi* for kommende åbning, især ved høj-impact nyheder. Anvend en billig, kildedækket research-/observationsfrekvens frem for nul information eller højfrekvent exit-polling.
5. Aktive **ejerpositioner** prioriteres frem for almindelige kandidater, men væsentlige nyheder og genåbning må ikke overses. En kritisk stophændelse er en analyseadvarsel, ikke en automatisk brokerordre.
6. Genbrug fælles exchange-status og kalender på tværs af instrumenter, og EODHD-feed/brokerkontekst inden for faktisk gyldig TTL; cache-hit må ikke opdatere kildetid.
7. EODHD: adskil HTTP-requests/minut, WebSocket-konnektioner/subscriptions og **fakturerede call-enheder pr. UTC-døgn**. Aftalens 80 %-loft er en maksimalt tilladt rutineramme, ikke et forbrugsmål. Eksplicit købt ekstra-buffer må ikke indgå i et automatisk dynamisk dagsbudget uden brugerens override. Ved lav restkapacitet: spar rutineopslag først, bevar kritisk verificering inden for mandat og kapacitet; ingen skjult overskridelse.
8. Budgetstatus skal vise saldo fra EODHD-konto, afstemt lokal forbrugstæller, beregnede enhedspriser, enheder med ukendt pris, andet klientforbrug når identificerbart, forbrugsprognose og sparet forbrug ved dvale. Sparet forbrug er et **estimat**, ikke et faktureret negativt forbrug.

**Vigtig budgetregnskabsregel:** En lokal tæller kan ikke forklare kontoforbruget, hvis andre klienter bruger samme token, eller endpointprisen ikke er kendt. Udvis afvigelsen som uafklaret, ikke som en ekstra motorfejl uden evidens.

## 8. Design til lav latens uden nyt kontrolhierarki

- **Først data, så kontrol** – løbende indsamling og journal er adskilt fra vurdering/godkendelse. Ingen ekstra netkald i en SQLite-skrivetransaktion.
- Del bounded EODHD WebSocket-captures og broker-opslag på tværs af sessioner, når identitet, bruger, feed, marked og friskhed passer. Der må ikke laves én identisk kalender/HTTP-request pr. ticker.
- Hold transaktioner korte og genkontroller lease/session/strategi/sampleversion inden atomisk commit. Ren featureberegning og IO uden for skrivelåsen.
- **Claim forfaldne sessioner efter deadline**, med prioritet til kritiske exits ved sammenlignelige deadlines; undgå at en worker monopoliseres af én langsom kilde. Ved `FEED_COLLECTING`: yield uden at bruge et helt scanbudget, genoptag ved dokumenteret feed completion.
- Dæmp forældede periodiske opdateringer (hvis markedet reelt er lukket) i stedet for at sende mange tomme kald. Genopvågning kræver originale friske observationer.
- Måling: p50/p90/p99 og worst-case for `scheduled → claimed`, `claimed → provider finished`, provider/http/ws, warmup, SQLite-claim/commit, `sample event → receive → decision`, advarselsqueue og brugerens synlige status. Vis både 5-min/1t og region/session; gamle data fra før genstart må ikke forveksles med aktuel effekt.
- Diagnose køophobning gennem faktisk 2-worker occupancy, WebSocket batches og antal overdue; mere CPU/worker-antal alene er ikke en dokumenteret løsning. Låsefejl identificeres via konkret SQLite-resultat og langsom SQL/transaktionssti, ikke blot ved at udskifte journal_mode uden sikker migrationsplan.

## 9. Fejlhåndtering: kontrakt for Codex' systematiske instrumentgennemgang

**Ikke en administrativ rapportøvelse.** Én fælles fejlkategori rettes én gang. Instrumentlisten er en deterministisk kontrolmatrix, som må fyldes via eksisterende read-only APIs og korte GitHub-noter.

### 9.1 Hent et sandt øjebliksbillede

- Aflæs installeret git commit/aktiv serverversion, worker/supervisor heartbeat, faktisk konfiguration, providerbudget og markedsvindue.
- Aflæs alle sessioner med paginering, inklusive pauserede/udløbne efter relevans, og kategorisér **entry vs exit, verified vs unknown identity, source, market, last error, last signal**.
- Aflæs Pluto-beholdninger med komplette snapshots inklusive Collections og åbne ordrer, uden broker-write. Kontroller faktiske typer/tider i data frem for antagne skemafelter.
- Tilknyt en stabil kort fejlgruppe, ikke en separat lang opgave pr. ticker.

### 9.2 Ét instrument ad gangen – spor indtil første reelle brud

Kontrolsti `owner/depot → Pluto asset-ID → Pluto instrument+trading modes → eksisterende EODHD-link (ISIN/venue/valuta) → kalender/session → EODHD trade/quote/bar med original eventtid → validering → eksisterende feature-resultat → fastlåst strategi → relevant risk/confirmation → session/readback/UI`.

For hvert led gem kun **verificeret ja/nej/ukendt, original tid, konkret fejlkode og kilde**, samt hvilken allerede eksisterende funktion der tager beslutningen. Stop ikke fejlsøgningen ved et generisk `NO_DATA`; spor til første konkrete blokering. Men stop dyre gentagne provideropslag, når ret/market-session er legitimt utilgængelig.

### 9.3 Klassificér årsagen

- **KODEFEJL:** bevist forkert match, parsing, cache, timing, sessionopdeling, featureberegning, risiko-/UI-projektion, concurrency eller SQL.
- **EKSTERN DATABEGRÆNSNING:** faktisk ingen handler, lukket venue, ukendt providerrettighed, autoritativ afvisning, lav likviditet, udløbet datakilde.
- **FORRETNINGS-/STRATEGIBLOKERING:** signalregel ikke opfyldt; risiko kræver valgte antal/stop/FX/omkostning; kandidat mangler gyldig revurdering.
- **ADGANG/DEPLOY-BLOKERING:** utilgængelige værktøjer/permissions, `Session terminated`, manglende server-readback eller forskel på WIP/live.

Kun første kategori er nødvendigvis en kodefejl. Andre kategorier skal vises med den konkrete årsag og eventuel godkendt fallback, ikke forsøges skjult.

### 9.4 Fix/test/verify-loop

1. Reproducer fejlen isoleret med faktisk minimal sample eller redigeret, redigerbar **syntetisk** fixture, hvor alle data tydeligt er testdata.
2. Identificér præcis fil/funktion og *første* årsag; skeln bevist årsag fra hypotese.
3. Lav mindst mulige generelle rettelse i eksisterende kode. Aldrig en ticker-specifik hardcode for at få status grøn.
4. Kør fokuseret regression/negative cases for identitet, tid, valuta, marked, manglende data, risiko og idempotens, samt relevant eksisterende testsuite. Ingen rigtige ordrer eller forslag.
5. Genkontrollér alle berørte instrumenter i read-only mode og installér kun efter separat godkendelse og sikker installationsprocedure.
6. Læs installeret commit tilbage, gentag konkret readback på server med den oprindelige fejlfixture/virkelig observation. Først **her** kan produktionsfejlen lukkes som `LIVE VERIFIED`.
7. Fortsæt med næste uafhængige fejlgruppe uden at vente på unødvendig dokumentation eller feedbackrunde.

### 9.5 Minimal række pr. instrument

`instrument | watch_mode | Pluto asset-ID | depot | match-status | feed/session | last trade age | last quote age | broker context | actual strategy/risk state | first blocker | classification | corrected? | test | production readback`

Undgå at kopiere rå tokens, personoplysninger, fulde market-payloads eller lange logs ind i GitHub. Mærk hele listen `snapshot as of ...`; den ændrer sig med markedet.

## 10. Hvad der skal testes, før man ændrer BUY-filtret

Mål strategien **før** justering:
- antal sessioner med gyldigt instrumentmatch;
- antal med frisk trade, frisk quote-only og sammenlignelige data i relevant session;
- antal med fuldt nødvendige features for den valgte strategi;
- antal med strategiske kriterier MET/NOT_MET/UNKNOWN og *første + samtlige* blokeringer;
- antal med komplet risiko-/beløbsplan;
- antal med confirmations pending, formelt BUY, formelt SELL og afventning;
- tid fra verificeret nyhed/trigger til første observation og til eventuelt formelt BUY;
- kursreaktion efter observation, kun med sammenlignelige faktisk observerede priser, uden look-ahead.

**Kun hvis** data- og motorfejl er rettet og disse mål viser, at en konkret eksisterende strategi konsekvent signalerer for sent, kan en *separat* versioneret strategi foreslås til Strategy Lab/simulation og ejerbeslutning. Ikke ændre baseline live for at øge antallet af grønne kort.

## 11. Testmatrix og accept – kompakt men seriøs

| Test | Bevis for PASS | Typisk negativ case |
|---|---|---|
| Instrument-ID | Entydig Pluto asset og verificeret EODHD-link når krævet | Samme ticker, forskellig venue/valuta; modstridende ISIN |
| Broker-reconciliation | Faktisk ejer/depot/asset/quantity og komplet snapshot | Delvis data, forkert Collection, null-mængde |
| Sessionshåndtering | Én genbrugt kandidat-watch; separat exit-watch | Dublet, pauseret session genstartes, exit lukkes ved FRAVÆLG |
| Rapport | v2 validate → send → readback, inkl. historik | Ændret payload med samme ID, udeladt region/kandidat |
| Daterede data | Event/received/quote/status times bevares | Fresh cache mod gammel eventtid, trade/quote blandes |
| Markedsfaser | Faktiske REGULAR/PRE/AFTER og kalender | Forkert session eller extended-status uden verificering |
| Sparsomme bars | Rigtige intervaller og indikator-tid | Opfundne minutter, forkert relative volume |
| ENTRY | EARLY WATCH uden køb; BUY først ved krav opfyldt | Ukendt stop/FX/spread/confirmations giver falsk BUY |
| EXIT | Faktisk stop/exit med egne input | Manglende MACD blokerer gyldig stop-exit |
| Ordrestatus | Kun Pluto FILLED afslutter faktiske fill | ACCEPTED eller 0 filled påstås solgt |
| Scheduler | Prioriterede forfaldne jobs uden unødig kø | 50 sessioner/2 workers, providerforsinkelser, FEED_COLLECTING |
| Market Sleep | Marked lukket reducerer kursopslag, vågner korrekt | Ukendt kalender eller event bliver ignoreret |
| Budget | Aflæst API-tæller vs lokal faktisk forbrug, nødreserve uden autooverride | 5-enheds-kald behandles som 1; 00 UTC-døgnforvirring |
| Push | Ny action giver én advarsel, stale/WAIT nulstiller ikke episode | SELL→NO_DATA→SELL spam, kritisk event mistes |
| Drift | Installeret commit, live worker, konkret readback | WIP lokalt PASS udlægges som live |
| Isolation | Ikke-test kan ikke bruge syntetisk feed; tenant-scope | Cross-account-data, rigtige handler i lab |

**Acceptrapport:** Kodeændringer: `PASS/FAIL/NOT RUN` med kommando+commit; integration: reelle read-only svar; produktion: version+eventtid+sessionreadback; mobilpush/visning: separat test. Ingen `LIVE PASS` for en gruppe uden relevant installeret evidens. Dæk alle berørte sessioner, men udskriv kun afvigelser og totalsummer.

## 12. Arbejdsrækkefølge for Codex – hvad giver mest nytte?

**Fase 1: Stabilt sandhedsgrundlag.** Fastslå installeret commit, værktøjsadgang, sessioner, faktiske markedsvinduer og budgetstatus. Løs `Session terminated`/manglende forbindelse før skjulte antagelser om live.

**Fase 2: De fælles brud.** Gruppér instrumenter på første defekte gate. Ret mapping- og brokerkontekst-/timestampfejl i fælles kildelag; ingen ændring af strategitærskler.

**Fase 3: Data uden falsk NO_DATA.** Skab brugbar observationstekst fra korrekt trade/quote/bar/status, også når formelt BUY endnu ikke er gyldigt. Bevar præcis skel mellem `DATA_STALE` og manglende strategisk trigger.

**Fase 4: Intelligent lav belastning.** Del feed og metadata, gør kurs-polling sessions-/kalenderbevidst, beskyt 80 %-dagsloftet og ejernes exit-watch, mål besparelse/latens.

**Fase 5: Signal-kvalitet.** Dokumentér featureklarhed, risikoblokeringer, signaltiming og relevante ændringer over tid. Brug Strategy Lab til alternative tærskler *før* en eventuel ny ejerbeslutning.

**Fase 6: Installation og lukning.** Fokusregression → ejerautoriseret deployment → faktisk serverreadback → kort fejloversigt, identifikation af resterende eksterne blokeringer og næste uafhængige fejlgruppe.

Alle faser kan gennemføres med eksisterende modulgrænser; kun dokumenterede kontrakt-/API-huller må føre til små additive udvidelser. Ingen ny parallel handels- eller statusmotor.

## 13. Tre eksempler på korrekt ende-til-ende-opførsel

### A. JDZG: tynd eftermarkedshandel
- Pluto-position (antal + konto) verificeres uafhængigt af EODHD-trades.
- En verificeret eftermarkedshandel og bid/ask får separate tider og kan vises, selv hvis historik er utilstrækkelig.
- En reel exitberegning kræver dens egne dokumenterede input; `SELL` er råd/advarsel, **ikke** solgt.
- Hvis Pluto ikke understøtter extended-hours SELL for aktivet, vis `BROKER EXECUTION NOT AVAILABLE` (eksisterende semantisk ækvivalent) og næste mulige handelsvindue, men behold overvågning og journal.

### B. MANE: `sample_id_conflict`
- Find hvilket *samme* immutable sample-ID og eventtid, der optræder med forskellige prisværdier.
- Dokumentér begge payload-hashes/prisfelter/kildetyper, originale tider og konfliktsted, uden tokens.
- Afvis konfliktende sample og bevar historien. Genforsøg først på en ny gyldig observation efter kontrolleret cadence; undgå evige identiske retry-payloads.
- Først luk fejlen, når en faktisk ny korrekt prøve er accepteret i produktion; `DEGRADED` alene er ikke årsagsforklaring.

### C. Europa lukket, USA/Asien åbent
- Europæiske lukkede ikke-handelbare instrumenter reducerer kurs-polling; europæiske nyheder scannes stadig ved aftalt radarplan.
- Åbne markeder og eksisterende ejede positioner prioriteres efter faktisk risiko og handelsmulighed.
- Når Europa genåbner, indhent ny *ægte* kurs/status og fortsæt med samme session, historik og strategy-version; aldrig gengivet gammel kurs som ny.

## 14. Hvad vi gør *efter* Codex afleverer udviklingsfilen

Denne model skal først sammenholdes med Codex' komplette instrumentgennemgang i GitHubs udviklingsrod. Derefter:
1. kortlæg hvert dokumenteret brud til modeltrin og faktisk fil/funktion;
2. identificér fælles grundfejl og fejl, hvor Codex kun har en hypotese;
3. foreslå den mindste sikre rettelse pr. fælles årsag, prioriteret efter signalberedskab, driftsrisiko og API-forbrug;
4. aftal eventuelle ægte kontraktkonflikter med ejeren, før kode ændres;
5. kontroller efter installation med faktiske readbacks, ikke kun lokale tests.

**Denne arbejdsmodel er ikke en erstatning for den gældende samarbejdsaftale.** Den må kun bruges som implementerings- og reviewguide, indtil ejerens eventuelle udtrykkelige ændringer er vedtaget.