# ESCAPE Invest v2.3 RC1

**Status: releasekandidat til review.** Den præcise commit-SHA og resultater fra samlet test samt kapacitetskontrol registreres i [Issue #57](https://github.com/hva73/invest/issues/57). Kandidaten er ikke godkendt eller installeret i produktion.

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

Den samlede kandidats CI, review, nøjagtige commit, aktuelle kapacitet og faktiske installationsstatus dokumenteres i #57. Ejeren skal særskilt godkende den præcise SHA før eksisterende SSH-deployment anvendes. Der udføres ingen automatiske brokerhandler eller ændringer af handelsmandatet som led i releasen.
