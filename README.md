# ESCAPE Trading Command Center

En første fungerende lokal version med Python 3.12+ standardbibliotek, SQLite og en responsiv JavaScript-frontend. Ingen eksterne pakker. Dette er ikke den komplette produktionsapp; se [funktionsoversigten](docs/STATUS.md) for præcis dækning og udeståender.

## Start

```sh
cd /workspace/invest
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

Pluto OAuth er endnu ikke aktiveret. Tilslutningsønsker gemmes kun lokalt og sendes ikke til Pluto. Der gemmes ingen Pluto-tokens. Se [integrationsplanen](docs/PLUTO.md). Kontoændringer, sletning, adgangskodegendannelse, 2FA og e-mailinvitationer er endnu ikke implementeret.

## Arkitektur

`app.py`: HTTP API, autentifikation, inputvalidering og SQLite. `static/`: frontend og PWA. `tests/`: HTTP-integrationstest. Kun lokale long-forslag understøttes. Samlet kapitalbehov = antal × pris × FX + omkostninger. Hypotetisk stoprisiko = antal × (pris − stop) × FX + omkostninger. Spread, slippage og FX-ændringer modelleres endnu ikke. En stoppris er ikke en garanteret udførelsespris.

Fremtidigt integrationslag skal gemme instrumentidentitet, børs, kilde, observationstid og indlæsningstid; behandle reserverede kontanter særskilt; afstemme ordrer mod mæglerens udførelser; og skelne faktisk, urealiseret og hypotetisk resultat. Rapportjob skal bruge Europe/Copenhagen og verificerede børskalendere. PostgreSQL-migrering og et robust job-/integrationslag anbefales før live drift.
