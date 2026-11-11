# HOT WATCH — selvstændig motor og end-to-end-kontrakt

Kontrakt 1.0.0, 3. november 2026. Supplerer END_TO_END_DATA_CONTRACT.md og HOTWATCH_ENGINE.md. Beskriver faktisk implementeret motor, ikke ønsket fremtidig realtidsarkitektur. Visuelt redesign må ikke ændre reglerne nedenfor.

## Arkitektur og overdragelse

Trading Radar/ChatGPT producerer rapportkandidater, anbefaling og rapporteret lifecycle. Rapportmodtagelsen validerer og gemmer kandidatidentitet/journal. HOT_WATCH-lifecycle eller åbning af en side starter ikke i sig selv en service eller session. Foruden eksplicit autoriseret start kan en kørende service oprette en kvalificeret kandidat- eller beholdningssession efter sine særskilte gates; se [aktuel kodeafstemning](ESCAPE_MASTER_CONTRACT.md). Backend-servicen hotwatch_service.py er en separat proces og kræver ingen aktiv ChatGPT-chat.

Et sessionsstartkald refererer til en eksisterende report_id/candidate_id i samme ejer/testkategori og en præcis strategy_id/version. Adapter → datavalidering → featuremotor → deklarativ strategi → obligatorisk risikogate/signalstabilisering → append-only beregning/event → dashboard/readback. Ingen broker-write i motoren.

## Hvem ejer status?

| Dimension | Må produceres/ændres af | Hvad ændrer den ikke? |
|---|---|---|
| Rapportens analytiske beslutning KØB/AFVENT/FRAVÆLG | Trading Radar/ChatGPT via valideret ny rapport; eksplicit afsenderobservation efter kontrakt | Ingen brokerordre, fill eller automatisk sessionskontrol |
| Kandidatens rapporterede lifecycle | Radar i ny rapport; ESCAPE registrerer append-only, særskilt reported_status ved ubekræftet ejerskab | Ændrer ikke automatisk engine status eller polling |
| Motorens matematiske signal | Fastlåst deterministisk strategi og obligatorisk risiko med verificeret input | Overskriver ikke Radarens analytiske beslutning |
| Motorrelateret kandidatjournal | ESCAPE kan registrere BUY_SIGNAL på signalovertagelse og brokerunderstøttede positions-/executionhændelser | En journalhændelse er ikke en rigtig handel |
| Sessionsstatus | Session manager ved validering/data/fejl/expiry; ejer med hotwatch:manage eller cookie+CSRF ved pause/resume/stop; særskilt kill-switch-kontrol | PAUSED/DEGRADED/ERROR er ikke kandidatens FRAVÆLG/CLOSED |
| Faktisk ejerskab, ordre og fill | Pluto-autoritativ læseobservation | Senderen eller motorens BUY/SELL må ikke selv bekræfte en handel |
| Visningsgruppe | UI-projektion fra dokumenteret status | Ingen start/pause/resume/stop, omskrivning af state, polling eller historik |

Manglende data giver NO_DATA/DEGRADED og advarsel, ikke en ny analytisk FRAVÆLG. Kandidat fravær i en senere rapport sletter intet. ARCHIVED/CLOSED i kandidatjournalen stopper heller ikke automatisk en allerede oprettet session: dette er eksisterende adfærd og må ikke ændres under redesign. UI skal derfor vise aktiv sessionstatus uafhængigt af kandidatens placering i historik.

## Faktisk sessionskontrakt

Den autoritative schema findes i hotwatch_contract.SESSION, eksponeret af sessions-API og MCP. Kernefelter: watch_id, report_id, candidate_id, is_test, purpose, ticker, exchange, asset_id, quote_currency, portfolio_ids, priority, profile, provider, end_at, activation_reason, strategy_id, strategy_version og risk. Valgfrie felter: provider_symbol, trade_cycle_id, reactivation_reason, watch_mode (entry/exit/both).

