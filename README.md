# ESCAPE Trading Command Center

En første fungerende lokal version med Python 3.12+ standardbibliotek, SQLite og en responsiv JavaScript-frontend. OAuth-tokenkryptering kræver den fastlåste pakke i `requirements.txt`. Dette er ikke den komplette produktionsapp; se [funktionsoversigten](docs/STATUS.md) for præcis dækning og udeståender.

## Start

```sh
cd /workspace/invest
python -m pip install -r requirements.txt
python app.py --create-user
python app.py --port 8000
```

Brugeroprettelse foregår interaktivt og skjuler adgangskoden. Mindst 14 tegn. Serveren lytter kun på loopback. Der leveres ingen standardkonto eller standardkode. Database oprettes i `var/escape.db` og må aldrig committes. `ESCAPE_DB` kan pege på en anden vedvarende sti. Eksisterende konto får brugernavnet `owner` ved opgradering og beholder adgangskoden. Sessioner gemmes som token-hashes i SQLite og deles af cPanels app-processer; de udløber efter otte timer.

## Test

```sh
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/sw.js
```

Tests bruger midlertidige databaser og en lokal HTTP-server. De opretter aldrig en produktionskonto. `GET /api/health` kontrollerer databaseforbindelsen. Serveren logger ikke passwords, cookies eller API-data.

## Produktion og backup

Python-standardserveren er til lokal udvikling. Før privat publicering: brug en produktionsklar applikationsserver/reverse proxy, TLS, `ESCAPE_SECURE_COOKIE=1`, begrænset adgang, verifikation af serveropsætning og sikkerhedsrevision. Aktivér ikke reelle handler uden separat verificeret integration og godkendelsesproces. Udfør browser- og iPhone-test før release. PWA-serviceworkeren gemmer ingen private data og giver ikke offlinehandel.

Tag en konsistent SQLite-backup med Python `sqlite3.Connection.backup` til et beskyttet lager uden for checkoutet. Krypter og begræns adgang til backups. Planlæg automatisering og gendannelsestest hos den valgte host; ingen automatisk backup er aktiveret endnu. Overvåg health-endpoint og diskforbrug. Database indeholder private handelsidéer.

## Flere brugere og Pluto

Administratorens Forbindelser-side kan oprette en engangsinvitation med 24 timers gyldighed. Modtageren åbner Har du en invitation? på login-siden, vælger brugernavn og sin egen adgangskode. Ingen offentlig selvregistrering. Hver brugers forslag, observationsliste, journal og Pluto-tilslutningsønske er isoleret på serveren.

OAuth authorization-code/PKCE og krypteret tokenopbevaring er implementeret og testet med simulerede serversvar. Live-login er ikke verificeret. Login er blokeret, indtil Plutos læsescopes er dokumenteret og konfigureret, appadressen er angivet, tokenkryptering er klargjort, og verificerede metadata understøtter klienttypen. Se [integrationsplanen](docs/PLUTO.md). Kontoændringer, sletning, adgangskodegendannelse, 2FA og e-mailinvitationer er endnu ikke implementeret.

## Arkitektur

`app.py`: HTTP API, autentifikation, inputvalidering og SQLite. `static/`: frontend og PWA. `tests/`: HTTP-integrationstest. Kun lokale long-forslag understøttes. Samlet kapitalbehov = antal × pris × FX + omkostninger. Hypotetisk stoprisiko = antal × (pris − stop) × FX + omkostninger. Spread, slippage og FX-ændringer modelleres endnu ikke. En stoppris er ikke en garanteret udførelsespris.

Fremtidigt integrationslag skal gemme instrumentidentitet, børs, kilde, observationstid og indlæsningstid; behandle reserverede kontanter særskilt; afstemme ordrer mod mæglerens udførelser; og skelne faktisk, urealiseret og hypotetisk resultat. Rapportjob skal bruge Europe/Copenhagen og verificerede børskalendere. PostgreSQL-migrering og et robust job-/integrationslag anbefales før live drift.

