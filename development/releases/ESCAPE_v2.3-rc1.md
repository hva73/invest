# ESCAPE Invest v2.3 RC1

**Status: installeret 11. november 2026 kl. 21:43 UTC (22:43 dansk tid).** Godkendt og installeret SHA: `b0fae95aa0d0342ef6de2145452829e2fb47825d`. [Issue #57](https://github.com/hva73/invest/issues/57) er releasejournal. PR #62 blev efter installationen merget som `42f1790d36563f288539209753825c8f7e036e09`; mergecommittet er ikke installeret.

## Forbedringer

- **Mobil (#55 / #54):** kompakt overblik, bundnavigation og sortering af beholdninger. Profilhandlinger er samlet under Mere. Positionsdialogen har en lettere køb-/salgsbar, og grafens kontroller er tilgængelige.
- **Handelsforslag (#55):** køb og salg gennemgår estimat og en synlig bekræftelse før eksplicit afsendelse. Pluto står fortsat for den endelige godkendelse. Ukendte sendesvar genafsendes ikke automatisk.
- **Performance (#56 / #14):** færre gentagne opslag af pollingbudget ved scanning. Syntetiske målinger er ikke dokumentation for produktionsgevinst.
- **Diagnostik (#61 / #14):** databasescope og SQLite BEGIN måles hver for sig for vellykkede ingest. Målingerne kan hjælpe en senere undersøgelse, men fastslår ikke alene årsagen til SQLite-låsning.
- **Releasegrundlag (#58 / #57):** bevarer den allerede installerede runtimeversionskontrol og updater på udviklingsgrenen samt beskriver den eksisterende releaseprocedure.

## Kendte begrænsninger

- Browseremulering erstatter ikke fysisk iPhone-test af tastatur, safe area, scroll og faktisk retur fra Pluto.
- Årsagen til historisk SQLITE_BUSY og den faktiske driftseffekt af performanceændringerne mangler sammenlignelig live-måling.
- Trailing-exit-rettelsen i #60 er under udvikling og er ikke med; fuldstændigt verificeret positionshistorik er endnu ikke dokumenteret.
- Eksisterende installeret deploybridge summerer ikke SQLite WAL/journal særskilt i sit automatiske pladsestimat. Kapacitet, sidecars og recoverystatus skal kontrolleres før hver installation.

## Test og installation

- [Python 3.11 CI](https://github.com/hva73/invest/actions/runs/43101566116): 363 + 15 tests bestået. [Browser og mobil CI](https://github.com/hva73/invest/actions/runs/43101565967): bestået på samme kandidat.
- Ejeren godkendte den præcise SHA efter review og serverpreflight. [Deploy](https://github.com/hva73/invest/actions/runs/43105356384) meldte fuldført, service gendannet, ingen recovery nødvendig og backupoprydning OK.
- [Filkontrol](https://github.com/hva73/invest/actions/runs/43105673025): 71/71 manifestfiler matcher. Den ældre read-only preflights generiske `blocked`-status er ikke deployresultatet.
- [Driftskontrol 21:51 UTC](https://github.com/hva73/invest/actions/runs/43106726289): SHA matcher, database OK, fire Passenger-processer og én hver af worker og supervisor, begge med friske heartbeats. API svarede efter installationen. 37 DEGRADED / 3 ACTIVE er et øjebliksbillede og ikke en effektmåling.
- Før deploy var kontokvoten mindst 6.987.365.824 bytes ledig, WAL/journal 0. Frisk efter-installations kontokvote, WAL/journal, backupintegritet og recoverymarkør er endnu ikke individuelt genmålt; deployet meldte backupoprydning OK og ingen recovery nødvendig.
- Fysisk iPhone og faktisk Pluto-retur mangler brugeraccept. Ingen brokerhandler eller ændringer af handelsmandatet blev udført som led i releasen.