priority NORMAL/HIGH/CRITICAL prioriterer køens claim. profile NORMAL/ACTIVE/CRITICAL/IDLE er et intervalmål, ikke en garantifrekvens. end_at afslutter sessionen ved udløb; risk.exit_deadline er derimod en matematisk exitbetingelse for en ejet position. Sessionens trade_cycle_id bruges i journalen; hvis det mangler, bruger den eksisterende kode en deterministisk cycle-reference afledt af watch_id. Det er ikke nødvendigvis samme cycle som en tidligere rapport. Fælles cycle skal derfor sendes eksplicit, når den er kendt.

Frie nyhedstriggers, vilkårlige kandidatregler og et ekstra triggers-objekt er **ikke** understøttet i sessionsschemaet og afvises. Radarens næste trigger er beskrivende rapportdata, ikke automatisk en eksekverbar matematisk regel. Kundeprioritet i en rapport bliver ikke automatisk til sessionens priority. Nye sådanne bindingsfelter kræver en koordineret schema-/strategiændring og særskilt review.

Globale risikolofter (sessioner må kun stramme dem):

```json
{
  "max_notional_dkk": "1000",
  "max_loss_dkk": "100",
  "max_spread_pct": "1",
  "max_quote_age_s": 120,
  "max_position_fraction_pct": "20"
}
```

## Eksisterende baseline: præcise parametre

escape_momentum 1.0.0, ingen dokumenteret profitabilitet. Følgende JSON er hentet fra den eksisterende kode, ikke nye forslag:

```json
{
  "schema_version": 1,
  "strategy_id": "escape_momentum",
  "version": "1.0.0",
  "description": "Konservativ kausal momentum-baseline; ingen dokumenteret profitabilitet.",
  "parameters": {
    "min_relative_volume": "1.8",
    "max_spread_pct": "0.8",
    "momentum_pct": "0.3",
    "min_acceleration": "0",
    "max_volatility_pct": "3",
    "short_period": 5,
    "long_period": 13,
    "rsi_period": 14,
    "atr_period": 14,
    "breakout_window": 10,
    "min_samples": 34,
    "confirmation_count": 3,
    "cooldown_s": 60,
    "minimum_signal_s": 15,
    "release_momentum_pct": "0.1",
    "exit_return_pct": "-0.8",
    "trailing_pct": "2",
    "allow_reduce": false
  },
  "entry_rules": {
    "all": [
      {
        "metric": "return_3_pct",
        "operator": ">=",
        "parameter": "momentum_pct"
      },
      {
        "metric": "acceleration_pct_s2",
        "operator": ">=",
        "parameter": "min_acceleration"
      },
      {
        "metric": "relative_volume",
        "operator": ">=",
        "parameter": "min_relative_volume"
      },
      {
        "metric": "spread_pct",
        "operator": "<=",
        "parameter": "max_spread_pct"
      },
      {
        "metric": "volatility_pct",
        "operator": "<=",
        "parameter": "max_volatility_pct"
      },
      {
        "metric": "breakout",
        "operator": "==",
        "value": true
      },
      {
        "metric": "macd_histogram",
        "operator": ">",
        "value": "0"
      },
      {
        "metric": "trend_up",
        "operator": "==",
        "value": true
      },
      {
        "metric": "rsi",
        "operator": "<=",
        "value": "80"
      }
    ]
  },
  "exit_rules": {
    "all": [
      {
        "metric": "return_3_pct",
        "operator": "<=",
        "parameter": "exit_return_pct"
      },
      {
        "metric": "breakdown",
        "operator": "==",
        "value": true
      }
    ]
  }
}
```

Uploadede deklarative strategier er versionsbevarede og skemavaliderede, men inaktive. Backtest, shadow, kvalificering, aktivering og rollback af nye uploads er stadig fase 3 og returnerer eksplicit 501. Upload er ikke en aktivering.

## Matematiske beregninger og forbehold

