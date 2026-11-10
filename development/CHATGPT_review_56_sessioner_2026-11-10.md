# ESCAPE – uafhængigt review af Codex' 56 HOT WATCH-sessioner
**Dato:** 10. november 2026 · **Repository:** `hva73/invest` · **Gren:** `codex/escape-development`

## Læsegrundlag og forrang
- Codex' input: [hotwatch-gennemgang-2026-11-10.md](hotwatch-gennemgang-2026-11-10.md), målt omkring 11:29 UTC, produktionscommit ifølge Codex `d889aff3694ce3a783845826d61827a5101b9aa7`.
- Vores selvstændige model: **[ESCAPE – samlet arkitektur- og arbejdsmodel](ESCAPE_arkitektur_og_arbejdsmodel_2026-11-10.md)**. Den skal bruges som praktisk guide, **ikke** som en tavs ændring af aftalen.
- Bindende: `docs/ESCAPE_TRADING_AGREEMENT_V3_9.md`, `docs/HOTWATCH_SAMARBEJDSAFTALE.md`, `docs/HOTWATCH_ENGINE_DATA_CONTRACT.md` samt eksisterende maskinkontrakter. Modstrid om kandidatloft/rapport-ID afklares med ejeren, ikke ved antagelse.
- Jeg har læst Codex' fil og relevante funktioner i den aktuelle udviklingsgren. **Jeg har ikke verificeret den installerede commit, kørt lokale regressionstests eller foretaget 56 atomiske live-readbacks.** Codex' observerede tider og fejl er evidens i hans snapshot, ikke bevis for uændret status nu. Ingen ordrer/ændringer.

## Hovedkonklusion
**Første arbejdshypotese bør ikke være “56 mappingfejl” eller “for snævert BUY-filter”.** Langt de fleste rækker i Codex' tabel er allerede `MATCHED`. De øvrige blokeringer ligger forskellige steder i kæden: broker-scope, samling/friskhed af handels- og quotedata, strategiens eget databehov, gamle statusfelter og ganske få reelle identitetskonflikter.

Et `MATCHED` beviser instrumentidentiteten på tidspunktet for match, men **ikke** at datakæden leverer en frisk handel, tilstrækkelig barhistorik eller frisk Pluto-depotkontekst. En frisk quote er heller ikke en frisk handel.

Prioritér et **første-fejl-sted** pr. session frem for at sætte samme `DEGRADED`-etiket på alt. Den eksisterende kode skal kunne levere information om observationer uafhængigt af BUY-klarhed.

## Konkrete kodefund og anbefalet minimal indsats

### P0 — Pluto parent/Collection overlap på CABA: begrænset, men påvist i koden
**Dokumenteret kodeadfærd:** `hotwatch_service.py:auto_activate_candidate()` bygger `portfolio_ids` til et entry-watch som tom liste, når et parent/Collection-overlap findes. `hotwatch_adapters.py:PlutoAdapter._context()` fortolker tom liste som alle aktive Pluto-porteføljer. Når både parent og Collection indeholder samme asset, returnerer `_context()` `HOLDING_SCOPE_OVERLAP`, fordi `found` kan indeholde samme reelle position to gange. Se især `hotwatch_service.py` ca. linje 286–291 og `hotwatch_adapters.py` ca. 201–246.

**Bevisgrænse:** At denne kodevej findes er påvist. At CABA faktisk rammer den vej er stærkt støttet af Codex' `HOLDING_SCOPE_OVERLAP`, men kræver rå scoped Pluto-snapshots og request for fuld bekræftelse.

**Mindste sikre rettelse:** Udled *én kanonisk, komplet holdingsliste* med klart dokumenteret parent/Collection-semantik, eller brug en ikke-overlappende depotprojektion, mens den originale scopebevisførelse bevares. **Aldrig** summer samme beholdning to gange, **aldrig** erklær `position=none` alene på et ufuldstændigt udsnit, og **aldrig** tilskriv et parent-fill til en Collection. Test tre tilfælde: parent+Collection overlap, position kun i Collection, og ufuldstændig/fejlet snapshot → UNKNOWN. Det må ikke resultere i en ny parallel positionsdatabase.

