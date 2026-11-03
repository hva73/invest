# HOT WATCH arbejdsbackup — 3. november 2026

**Ikke en installationsklar udgave.** Branch `codex/hotwatch-engine-wip`.
Stabil v2.2 findes på `codex/escape-development`, commit `d4b1a45`.
Checkpoint `2a8da59` indeholder arbejdet nedenfor. Ingen drift er installeret, ingen rigtige handler eller eksisterende timeautomatisering er ændret.

## Brugerens scope

Byg standalone HOT WATCH Engine v1.0 efter den komplette specifikation i chatten. Prioritér fase 1–2; fase 3–5 kan afgrænses eksplicit. Brugeren har EODHD **Active Trader**, men ingen API-nøgle eller verificerede feedrettigheder er tilgængelige i udviklingsmiljøet. Ingen datatjenester må købes. Seneste tillæg kræver permanent kandidatlivscyklus DISCOVERED/ANALYZING/HOT_WATCH/WAITING_TRIGGER/BUY_SIGNAL/ORDER_PENDING/POSITION_OPEN/EXIT_WATCH/CLOSED/ARCHIVED, separat BUY/WAIT/REJECT-anbefaling og Pluto-autoritativ udførelse. Samme kandidat kan have flere forløb og være ejet trods REJECT for nye køb.

Brugeren varslede 10 % resterende forbrug med nulstilling kl. 19.22. Backup er derfor pushed på separat branch før færdiggørelse. Bevar den sædvanlige branch, indtil slutkontrollerne er bestået.

## Bygget i checkpointet

- `hotwatch_contract.py`, `hotwatch_features.py`, `hotwatch_strategy.py`: strenge kontrakter, kausale Decimal-indikatorer med max. 120 observationer og sessions-/kilde-/valuta-/intervaladskillelse, deklarativ whitelist-regelmotor, central risiko og anti-noise. Baseline escape_momentum 1.0.0; ingen arbitrary eval/import af strategier.
- `hotwatch_engine.py`: persistent session manager, idempotens, kapacitet, leases, concurrency/budget/backoff, append-only markedsdata/brokerkontekst/beregninger/hændelser, account- og system-kill switch. Stop/pause genoptages ikke automatisk. Uddata gemmer strategi-checksum, risiko-/feature-versioner, input-ID'er og tidligere signalstate til rekonstruktion.
- `hotwatch_service.py`: separat service/--once/central --kill-switch. Eksisterende worker.py/jobs.py er urørt.
- `hotwatch_adapters.py`: strikt read-only Pluto Gateway med RPC-budget og blokering af write-værktøjer, existing quote/snapshot-contracts, bounded INACTIVE order read, EODHD REST real-time reader (disabled by default), sender inbox og synthetic test feed. Ukendt quote time/valuta/spread/session/fees/FX/tradability blokerer nye BUY. Ingen WebSocket eller antagelse om tick/realtime-rettigheder.
- `hotwatch_api.py`: cookie+CSRF eller nye OAuth-scopes `hotwatch:read`/`hotwatch:manage`. Gamle report-grants får ikke motoradgang. Strategy uploads/admin/kills/test ingestion er manuelt cookie/admin-begrænset. Produktionssamples kan ikke sendes gennem test-endpoint.
- MCP 2.5.0: start_hot_watch/control_hot_watch/get_hot_watch_engine kræver nye scopes. get_hot_watch_engine kind=candidate returnerer den permanente kandidatstatus. Existing report tools/scopes er bevaret.
- `candidate_lifecycle.py`: append-only livscyklus og execution events, separate trade cycles, migration fra eksisterende rapporter, broker-bekræftet position adskilt fra afsenderpåstand, varig identitet, arkivering/genaktivering, pagineret statushistorik. Gamle payloads/digest omskrives ikke.
- Optional v2 fields: candidate asset_id/exchange/lifecycle/reactivation_reason, trade_cycle_id på position/order/journal. Eksisterende decision KØB/AFVENT/FRAVÆLG bevares; projections mapper til BUY/WAIT/REJECT. Raw report FILLED er ikke i sig selv serverbekræftet Pluto-udførelse.
- `static/engine-ui.js`, `static/candidate-ui.js` og eksisterende views: dynamisk engine-status med 15s DB-polling, sessionoprettelse/pause/resume/stop, graf/metrics/events, inaktive strategiuploads, kill switch, livscyklusfiltre og separat udførelsesstatus. Ingen provider-polling fra frontend.

## Verifikation indtil nu