- Højst 120 kronologiske observationer; adskil kilde, asset, valuta, venue, session_key, market_status og interval_s. Gaps uden for 0,5–1,5 af interval nulstiller det sammenhængende vindue.
- Afkast over 1/3/5/10 intervaller: (seneste/tidligere−1)×100. Hastighed er intervalafkast divideret med faktisk tidsforskel; acceleration er ændring i hastighed divideret med seneste tidsforskel.
- SMA er aritmetisk gennemsnit. EMA seedes med periodens SMA og alpha=2/(period+1), inden for det beholdte vindue. Trend_up kræver pris>kort EMA>lang EMA.
- RSI bruger Wilder-opdatering af gennemsnitlige gevinster/tab; fladt vindue giver 50, nul tab med gevinster giver 100. MACD er EMA12−EMA26, signallinje EMA9 og histogram deres forskel.
- Volatilitet er populationsstandardafvigelse af de observerede procentafkast, ikke annualiseret risiko. ATR er gennemsnit af seneste true ranges, kun når det sammenhængende OHLC-grundlag er komplet.
- Breakout/breakdown sammenligner aktuel pris med de foregående breakout_window priser. High/low og afstande gælder det observerede vindue, ikke nødvendigvis hele handelsdagen.
- Spread=ask−bid og spread%=spread/midpoint×100. Manglende bid/ask giver null; bid/ask beviser ikke faktisk køb/salgspres.
- Volumen pr. interval bruges direkte; kumuleret volumen omregnes kun ved sammenhængende ikke-negative differencer. Relativ volumen er seneste interval / gennemsnit af foregående breakout_window intervaller (baseline 10). Det er **ikke** historisk tidspunktskorrigeret RVOL. Volumenacceleration er diskret anden differens.
- Indgang kræver baseline-reglernes konjunktion, ingen eksisterende position, alle obligatoriske risikoinput og tilladt entry-scope. Exit-regler for ejet position kræver return_3_pct≤−0,8 og breakdown; trailing exit ved mindst 2% afstand ned fra en verificeret top for den aktuelle position. allow_reduce=false i baseline.

`position_history_complete` er et separat bevis fra en betroet brokeradapter: `true` betyder, at alle handler, herunder kumulative fyldninger, der påvirker netop det entydige depot og aktiv gennem observationsintervallet, er med i den komplette `orders`-liste. En komplet liste over aktive ordrer er ikke tilstrækkelig. Toppen opbygges fra friske verificerede kursobservationer mellem to sådanne positionskontroller; ændret identitet, mængde, ordregrundlag, manglende bevis eller længere afbrydelse nulstiller toppen. Den eksisterende Pluto-adapter sætter ikke dette bevis: trailing-exit afventer derfor dokumentation, mens uafhængige exitregler og stop fortsat vurderes. Historiske markedstoppe er fortsat analyseinput, ikke en positionstop.

**Undersøgte Pluto-kilder 11. november 2026:** `list_orders` for DIRECT leverede seneste ordreposter med `createdAt`, `filledQuantity` og `filledAveragePrice`, men i de modtagne poster ingen faktisk fill-tid, intet aktiv-ID og ingen dokumenteret komplet paginering. `get_collection_activity` understøtter paginering og de undersøgte Collection-ordrer indeholdt `filledAt`, men instrumenterne var identificeret ved navn/ticker/valuta uden aktiv-ID. Det er brugbar udførelsesevidens for de pågældende poster, men ikke tilstrækkeligt til at bevise en entydig, komplet aktivhistorik eller DIRECT-handler. En observation efter bekræftet beholdning kan fastslå, at en kurs er observeret efter dette snapshot, men uden fuldstændige fills kan et efterfølgende salg og genkøb af samme antal ikke udelukkes. Kilderne må derfor ikke sætte `position_history_complete=true` på dette grundlag. For at aktivere faktisk trailing kræves en autoriseret read-only brokerkilde, der dokumenterer depot/Collection, Pluto-aktiv-ID, alle fyldninger og komplet dækning af observationsintervallet.
- Stopbrud eller exitdeadline på en ejet position kan tilsidesætte normal cooldown/bekræftelse, men friske verificerede pris-/positionsdata kræves stadig. Lukket/halted marked giver PAUSE. Extended-hours exit advarer om ubekræftet eksekverbarhed.
- Regelscore er 20 point pr. tilgængeligt input blandt return_3_pct, relative_volume, spread_pct, volatility_pct og macd_histogram, 0 ved NO_DATA/PAUSE. Det er datadækning, ikke en sandsynlighed.

