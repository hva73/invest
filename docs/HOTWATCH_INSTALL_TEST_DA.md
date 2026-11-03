# Kontrolleret HOT WATCH-installation og første feedtest

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