- Sidste fulde suite: **244 tests bestået**, `/tmp/escape-engine-final-tests.log`. Senere målrettet motor-suite: **33 tests bestået** før de allerseneste INACTIVE-order/context-only-ændringer. Der er tilføjet flere cases siden første fulde kørsel; tæl kun det endelige aktuelle resultat.
- Beståede browserforløb: browser_hotwatch_engine.py, browser_intel.py, browser_positions.py, browser_overview.py; 320–1920px, syntetiske data, ingen provider-/tradecalls i engine-browserforløbet. Billeder `/tmp/escape-engine-390.png` og `-1440.png`. Billeder mangler endnu endelig visuel gennemgang.
- Tre JS-tests bestået. Gentag relevante checks efter sidste ændringer.
- Nyeste udvidelse i checkpoint: ReadOnlyGateway læser bounded INACTIVE ordrer. PlutoAdapter kan ved manglende kurstid vedhæfte `DataUnavailable.position_context`. **Runner håndterer endnu ikke denne context-only-egenskab**, så det skal færdiggøres eller afgrænses klart før aflevering. `hw_context_events.sample_row_id` er endnu NOT NULL; en context-only-observation før første kurs kræver nullable reference og en kontrolleret producentfunktion. Ingen falsk event_time må indsættes for at få manglende kurstid accepteret.
- Først observerede historiske fyldninger uden tid må ikke fejlagtigt lukke en helt ny trade cycle. Seneste candidate_lifecycle.observe_pluto binder sådanne ordrer til cycle=None; følg med tests for gentaget/multiple-cycle-forløb.

## Resterende før klar levering

1. Afslut/verify context-only brokerobservationer ved manglende kurstid, så position/fyldning kan journalføres uden at skabe en fiktiv kurs eller gentage entry-confirmations.
2. Test central system-kill-switch, seneste INACTIVE/Retry-After/fault cases, lifecycle pagination og nye candidate-status API paths. Ret eventuelle regresioner; ingen rigtige brokerkald.
3. Regenerér schemafiler og opret synthetic engine examples fra de aktuelle kontrakter.
4. Skriv `docs/HOTWATCH_ENGINE.md` og `docs/CANDIDATE_STATUS_MODEL.md` med API, matematik/limits, scopes, migration, operatoropsætning og klar capability-matrix. Tilføj drifts-/opdateringsvejledning og references i README/MCP docs.
5. **Backtest, shadow, qualification/activation og rollback af uploadede versioner er IKKE implementeret** (returnerer eksplicit 501). Markér som fase 3. Ingen performance-/profitabilitetspåstande. Builtin baseline vælges eksplicit ved sessionstart, ikke via upload.
6. EODHD official SDK 1.0.32 fra PyPI blev kun inspiceret, ikke installeret/kørt. Public source verificerer `/api/real-time/{ticker}` og SDK WebSocket-klasser, ikke kontoens rettigheder. EODHD_KEY konfigureres kun server-side; REST kræver ESCAPE_HW_EODHD_REST_ENABLED=1. Reader kræver eksplicit provider_symbol og quote_currency og afviser uverificeret mapping/manglende currency. De nuværende eksterne adapters har 300s floor og kan mangle bid/ask/session/volume; de må ikke markedsføres som 5s livefeeds. Actual EODHD key/entitlement/probe er IKKE testet.
7. Hostingens tilladelse til en separat vedvarende service er IKKE verificeret. Ingen daemon/cron må startes automatisk. CPanel/Passenger er ikke i sig selv en garanti for en kontinuerlig worker. Lever dokumenteret --once og separat supervisorvejledning uden at ændre eksisterende scheduler eller købe infrastruktur.
8. Kør fuld Python suite med lokal-socket-tilladelse, 3 JS-tests og relevante browser-regressioner. `apply_update.py` FILES er udvidet og skal kontrolleres i ZIP.
9. Commit/push færdig version til normal branch først efter verifikation; ellers push WIP igen. Aflever GitHub-link, præcist mappe-/scriptnavn og ærlig fase-/datakildestatus. Ingen automatiseret deploy.

## Arbejdskommandoer

`python3 -m unittest discover -s tests -p 'test_*.py'` (kræver socket-permission til lokale HTTP-tests).
`python3 tests/browser_hotwatch_engine.py` (Playwright + /usr/bin/chromium, lokale sockets).
`node tests/test_attention.js`, `node tests/test_format.js`, `node tests/test_freshness.js`.

Git remote: https://github.com/hva73/invest. Normal aflevering: `git push origin HEAD:codex/escape-development`; ufærdig backup: `git push origin HEAD:codex/hotwatch-engine-wip`. Brug ikke force push og nulstil ikke workspace.