## Risiko, stabilisering og alarmer

Nye BUY blokeres ved ukendt/forældet pris eller kontekst, ukendt marked/handelsbarhed, manglende bid/ask/spread, fees/FX/kapital/størrelse/stopgrundlag samt overskredne globale/sessiongrænser. Eksisterende algoritme har desuden hårde 5%-grænser for volatilitet og price gap samt højst 20 nye handlingssignaler pr. time. Maksimal brokerkontekstalder er 300s; maksimal risikogodkendt quotealder er min(sessiongrænse,120s).

Tre nye markedsbekræftelser, minimumsvarighed, cooldown og hysterese følger baseline-parametrene. Gentagen identisk quote og en ren ændring af brokerkontekst må ikke tælle som nye entry-bekræftelser. Kritiske overrides og signal-/risiko-/kvalitetshændelser journalføres. Identiske advarsler deduplikeres; historie slettes ikke af kill switch.

**60s i den nye designspecifikation er en visnings-friskhedsgrænse for live-quote, ikke en ændring af strategiens eksisterende 120s-risikoloft eller adapterfrekvens.** UI kan mærke den seneste historiske beregning forældet, men må ikke omskrive dens signal, parametre eller journal.

## Faktisk datatilgang, polling og budget

## Historisk WIP-løsningsmodel fra 3. november (ikke aktuel versionsstatus)

> Følgende tal, feed- og releasepåstande beskriver det daværende WIP. Se [aktuel kodeafstemning](ESCAPE_MASTER_CONTRACT.md) for batchgrænser, kapacitet, automatisk aktivering og WebSocket-kode.

En almindelig rapport med lifecycle `HOT_WATCH` ændrer kun kandidatjournalen. Den starter aldrig en motorsession. Autoriseret aktivering kræver `hotwatch:manage` og et eksplicit værktøj/kald. WIP tilføjer `activate_hot_watch_batch` og `POST /api/v1/hotwatch/activation-requests`: `request_id`, `is_test` og 1–20 fulde sessionsdefinitioner. Alle sessioner skal matche gemte rapportkandidater, instrument/ticker, gyldig risiko, testkategori og kapacitet. Gentaget request-id med identisk payload er idempotent; ændret payload giver konflikt. HTTP kræver matchende `Idempotency-Key`. Kapacitet/validering kontrolleres for hele batchen før oprettelse. Dette opretter sessioner, men starter ikke serviceprocessen og beviser ikke feedberedskab.

Status skal skelne mellem (1) kandidat afventer eksplicit aktivering, (2) session `CREATED`/`VALIDATING`, (3) worker heartbeat og første scan, (4) seneste vellykkede scan/planlagt næste scan samt (5) feed-/feature-/signalstatus. `ACTIVE` alene må ikke fortolkes som verificeret frisk feed. Dashboardets kandidatvisning skal vise sessionens faktiske tilstand og seneste data- og beregningstid, daglig ændring og ændring siden sammenlignelig observation kun når kilde, instrument, valuta, session og datakvalitet kan matches. Signaltyper er motorhændelser og ændrer ikke Trading Radars beslutning eller Pluto-ordrestatus.

