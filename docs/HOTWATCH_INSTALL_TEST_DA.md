# Kontrolleret HOT WATCH-installation og første feedtest

## EODHD-udvidelse: test efter separat driftsgodkendelse

Den eksisterende beskyttede `ESCAPE_EODHD_API_KEY` anvendes af alle EODHD-kald. Nøglen sendes som EODHD's `api_token` over TLS; den skal ikke ind i GitHub, shellhistorik, kommandoargumenter eller log. Eksisterende REST-adapter kræver fortsat `ESCAPE_HW_EODHD_REST_ENABLED=1`. For WebSocket skal serverens eksisterende Python-miljø efter godkendelse have pakken `websockets` version 12–16; uden den rapporteres `WEBSOCKET_DEPENDENCY_MISSING`, og REST-fallback bevares:

```sh
/home/nordicr4/virtualenv/escape_app/3.11/bin/python3.11 -m pip install 'websockets>=12,<17'
```

Med appens normale miljøvariabler og godkendt serverinstallation kan en operatør lave en begrænset test med to verificerede symboler, helst når markederne er åbne. Erstat kun symbolerne, aldrig nøglen:

```sh
cd /home/nordicr4/escape_app
/home/nordicr4/virtualenv/escape_app/3.11/bin/python3.11 hotwatch_service.py --probe-eodhd NOVO-B.CO --market eu
/home/nordicr4/virtualenv/escape_app/3.11/bin/python3.11 hotwatch_service.py --probe-eodhd AMD.US --market us
```

Hver kommando foretager op til 7 (EU) eller 8 (USA) læseopslag/forbindelser og anvender samme lokale EODHD-requestbudget. Den starter ingen sessioner eller handler. `app.init()` og budgetregistrering kan skrive til appdatabasen; det er derfor en godkendelsespligtig driftsaktivitet. Samtidigt kørende worker deler budgettet. Ved `RATE_LIMIT` springes de resterende kontroller over. `ENTITLEMENT_UNVERIFIED` betyder afvist eller uafklaret adgang for den enkelte datavej og kan dække både nøgle- og abonnementsforhold. `NO_MESSAGES` afgør ikke, om markedet er inaktivt eller et feed er utilgængeligt. Se resultaternes timestamps, antal og separate bid/ask-tider; output indeholder ikke API-nøglen.