### P0 — Manglende separat quote-fremdrift efter seneste handel
**Dokumenteret kodeadfærd:** `hotwatch_adapters.py:EODHDAdapter.poll()` kan hente friske quotes, når ingen gyldig handel findes, og journalføre dem som `TRADE_MISSING`. Når handler findes, tilknyttes quotes til handelssample med egne `bid_at`/`ask_at`. `hotwatch_engine.py:view()` udstiller `partial_quote` for verificeret frisk quote, når det effektive signal er NO_DATA. Dette er korrekt beskyttelse mod at gøre gammel handel frisk.

**Observeret:** WIX, AMZN, IBRX og CRSP havde nyere direkte EODHD-data end senest gemt i motoren; ZETA, TLS og SANM havde friske quotes med ældre handler. Det er *ikke* i sig selv dokumentation for tabte data: Codex tog snapshot kort efter genstart, og uafhængig capture og motor kan have forskellig sampling.

**Mindste sikre ændring:** Log pr. session `last_trade_source_at`, `last_quote_source_at`, `last_poll_at`, `last_ingest_at`, seneste feed/collector-udfald og `next_due_at`. Genbrug eksisterende observation/event-tabeller og statusvisning. Sammenlign dem først for et enkelt aktiv, fx WIX, med samtidige provider- og motorreadbacks. Kun hvis det påvises, at modtaget gyldig observation bortfalder i en konkret funktion, ændres denne funktion. Ingen “frisk ved modtagelse”-genstempling.

### P1 — `BAR_EVIDENCE_STALE` på ASML/ORCL skal dissekeres, ikke slås fra
**Dokumenteret kodeadfærd:** `hotwatch_engine.py:view()` afleder et effektivt `NO_DATA`, hvis seneste bar-slut eller `bar_evidence.schedule_received_at` overskrider `max_quote_age_s`, når beregningen bruger bars; se ca. linje 552–569. `hotwatch_features.py:verified_bar_samples()` kræver verificeret kilde, handelsfase og kalender. Dette er en **strammere evidenskontrol for et formelt signal** end blot at have en frisk livehandel.

**Afgrænsning:** Frisk handel + `BAR_EVIDENCE_STALE` kan være fuldt legitimt, hvis momentumreglerne reelt bruger ældre bars. Men en prisbaseret exit må ifølge aftalens afsnit 16 ikke blokere på uvedkommende købsbars.

**Mindste sikre ændring:** Journalfør `bar_last_closed_at`, `schedule_received_at`, `analysis_uses_bars`, nødvendig strategiregel og hvilken af de to tidsaldre der konkret udløste visningsblokeringen. Lav to isolerede regressionscases: entry med udløbne bars → ingen BUY; verificeret price-context exit med gammel barhistory, men alle *exitnødvendige* kilder friske → exit bevares. Ændr ikke den globale friskhedsgrænse.

### P1 — Identitetsgendannelse og budget: TTD/CELC/SHOT/EXK
**Dokumenteret kodeadfærd:** `hotwatch_service.py:recover_automatic_feeds()` arbejder målrettet på Pluto-baserede automatsessioner og sætter `hw_feed_recovery.next_attempt`; en ny mapping søger via `hotwatch_adapters.py:search_eodhd_symbols()` og EODHDs budgetregnskab. `eodhd_capacity.py:Capacity.reserve()` kontrollerer UTC-dagsbudget og leverandørens minutbudget, og skelner routine/essential. Den nyligt købte ekstra saldo må **kun** bruges efter ejerens dokumenterede engangsautorisation og må ikke gøre det normale 80%-loft til et mål.

**Stadig ubevist:** `PROVIDER_RATE_BUDGET` i TTD/CELC/SHOT/EXK kan være EODHD-dagsgrænse, EODHD-minutgrænse, Pluto-reserve, tidligere retry eller snapshot fra før ekstrarettigheden. “Ledig dagskvote” beviser ikke ret til netop dette kald i netop det minut.

**Mindste sikre ændring:** Vis kort, men *adskilt* `provider=pluto/eodhd`, `budget_type=daily/minute/local_retry/entitlement`, `priority`, `retry_at`, `actual_budget_at`, uden tokens. Test at et nyt verificeret identitetsmatch kan genbruges uden gentagen dyr søgning. Test at underkendt ISIN/børs/valuta stadig blokeres. **Undgå** at lade rutinemæssig rekonstruktion bruge den manuelle nødbuffer.