Driftsmodellen kræver en separat vedvarende worker under en verificeret supervisor med genstart ved procesfejl, databaseadgang, heartbeat-/stale-alarm og graceful stop. Den skal testes efter hostens egne begrænsninger. Webrequests og ChatGPT-sessionen må aldrig bruges som worker. Den nuværende repository-konfiguration dokumenterer ingen produktionssupervisor; produktionens kilde-, feedrettigheder, realtime-/WebSocket-adgang og netværk blev ikke verificeret i dette WIP-miljø.

Hurtigere polling kræver separat versionsstyret change request. Timeren alene kan ikke accelerere en leverandørs feed. Med nuværende kode er Pluto og EODHD gulv 300s, Pluto-quote giver ikke garanteret event-time/bid/ask/volume, EODHD REST er disabled by default, kontorettigheder er ukontrollerede, og intet WS er implementeret/aktiveret. Standardbudget 12 requests/minut er globalt/pluto-resourcebegrænset i praksis; højst 2 samtidige leases. Eksempelvis overstiger 10 kandidater ved 5s allerede 120 polls/minut, før flere Pluto-RPC-kald pr. poll. En fremtidig EODHD/stream adapter skal have entitlement probe, server-side credentials, dokumenteret feed/event timestamps, reconnect/backoff, dedup, instrumentbudget, leverandørens rate limits og fallback til reelt feedinterval. Stream/WS-omkostninger og kontorettigheder er ikke verificeret her; ingen pris eller real-time entitlement påstås. Hurtig polling og serviceautostart må først aktiveres efter separat godkendelse.

Strategi `escape_momentum 1.0.0` og dens signalregler ændres ikke i denne aktiveringssti. Nye signalhændelser skal skelne mellem ENTRY, EXIT, RISK, MOMENTUM_WEAKENING, DATA_MISSING og ENGINE_ERROR; nuværende konkrete signalvokabular skal kortlægges uden semantisk ændring, og nye event-typer kræver kontraktversion. Candidate lifecycle ejes fortsat af Radar/autoriseret beslutningsflow; sessionsstatus ejes af engine; motoren udsteder analytiske signaler, ikke Radar-beslutninger. Stop/udløb frigør claim-ressource, historikken bevares; automatisk genaktivering eller kandidatstatus→stop-kobling er ikke indført.

Nye E2E acceptcases ud over H01–H08: H09 batchstart med to kandidater, idempotens og almindelig rapport-HOT_WATCH uden start (bestået lokalt); H10 kapacitetsafvisning er uden delvise sessioner; H11 worker-genstart genoptager due session uden dubletberegning; H12 lukket marked respekterer timer og emit-ter ikke entry; H13 upstream rate limit/backoff tælles i samlet budget; H14 sessionstop annullerer fremtidige polls og bevarer historik. Live-adapter-/supervisorprøver kan først godkendes på staging/server med verificeret kontoadgang.

### Undersøgelsesresultat, latency, prioritering og drift

**WIP-verifikation 3. november 2026:** hele HOT WATCH-suiten bestod **49 tests** (`test_hotwatch_engine` + `test_hotwatch_e2e_contract`, 17,8s). H09 oprettede 20 testkandidater på ca. 36 ms wall-clock / 21 ms intern tid; nul feedscans i det batchkald. Adaptertest gennem normal EODHD parser→Runner bevarede kildens epoch præcist og målte event→modtagelse, providerkald, beregning og modtagelse→journal med lokal testtransport. En scheduler-test bekræftede 20-sessioners standardkapacitet og at kun faktiske adapterkald bruger requestbudget. Prioriteringstesten bekræftede at eksisterende CRITICAL-profil går forrest uden signalændringer. Ingen live EODHD/Pluto-data, produktionsdatabase, host-supervisor eller handler indgik. `py_compile` og `git diff --check` bestod.

Aktuel kø vælger først sessions med motorens allerede beregnede `adaptive_profile=CRITICAL`, derefter eksplicit sessionprioritet og ældste `next_due`. Det ændrer kun rækkefølgen. Der er endnu ingen live 20-symbolmåling; syntetisk batchmåling måler kun sessionoprettelse, ikke feedkapacitet. Claim bruger ikke længere leverandørbudget; hver adapter reserverer budget umiddelbart før sit faktiske eksterne kald. Der er fortsat højst 2 samtidige leases som standard og ingen fair-aging ud over `next_due`-rækkefølgen.

