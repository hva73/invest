# HOT WATCH — selvstændig motor og end-to-end-kontrakt

Kontrakt 1.0.0, 3. november 2026. Supplerer END_TO_END_DATA_CONTRACT.md og HOTWATCH_ENGINE.md. Beskriver faktisk implementeret motor, ikke ønsket fremtidig realtidsarkitektur. Visuelt redesign må ikke ændre reglerne nedenfor.

## Arkitektur og overdragelse

Trading Radar/ChatGPT producerer rapportkandidater, anbefaling og rapporteret lifecycle. Rapportmodtagelsen validerer og gemmer kandidatidentitet/journal. En motor starter **kun** ved et eksplicit autoriseret start_hot_watch / sessions-API-kald; HOT_WATCH-lifecycle eller åbning af en side starter ikke en service eller session. Backend-servicen hotwatch_service.py er en separat proces og kræver ingen aktiv ChatGPT-chat.

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
- Indgang kræver baseline-reglernes konjunktion, ingen eksisterende position, alle obligatoriske risikoinput og tilladt entry-scope. Exit-regler for ejet position kræver return_3_pct≤−0,8 og breakdown; trailing exit ved mindst 2% afstand ned fra observeret high. allow_reduce=false i baseline.
- Stopbrud eller exitdeadline på en ejet position kan tilsidesætte normal cooldown/bekræftelse, men friske verificerede pris-/positionsdata kræves stadig. Lukket/halted marked giver PAUSE. Extended-hours exit advarer om ubekræftet eksekverbarhed.
- Regelscore er 20 point pr. tilgængeligt input blandt return_3_pct, relative_volume, spread_pct, volatility_pct og macd_histogram, 0 ved NO_DATA/PAUSE. Det er datadækning, ikke en sandsynlighed.

## Risiko, stabilisering og alarmer

Nye BUY blokeres ved ukendt/forældet pris eller kontekst, ukendt marked/handelsbarhed, manglende bid/ask/spread, fees/FX/kapital/størrelse/stopgrundlag samt overskredne globale/sessiongrænser. Eksisterende algoritme har desuden hårde 5%-grænser for volatilitet og price gap samt højst 20 nye handlingssignaler pr. time. Maksimal brokerkontekstalder er 300s; maksimal risikogodkendt quotealder er min(sessiongrænse,120s).

Tre nye markedsbekræftelser, minimumsvarighed, cooldown og hysterese følger baseline-parametrene. Gentagen identisk quote og en ren ændring af brokerkontekst må ikke tælle som nye entry-bekræftelser. Kritiske overrides og signal-/risiko-/kvalitetshændelser journalføres. Identiske advarsler deduplikeres; historie slettes ikke af kill switch.

**60s i den nye designspecifikation er en visnings-friskhedsgrænse for live-quote, ikke en ændring af strategiens eksisterende 120s-risikoloft eller adapterfrekvens.** UI kan mærke den seneste historiske beregning forældet, men må ikke omskrive dens signal, parametre eller journal.

## Faktisk datatilgang, polling og budget

| Adapter | Faktisk minimumsinterval | Dokumenteret begrænsning |
|---|---:|---|
| Pluto | 300s | Eksisterende read-only RPC-kontrakter; kursens event time, spread, volumen, market phase, fees, FX og handelsbarhed kan mangle |
| EODHD REST | 300s | Disabled by default; kræver servernøgle og særskilt enabled-flag, eksplicit provider_symbol/quote_currency; Active Trader oplyst, rettigheder ikke verificeret |
| Report inbox | 60s | Afsenderobservation, ikke i sig selv betroet til nye BUY |
| Synthetic | 5s gulv | Kun testkategori; samples indsættes gennem cookie-admin-testendpoint, ikke livefeed |

Profilernes mål: NORMAL60s, ACTIVE15s, CRITICAL5s, IDLE300s. Reelt interval er mindst adaptergulvet og kan blive længere ved budget, backoff, markedsstatus eller fravær af nye data. Adaptiv profil prioriterer risiko/breakout/volume spike, men tilsidesætter ikke gulvet. Intet WebSocket-feed er aktiveret. Fem sekunders mål er derfor ikke fem sekunders produktionsdækning.

Standardkapacitet 10, konfigurerbart 1–100; samtidige leases standard2, interval1–10; lease120s. Requestbudget er kalender-minutbaseret, standard12, maksimum120. Claim har konservativ budgettering, og egne Pluto-RPC-kald tælles også gennem den begrænsede gateway, inklusive initialize/tools. EODHD deler kildebudget globalt. API-vilkår/rate limits er stadig selvstændige krav; systemets budget er ikke en leverandørgaranti.

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