## Baggrundsjob

`worker.py` er en kortvarig cron-worker. Den planlægger ECB-valutareferencer og ECB-pressemeddelelser hver time og lokale datastatusrapporter kl. 08, 14 og 22 i Europe/Copenhagen. Job gemmes i SQLite med deduplikering, leases og højst tre forsøg. Fejl prøves igen efter 15 minutter. Ingen handels-, nyhedsfortolknings- eller betalte AI-kald. Jobkørsler skal faktisk aktiveres i hostingens scheduler; appen viser seneste heartbeat. Se [drift og opdatering](docs/UPDATE.md).

`python worker.py` køres én gang. Gentagen cron-kørsel er nødvendig for automatisk drift. Ingen hemmelig HTTP-cron-URL eller offentlig jobtrigger. Kun administratoren kan sætte manuelle kildeopslag i kø. AI forbliver frakoblet, da ejeren alene har ChatGPT Plus og ikke har valgt en API-tjeneste.

Valgfri browsertest: `python tests/browser_smoke.py` kræver Playwright og Chromium på testmaskinen, ikke på webhotellet. Testen bruger en midlertidig database og ingen eksterne data.

## Porteføljedata v0.6

Importerede Pluto-enheder har en detaljevisning med manuel læsning af senest registreret værdi, beholdninger og kontanter. Den bruger kun de fire observerede læseværktøjer i portfolio_data.py og gemmer brugerbundne snapshots. Flere sider med positioner hentes før en liste vises som komplet. Ukendte beløb/pristidspunkter vises som ukendte, og gamle snapshots markeres ved senere læsefejl. Root-porteføljer summeres separat pr. valuta; Collection-værdier lægges ikke oveni. Brokerens økonomiske output kræver fortsat liveverifikation på Nordicway. Se docs/STATUS.md og docs/UPDATE.md for begrænsninger og aktivering.

Privat MCP-rapportindbakke med OAuth/PKCE: se [docs/MCP_REPORTS.md](docs/MCP_REPORTS.md). Forbindelse til ChatGPT og planlagte opgaver kræver separat verifikation.

ESCAPE Intelligence rapportvisning og JSON v2: [docs/REPORT_V2.md](docs/REPORT_V2.md). V1 og eksisterende OAuth-integration er bagudkompatible.

Positionsvurderinger og V2.2: [positionskontrakt](docs/POSITION_ASSESSMENTS.md), [beslutninger og HOT WATCH](docs/V2_2_WORKFLOWS.md), [kravtillæg](docs/REQUIREMENTS_V2_2_DA.md). Gamle v1/v2-rapporter forbliver gyldige. Nye målinger og analyser kræver faktisk levering fra rapportgeneratoren; rapportimport udløser ingen handler.

## HOT WATCH Engine og permanent kandidatstatus

Fase 1–2, selvstændig read-only service med deterministiske signaler, persistente sessioner og kandidatjournal. Se [funktioner, API og drift](docs/HOTWATCH_ENGINE.md) og [statusmodel](docs/CANDIDATE_STATUS_MODEL.md). Backtest, shadow og aktivering/rollback af uploadede algoritmer er fase 3 og ikke implementeret. Aktuelle produktionsfeeds og hostens vedvarende service er endnu ikke verificeret.

## Design v1 — arbejdsudgave til gennemgang

WIP-branchen indeholder brokerbaserede kompakte beholdninger, neutralt værdi-/kursformat, dokumenterede finansielle ændringer, separat kandidat-/motorstatus, sammenfoldet historik og samlet læsejournal. [End-to-end-kontrakten](docs/END_TO_END_DATA_CONTRACT.md) og [motorens særskilte kontrakt](docs/HOTWATCH_ENGINE_DATA_CONTRACT.md) fastlægger afsender-/modtageransvar og uændret strategi/polling. Ingen installation eller release er godkendt. Live close-reference, cashflow-resultat, FX og markedsdækning må ikke antages; manglende grundlag vises som ukendt.