### P1 — `sample_id_conflict` på MSFT/MANE: bevar afvisningen
**Dokumenteret kodeadfærd:** `hotwatch_adapters.py:EODHDAdapter.poll()` skaber WebSocket sample-ID fra symbol og handelstid, mens `hotwatch_engine.py:ingest()` og `refreshed_trade_evidence()` kun tillader fornyelse af uafhængige quote-/status-/barbeviser; en ændret kernehandel under samme ID afvises. Det er hensigtsmæssigt: to forskellige priser med “samme handel” skal ikke stiltiende sammenlægges.

**Bevisgrænse:** Vi kender ikke endnu de konkrete fulde par af samples for MSFT. Fra tidligere MANE-drift ses samme timestamp med forskellige priser; det er ikke dokumentation for hvilken upstream-provider der var forkert.

**Mindste sikre handling:** Udtræk redigeret konfliktpar med `symbol`, feedtype, `event_time`, `sample_id`, pris, receive-tid og kilde, samt om data kom fra WS-handel, lukket minutbar eller REST-snapshot. Find fælles oprindelse *før* der ændres på deduplikering. Test at identisk sample-ID med ændret pris afvises, mens en ægte ny hændelse får eget ID og kan beregnes. Aldrig fremryk gammel kildetid.

### P1 — `NO_DATA` versus aktiv observation
**Dokumenteret kodeadfærd:** `hotwatch_engine.py:view()` kan vise marked, quote og observationsgrundlag separat, men en effektiv `NO_DATA` afhænger fortsat af nyeste handel, kontekst, strategi og enkelte beviser. `hotwatch_features.py:observation_status()` beregner visningsfeatures uden at være handelsinput.

**Mindste sikre ændring:** Vis både `MARKED/HANDEL`, `KURS/QUOTE`, `STRATEGI`, `RISIKO` og `BROKER/DEPOT` som adskilte, eksisterende read-only projektioner. Det giver nyttig information om stigende kurser, friske quotes og konkret blokering *uden* at gøre BUY eller SELL lovlige på manglende data. Ikke nye wire-enums eller en parallel statusmotor.

### P2 — Eksekverbarhed efter lukketid: JDZG
Codex' `TRAILING_EXIT` + `EXTENDED_HOURS_EXECUTION_UNCONFIRMED` + `CONFIRMATION_PENDING` kan være en legitim kombination. EODHD kan vise handel, uden at Pluto kan udføre eftermarkedssalg for JDZG. Et exit-signal, et eksekverbart orderforslag og en faktisk Pluto-ordre skal forblive tre separate ting. Kontrollér signal-/pushhistorik og Plutos read-only ordretyper; **ikke** automatisk GTC/market-forslag og ikke “SELL” som bevis for en placeret stopordre.

## Forslag til let, systematisk gennemgang af alle 56
Første gennemløb: Opret en kompakt række pr. eksisterende session (samme `watch_id`) med **scope (holding/entry), asset-ID, mappingstatus, seneste trade/quote/kildetider, broker-kontekst, strategi/version, sidste beredskab, første blokering, næste forfald**. Ingen 56 individuelle nye rapporter. Brug den allerede eksisterende journal; bevar kandidat/exit-skel.

Andet gennemløb: Gruppér efter *faktisk første blokering*, ikke efter `DEGRADED`: (A) Pluto-identitet/scope, (B) EODHD-match, (C) feedintet/stale, (D) kalender/barhistorik, (E) broker-kontekst, (F) strategidata, (G) strategi ikke opfyldt, (H) risk/eksekverbarhed. Vælg **ét repræsentativt instrument pr. fællesfejl**. Ret fællesfunktionsfejl én gang, test både bekræftelse og afvisning, kontrollér derefter automatisk samtlige berørte sessioner.