EODHD-planen er oplyst som **Active Trader**, men livekontoen kan ikke nås tästä workspace: EODHD host er ikke tilladt, secret binding mangler, og REST-flag er slået fra. Faktisk entitlement til realtime, minute bars, WebSocket, symbol/venue, forbindelser og beskedgrænser er derfor ukendt. Implementeret er kun REST `/api/real-time/{symbol}` normalisator; minute-bar endpoint og WS er ikke implementeret. Der er ikke foretaget livekald. Ingen abonnementskøb.

Latency reduceres forsvarligt i denne rækkefølge: (1) brug leverandørpush/WS kun hvis konto, kontrakt og server egress dokumenterer det; (2) én delt providerforbindelse multiplexes for instrumentlisten i stedet for ét REST-kald pr. kandidat; (3) scheduler håndhæver leverandørens globale token bucket og fair priority queue; (4) ved REST anvendes adaptive intervaller efter prioritet/volatilitet, men aldrig under feedets faktiske update cadence eller quota; (5) beregning og journalisering udføres umiddelbart efter verificeret ny event; (6) UI-/Radar-readback bruger samme persistente signaljournal. Markedslukning reducerer scanning og intet kunstigt nyt datapunkt skabes. Den viste tid til signal opdeles i market event→receive, receive→calculation, calculation→journal, journal→dashboard/readback og event age. Signalets event-time stammer fra markedskilden, ikke modtagelsestid.

Kapaciteten er nu 20 sessioner som standard og kan ikke sættes højere end 20. Køen prioriterer først den eksisterende `CRITICAL` adaptive profil, så eksplicit `CRITICAL`/`HIGH`-prioritet, dernæst forfaldstid. Ingen nye signalregler eller pollingmål er indført. Det delte requestbudget (standard 12/minut) håndhæves pr. faktisk adapterkald; EODHD-polls er fortsat mindst 300 sekunder fra hinanden pr. session, og Pluto bruger flere RPC pr. scan. Ved opbrugt budget adapteren fejler tydeligt og backoff anvendes; leverandørens egne grænser gælder stadig. 20 samtidige sessioner er derfor sessionskapacitet, ikke garanti om 20 samtidige reads eller opdateringer. Ved push-feed er begrænsningen messages/symbols/connection; intet pushfeed er implementeret.

Vedvarende drift på server kræver verificeret supervisor (systemd, Supervisor eller hostens godkendte worker service), ikke webrequest/cron-kick. Startkommandoen kører under appens venv, service-user, samme DB/key, working directory, secrets via beskyttet environment, restart-on-failure med begrænset backoff, SIGTERM graceful shutdown, stdout/stderr til rotation og heartbeat. Healthchecks skal alarmere på heartbeat-age, exception/restart-loop, oldest due scan, sessions without new observations, provider 401/403/429/5xx, rate budget exhaustion, stale quote, event gaps, disk/db growth og clock drift. DB lease skal ved genstart reclaimes uden at genberegne samme sample; event/sample keys er deduplikeret. Staging skal simulere kill -9, database busy, provider timeout/429, reconnect og graceful stop. Hosting/supervisor er ukendt her; ingen automatisk start konfigureres.

Per scanning logges `source_event_time` når den findes, adaptermodtagelse, provider-/beregningstid, journalføring og eventalder; manglende event-time bliver `null`. Seneste scanmåling/feltkapabiliteter gemmes i eksisterende provider-health payload. Det ændrer ikke rapport- eller handelskontrakter og er ikke et komplet historisk metricsarkiv; logrotation/retention er hostens ansvar. Målingerne indgår ikke i strategien.