Dokumenterede endpoints: `https://eodhd.com/api/real-time/{symbol}` (eksisterende fallback), `https://eodhd.com/api/intraday/{symbol}`, `https://eodhd.com/api/us-quote-delayed` (forsinkede amerikanske bid/ask), `https://eodhd.com/api/exchange-details/{exchange}` og `https://ws.eodhistoricaldata.com/history` (lukkede 1m-barer). WebSocket bruger `wss://ws.eodhistoricaldata.com/ws/{feed}` med `us`, `us-quote`, `us-status`, `eu`, `eu-quote` eller `eu-status`. Kilde: [EODHD MCP-kilde](https://github.com/EodHistoricalData/EODHD-MCP-Server) og [EODHD OpenAPI](https://github.com/EodHistoricalData/EODHD-openapi).

Efter en vellykket og separat godkendt feedtest kan `ESCAPE_HW_EODHD_WS_TRADES_ENABLED=1` sættes i workerens beskyttede miljø. For EU skal de særskilt verificerede EODHD-børssuffikser angives, fx `ESCAPE_HW_EODHD_WS_EU_EXCHANGES=CO`; uden denne mapping bruges REST. Worker åbner højst en tosekunders trade-capture pr. planlagt scanning og falder tilbage til REST ved manglende adgang/data. Det er ikke en vedvarende streamingforbindelse. `RATE_LIMIT` udløser backoff frem for flere kald. Standardinterval er fortsat 300 sekunder; hurtigere polling kræver særskilt godkendelse, feed- og kvotekontrol samt de eksisterende `ESCAPE_HW_EODHD_FAST_POLL_ENABLED` og `ESCAPE_HW_EODHD_MIN_POLL_S`. Intet af dette aktiveres af installationen.

De nye metoder gør minutbarer, quotes og status tilgængelige til diagnostik. De kobles ikke endnu til motorens signalsample: den nuværende samplekontrakt kan ikke gemme uafhængige bid/ask-tider eller sikkert sammenstille asynkrone feeds. WS-trades gemmes med faktisk kildetid, men markedssession, spread og intervalvolumen er ukendte; eksisterende risikokrav er uændrede. Handelsbeslutning eller realtidsadgang kan derfor ikke garanteres af denne test.

Dette er en manuel, read-only installationsprøve. Den opretter ingen handler og starter ikke HOT WATCH automatisk. Første test bør bruge én eksplicit godkendt kandidat; batch på op til 20 bruges først efter at den første observation er kontrolleret.

## Installation

1. Tag den eksisterende private backup efter jeres normale procedure, og stop webappen.
2. Åbn GitHub-repoet `hva73/invest`, vælg branchen `codex/escape-development`, og brug **Code → Download ZIP**. GitHub-arkivet udpakkes som mappen `invest-codex-escape-development`. Upload ZIP-filen til `/home/nordicr4/escape_app/opdatering/`, og pak den ud dér. `apply_update.py` ligger direkte i den udpakkede repo-mappe sammen med `app.py`.
3. Kør via Run Script:

   ```sh
   /home/nordicr4/virtualenv/escape_app/3.11/bin/python3.11 /home/nordicr4/escape_app/opdatering/invest-codex-escape-development/apply_update.py
   ```

   Scriptet tager privat database-/kodebackup og erstatter kun de listede kodefiler. Kontrollér outputtet og gem backupstien.
4. Brug hostingens **Run Pip Install** på appens eksisterende `requirements.txt`, kør `setup_runtime.py` med det normale virtuelle miljø, og start webappen efter jeres sædvanlige procedure. Denne pakke starter ikke worker automatisk.

## Kontrol og én rigtig observation

1. I serverens beskyttede miljø kan I kontrollere/aktivere de eksisterende værdier `ESCAPE_EODHD_API_KEY` og `ESCAPE_HW_EODHD_REST_ENABLED=1`. Indsæt aldrig nøglen i rapporter, frontend, terminal-output eller chat. Hvis hostingmiljøet kræver en konfigurationsændring, behandles den som en separat driftsændring.
2. Kør credential-fri kontrol fra appmappen:

   ```sh
   /home/nordicr4/virtualenv/escape_app/3.11/bin/python3.11 hotwatch_service.py --diagnose
   ```

   `network_requests_made:false` er forventet. `ready_to_probe_entitlement_unverified` betyder kun, at nøgle og flag er til stede; det beviser ikke abonnementstilladelse.
3. Opret én eksplicit HOT WATCH-session gennem den normale autoriserede aktiveringsvej med korrekt `provider_symbol` (EODHD-symbol), valuta og `is_test`-kategori. Status `HOT_WATCH` i en almindelig rapport starter ikke sessionen. Bekræft at sessionen står som `CREATED`/`VALIDATING` og at kandidatidentiteten er korrekt.
4. Kør kun den valgte session gennem den normale adapter:

   ```sh
   /home/nordicr4/virtualenv/escape_app/3.11/bin/python3.11 hotwatch_service.py --once --watch-id <WATCH_ID>
   ```

   Hvis den ikke er forfalden, vent til `next_due_at`; ændr ikke tidsstempler.
5. Kontrollér `/api/v1/hotwatch/providers`, sessionens `/samples`, `/metrics` og `/events`, samt workerlog. Se efter `last_success`, `last_error`, `endpoint_access`, `price_time`, `bid_ask`, `interval_volume`, `market_status`, `event_to_adapter_receive_ms` og `adapter_to_journal_ms`. Ukendte felter forbliver ukendte. HTTP 401/403 betyder afvist adgang; 429 betyder rate limit/backoff; 5xx/netværksfejl betyder, at feedet ikke kunne verificeres.
6. Først efter en vellykket observation kan I eksplicit batch-aktivere op til 20 sessioner. Standardkapaciteten er 20. Standardbudgettet er 12 faktiske providerkald pr. minut; Pluto tæller hvert underliggende RPC. EODHD-adapteren har fortsat et 300 sekunders pollgulv, så dette er **ikke** en realtime-garanti. Overvåg worker-heartbeat, fejl, requestbudget og tidsstempler.

Lad kun worker-processen køre vedvarende, når hostingens supervisor-/genstartspolitik er godkendt og afprøvet. `--interval` er schedulerens vågnetid, ikke feedfrekvens. Afslut testen med sessions-API'ets stopfunktion; historik bevares, og polling ophører.

## Tilbagerulning

Stop webapp/worker, gendan kodefiler fra den private backup og genstart appen. Databasebackup må kun gendannes som en særskilt operatørhandling, hvis en kompatibilitetsfejl gør det nødvendigt; pakken foretager ikke automatisk database-restore. Deaktivering af EODHD-flaget stopper nye EODHD-kald, men afslut eksplicit testsessionerne.