Tredje gennemløb: Udfør en fuld pagineret læsning **efter ny produktionsinstallation**; noter hvilken GitHub-commit der faktisk kører. For hver session: PASS = rigtig identitet, gyldigt data eller korrekt dokumenteret årsag til manglende data, gyldigt tidsgrundlag, korrekt strategi/risikoadskillelse og sammenhængende readback. `ACTIVE` eller BUY er **ikke** et succeskriterium i sig selv. Eksterne begrænsninger kan være legitimt dokumenteret status, ikke skjult teknisk PASS.

**Rækkefølge:** P0 CABA/scope og én frisk amerikansk sammenligning (WIX/AMZN) → P1 bars/quotes og ratebudget → MSFT/MANE → crypto/PEPE (bevar identitetsspærre) → øvrige dokumenterede særlige tilfælde. Hold exits i drift under analysen.

## Konkrete tests der giver mening
1. Parent + Collection deler samme reelle position; ingen dobbeltoptælling, korrekt depot/asset, og ingen falsk `none`.
2. Fremtidig, gammel eller kun quote-baseret observation må ikke få handel, barhistorik, BUY-bekræftelse eller exit til at fremstå frisk.
3. Ny handel med original kildetid efter genstart kan modtages; stale/cached old trade bliver ikke omskrevet.
4. PRE/AFTER-bars kun fra verificeret *samme* handelssession, ingen fabrikerede tomme minutter; price-context exit uafhængig af entry-warmup.
5. Budgetfejl viser korrekt provider og `retry_at`; normal budgetramme genindføres automatisk efter 10. november UTC, og engangsbuffer bruges ikke som rutinekvote.
6. Intet codepath i HOT WATCH gør broker-write. Godkendt forslag =/= FILLED. Historisk SELL-push deduplikeres uden at skjule ny kritisk exit.
7. Forskel på gammel beregning, aktuel status og genberegningsfrist vises ved åbent/lukket marked.

## Kort tilbagemelding til Codex
**Vores model:** [ESCAPE – samlet arkitektur- og arbejdsmodel](ESCAPE_arkitektur_og_arbejdsmodel_2026-11-10.md).

Prioritér **det første dokumenterede brud pr. session** og gruppering af de 56 sessioner efter fælles årsager. Der er allerede mange `MATCHED` instrumenter. Begynd med scope-overlap på CABA, verificér samtidige direkte- versus motorobservationer på WIX/AMZN, og mål præcis hvorfor ASML/ORCL får bar-evidens-blokering. Del quote- og handelsstatus, men bevar alle køb-/exit-/risikogates. Budgetfejl skal mærkes med den faktiske provider og type. Ret kun påviste fællesfejl og læs den installerede version tilbage. Følg samarbejdsaftalens mandat og versionslåste strategier. Ingen nye subsystemer, ingen ordrer eller skjult regelændring.

**Resultatstatus:** Uafhængigt kode-review med dokumenterede kodeveje og målrettede hypoteser. **Ikke** et live-verificeret fix, komplet testkørsel eller ejerautoriseret deployment.


---

## Opfølgning – Codex commit `6243faf` og overførsel til GitHub Projects (10. november 2026)

**Projektstyring:** Ejeren har oprettet GitHub Projects-tavlen **ESCAPE Development**. Fremover er GitHub Issues i `hva73/invest` opgavernes autoritative backlog, tilknyttet Projects-tavlen; `development/` rummer model, Codex-undersøgelser og dette uafhængige review. GitHub-connectoren tillader i øjeblikket **ikke** at sætte Project-værdier eller tilknytte Issues direkte til Projects. Nye Issues er oprettet i repository; de må ikke hævdes synlige på tavlen, før GitHubs auto-add workflow eller manuel tilføjelse er verificeret.

**Vores model:** [ESCAPE – samlet driftsmodel](ESCAPE_arkitektur_og_arbejdsmodel_2026-11-10.md). Ændrer ikke samarbejdsaftalen eller handelsmandatet.