EODHD research block: live documentation/account portal could not be reached from this workspace because eodhd.com is not an allowed network destination; no entitlement or cost claim is made. Exact next verification requires an authorized read-only account-plan export or safe server-side probe with the existing key. Never send key in chat/report or log endpoint URL query.

| Adapter | Faktisk minimumsinterval | Dokumenteret begrænsning |
|---|---:|---|
| Pluto | 300s | Eksisterende read-only RPC-kontrakter; kursens event time, spread, volumen, market phase, fees, FX og handelsbarhed kan mangle |
| EODHD REST | 300s | Disabled by default; kræver servernøgle og særskilt enabled-flag, eksplicit provider_symbol/quote_currency; Active Trader oplyst, rettigheder ikke verificeret |
| Report inbox | 60s | Afsenderobservation, ikke i sig selv betroet til nye BUY |
| Synthetic | 5s gulv | Kun testkategori; samples indsættes gennem cookie-admin-testendpoint, ikke livefeed |

Profilernes mål: NORMAL60s, ACTIVE15s, CRITICAL5s, IDLE300s. Reelt interval er mindst adaptergulvet og kan blive længere ved budget, backoff, markedsstatus eller fravær af nye data. Adaptiv profil prioriterer risiko/breakout/volume spike, men tilsidesætter ikke gulvet. Intet WebSocket-feed er aktiveret. Fem sekunders mål er derfor ikke fem sekunders produktionsdækning.

Standardkapacitet 20, konfigurerbart 1–20; samtidige leases standard2, interval1–10; lease120s. Requestbudget er kalender-minutbaseret, standard12, maksimum120. Claim reserverer ikke budget; adaptere reserverer umiddelbart før hvert faktiske providerkald. Egne Pluto-RPC-kald tælles gennem den begrænsede gateway, inklusive initialize/tools. EODHD deler kildebudget globalt. API-vilkår/rate limits er stadig selvstændige krav; systemets budget er ikke en leverandørgaranti.

Fejlbackoff starter ved det effektive gulv/profilmål og fordobles op til det eksisterende loft, med Retry-After som yderligere nedre grænse. Meget lang EODHD Retry-After kræver manuel kontrol. Ingen ukontrolleret polling eller abonnementskøb.

## Afslutning og ressourceophør

claim vælger kun CREATED/VALIDATING/ACTIVE/DEGRADED. PAUSED/ERROR/EXPIRED/COMPLETED får ikke nye claims. Pause/stop/kill rydder leases og kræver eksplicit genoptagelse, hvor tilladt. Session deadline kontrolleres før nyt adapterpoll i Runner. Stop er terminalt; historik og observations-/beregnings-ID'er bevares.

Et allerede afsendt netværkskald kan nå at afslutte eller time out; eksisterende state-/leasekontrol afviser efterfølgende ingestion efter stop. Der loves ikke øjeblikkelig netværksabort eller nul ressourceforbrug fra et allerede igangværende kald. Ingen nye polls skal planlægges for den afsluttede session.

## Forskelle fra den ønskede arkitektur — ingen skjulte ændringer

1. Rapportkandidat bliver ikke automatisk en motorsession; eksplicit start er nødvendig.
2. Rapportens friteksttrigger bliver ikke automatisk en eksekverbar regel. Vilkårlige regler kræver sikker versionering/kvalificering, som ikke er færdig.
3. Datarettigheder, realtime/tick/volume/spread/FX/market-context og kontinuerlig hosting er ikke verificeret på produktionsinstallationen. De nuværende adapters kan derfor legitimt blive NO_DATA/WAIT.
4. Nyhedsrevurdering og automatisk tilbagekald til Radar er ikke implementeret. Hændelser og status kan læses af Radar ved næste eksplicitte analyse.
5. Udvidet strategy backtest/shadow/activation/rollback er ikke implementeret.
6. Kalenderstyret markedsåbning er ikke garanteret af de nuværende adapters; UNKNOWN må ikke skjules som regular session.
7. Kandidatterminalstatus og sessionsafslutning er ikke automatisk koblet. En sådan kobling ville ændre pollingadfærd og kræver særskilt godkendelse.
8. Der er ingen dokumenteret performance- eller profitabilitetsgaranti; syntetisk accept er ikke en reel MERC-backtest eller live-validering.

## Særskilte kontrakttests H01–H08

`tests/test_hotwatch_e2e_contract.py` bruger lokal HTTP/MCP, OAuth/scopes, midlertidig database, syntetiske sample-API-kald og den faktiske deterministiske baseline uden algoritmemock.

- H01: Radar-rapport → validate/send MCP → kandidatpersistens → eksplicit motorsession → 40 tidsstemplede observationer → BUY med fast strategi-checksum → rapportrevurdering uden pollingændring → stop → ingen nye claims → læsbar sample-/signal-/kandidathistorik.
- H02: Kildeudfald → DEGRADED/NO_DATA, ikke kandidatens REJECT/ARCHIVED.
- H03: Kun eksplicit pause/resume/stop ændrer claim-berettigelse.
- H04: Kandidatens ARCHIVED ændrer ikke sessionstate/next_due og stopper ikke eksisterende polling.
- H05: Identisk quote er deduplikeret og tæller ikke som nye observationer.
- H06: Uunderstøttede vilkårlige triggerfelter afvises, ikke tavst evalueret.
- H07: Inflight ingestion efter stop afvises og kan ikke genstarte session.
- H08: Rene status-/historikopslag ændrer ikke forretningsdata, sessionsstatus eller next_due. HTTP-authens eksisterende rate-limit-bogføring er særskilt og er ikke et markedsdatapoll.

Disse supplerer T01–T28 og eksisterende risiko-/matematik-/auth-/kill-switch-tests. Produktionskilder og den egentlige separate Radar-prompt er ikke ændret eller live-testet. Der må ikke mærkes fuld ekstern end-to-end-godkendelse alene ud fra lokale fixtures.

### Automatisk beholdningsovervågning og kapacitet (opdateret)

Historisk snapshot: motoren havde 40 aktive/pausede sessioner som standard. Aktuel kode og den konfigurerede servers begrænsninger skal kontrolleres særskilt; se [kodeafstemningen](ESCAPE_MASTER_CONTRACT.md). En separat baggrundsløkke forsøger gradvist at overvåge aktuelle, komplet verificerede Pluto-beholdninger. Aktivet skal bekræftes af Pluto og have præcis én EODHD-kandidat med samme ISIN og valuta; ukendte eller tvetydige instrumenter oprettes ikke. Positioner oprettes i exit-tilstand og sender aldrig ordrer. Eksisterende og pausede sessioner genbruges; en manuelt afsluttet session genstartes ikke automatisk. Stale, fejlede eller ufuldstændige depotsnapshots bruges ikke til nye sessioner. `ESCAPE_HW_HOLDINGS_AUTOWATCH=0` deaktiverer denne automatiske oprettelse.

Kapacitet er ikke adgang eller frekvens: EODHD-budgettet er delt og tæller alle leverandørkald. Med 40 sessioner kan scanninger blive betydeligt langsommere end 60 sekunder, og adgang, kildetid, kvoter og genstart skal verificeres på installationen. Flere symboler og før-/eftermarked kræver bekræftede feedrettigheder. Ingen købssignaler tillades uden for de eksisterende risikoregler.

### Ordinær åbningstid og warmup

Børsens ordinære åbningstid vises særskilt fra instrumentets før-/eftermarked. Motoren henter en tidsstemplet EODHD-børsstatus i baggrunden og genbruger den i højst fem minutter; manglende, modstridende eller forældet status forbliver ukendt. Lukket ordinær handel indebærer ikke, at et amerikansk instrument ikke kan handles uden for normal tid. En varm op-tæller vises kun, når den seneste beregning har brugbare, aktuelle data; gamle kursobservationer fremstår som gamle. Denne visning ændrer ikke ordre- eller signalregler.