### Review af den nye ændring
Codex har tilføjet [`6243faf`](https://github.com/hva73/invest/commit/6243faf95485627e5aad780a4fd68c58eaa9151f) (**Reconcile explicitly scoped Pluto holdings**) og [sin opfølgning](CODEX_opfoelgning_hotwatch_2026-11-10.md).

**Vigtig korrigering/præcisering til den første CABA-hypotese:** Pluto-parentens `get_positions` og en Collections `get_collection` kan repræsentere **forskellige direkte og Collection-beholdninger i samme aktiv**, ikke nødvendigvis dubletter. Det var derfor for hårdt at afvise alle tilfælde, hvor samme asset-ID forekommer i begge. Codex dokumenterer konkrete Pluto-responsefund for CABA/BTC. Rettelsen mærker direkte portefølje-data `positions_scope=DIRECT`, Collection-data `positions_scope=COLLECTION`, kontrollerer komplette strengt læste positioner, sammenholder de aktuelle Collection-ID'er og tillader kun summation, når begge scopes er særskilt dokumenterede. Manglende metadata medfører fortsat UNKNOWN. Ingen ny database.

**Kode-review:** Dette er en målrettet, bagudkompatibel retning, som bevarer afvisning ved ufuldstændig scope. De væsentlige linjer ligger i `hotwatch_adapters.py:PlutoAdapter._context()` og `portfolio_data.py:read()`. Der er imidlertid stadig en vigtig **produktionsaccept**: kontrollér at `positions_scope` er opnået fra de faktiske raw Pluto-responsefelter på alle relevante depoter, inklusive korrekt pagination og reference til alle child Collections. Test separate vs. aggregerede beholdninger og ingen krydsdepottilskrivning. Denne observation er *ikke* bevis for, at rettelsen er installeret.

Codex' read-only samtidige check omkring **11:56 UTC** viste, at WIX og AMZNs seneste handler stemte med motorens. Dermed er der **ikke** påvist tabte EODHD-handler for disse to i måleintervallet. Tidligere kilde-/motortidsforskel er et undersøgelsesspor, ikke en dokumenteret bug. ASML/ORCLs tidligere `BAR_EVIDENCE_STALE` var ikke længere til stede i det senere snapshot; undersøg uden at lempes entry/exitkrav.

**Tests:** Codex oplyser **342 relevante lokale PASS** for den nye rettelse. Dette er ikke min egen reproduktion, ingen fuld testpakke og intet LIVE PASS. Codex oplyser, at serveren fortsat kørte `d889aff` ved kontroltidspunktet; installationsgodkendelse kræves særskilt fra ejeren.

### Nye Issues – opgaver og efterfølgende accept
- [#3 – P0: Pluto DIRECT/COLLECTION CABA/BTC](https://github.com/hva73/invest/issues/3)
- [#4 – P0: EODHD → HOT WATCH datakæde, 56 sessioner](https://github.com/hva73/invest/issues/4)
- [#5 – P1: ASML/ORCL bar-evidens](https://github.com/hva73/invest/issues/5)
- [#6 – P1: MSFT/MANE sample-ID-konflikter](https://github.com/hva73/invest/issues/6)
- [#7 – P1: TTD/CELC/SHOT/EXK/PEPE identitets- og budgetdiagnose](https://github.com/hva73/invest/issues/7)
- [#8 – P1: Tidlige observationer og købsfilter](https://github.com/hva73/invest/issues/8)
- [#9 – P1: EODHD-forbrug, market sleep/wake](https://github.com/hva73/invest/issues/9)
- [#10 – P1: Installeret commit, readback og release-gate](https://github.com/hva73/invest/issues/10)

Tidligere [#1 – kontraktafstemning](https://github.com/hva73/invest/issues/1) bevares, men skal opdateres mod den *nuværende* v3.9-tekst og nyere tillæg, ikke styres af forældede tal.

**Anbefalet proces:** Backlog → I gang → Review → Klar til installation → Driftstest → Færdig. Maksimalt 2–3 aktive kodeopgaver. Codex knytter commits/tests til Issues. ChatGPT reviewer ændringer uafhængigt. Ejeren godkender produktion særskilt. Først efter dokumenteret live-readback markeres issue Færdig. Ingen automatisk broker-write, ingen falsk PASS, ingen implicit ejerbeslutning.

**Kanban-tilknytning:** Repo-Issues er oprettet, men deres visning i selve Projects-tavlen er endnu **ikke verificeret** fra denne forbindelse; aktivér auto-add for `hva73/invest` eller tilføj de eksisterende Issues én gang i GitHub Projects.
