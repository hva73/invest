# Accepttestmatrix — design v1.0

Alle T01–T28 er specificeret i `tests/fixtures/design-v1-acceptance.json`. Filen er et testgrundlag, ikke en schema_version 2-rapport og må ikke sendes til produktionsindbakken.

**Baseline:** eksisterende arbejdsudgave 162d41f. Det kommende redesign er ikke implementeret eller samlet godkendt. Tabellen beskriver dækning og konkrete huller; eksisterende dækning er ikke automatisk en bestået sluttest.

| Test | Scenario | Baselinestatus | Evidens / mangler |
|---|---|---|---|
| T01 | Positiv dagsændring | Kildereference mangler | Pluto previous_close er null; CSS-farven er separat browserkontrolleret. |
| T02 | Negativ dagsændring | Kildereference mangler | Samme referencemangel som T01; rød klikfarve er browserkontrolleret. |
| T03 | Positiv dag, negativt urealiseret P/L | Afventer implementering | Ny fælles komponent og neutral absolut værdi mangler. |
| T04 | Gevinst og SÆLG-vurdering | Afventer implementering | Eksisterende separation er delvist testet; værdifeltet farves endnu efter P/L. |
| T05 | Ukendt kurs | Delvis dækning | Ukendt beløb testes; endelig fælles referencevisning mangler. |
| T06 | Gammel analyse med faktisk position | Afventer implementering | Aktuel oversigt er rapportbaseret, ikke komplet brokerbaseret. |
| T07 | FRAVÆLG med faktisk position | Delvis dækning | Kandidatprojektion bevarer ejerskab; samlet beholdningsvisning skal omlægges. |
| T08 | Delvis fyldning og efterfølgende annullering | Delvis dækning | Backend bevarer CANCELLED og fyldt antal; ny 24h-gruppering mangler. |
| T09 | Terminale kandidater og sekundære filtre | Eksisterende dækning; skal gentages | Udvidet browser_hotwatch_engine kontrollerer kombinerede filtre. |
| T10 | Fejlramt motorsession | Delvis dækning | Backend-fejltilstande er testet; ny prioriteret advarselsvisning mangler. |
| T11 | Samme ticker i to depoter | Eksisterende dækning; skal gentages | Eksisterende positions- og browsertests; gentages mod ny brokerprojektion. |
| T12 | Root inkluderer AI | Eksisterende dækning; skal gentages | Root-only summering findes; ny oversigt skal bevare samme invariant. |
| T13 | Manglende FX | Delvis dækning | Eksisterende kildevaluta bevares; nye DKK-kolonner og årsagskomponent mangler. |
| T14 | Afventer trigger | Afventer implementering | Nuværende filter er ikke den godkendte sammenklappede gruppe. |
| T15 | Udeladt kandidat bevares | Eksisterende dækning; skal gentages | MCP 2.5.1 og kandidatlivscyklus har konkret to-rapporttest. |
| T16 | Append-only statusændring | Eksisterende dækning; skal gentages | Kandidat- og MCP-tests kontrollerer readback, journal og duplicate. |
| T17 | Klikbare farver og hover | Eksisterende dækning; skal gentages | Computed style og tekstretning kontrolleret i browser_positions, ikke kun klassenavne. |
| T18 | Inkompatibel siden-sidst | Afventer implementering | Intet generelt kompatibilitetsmærket observationstil-observation-lager. |
| T19 | Aktiv live-quote forældelse | Afventer implementering | Visningen anvender nu generelle 10/30-minutgrænser. |
| T20 | Åbent intradag-snapshot | Afventer implementering | Central datatypeafhængig 300s-visningspolitik mangler. |
| T21 | Positionsanalyse 24h | Afventer implementering | Fælles 24h-analyseindikator og brokerbaseret oversigt mangler. |
| T22 | Session, weekend og helligdag | Kildereference mangler | Ingen verificeret venuekalender installeret; syntetisk kalender kan kun teste logikken. |
| T23 | 12+ kompakte mobilpositioner | Afventer implementering | Eksisterende side med 12 positioner er meget lang; layoutændring ikke lavet. |
| T24 | Responsivt layout | Delvis dækning | Nuværende layout er browserkontrolleret; kommende redesign skal kontrolleres igen. |
| T25 | Original historisk rapport | Eksisterende dækning; skal gentages | Rapportreadback og historik bevares i eksisterende tests. |
| T26 | Rapport og broker i konflikt | Afventer implementering | Fælles brokerbaseret positions-/afstemningsvisning mangler. |
| T27 | Datakildeudfald og kritisk advarsel | Delvis dækning | Motor-fejlhåndtering findes; samlet kritisk-liste og hændelsesafklaring mangler. |
| T28 | Handels- og godkendelsesregression | Eksisterende dækning; skal gentages | Eksisterende trade-/browser-/autorisationsregression skal genkøres efter hver relevant ændring. |

## Syntetiske referencer og kørselsregler

Testtid låses eksplicit. T01–T04 anvender kendte syntetiske priser, tidligere officiel close, fuldt kostgrundlag og eventuelle omkostninger. Deres verificeringsmarkering gælder kun fixture-data, ikke et faktisk EODHD-/Pluto-opslag. Ingen baglæns udledning af officielle kildedata.

T18 køres separat for hver inkompatibel dimension, også manglende og ikke kun forskellige metadata. T19–T21 tester før/på/efter grænserne. T22 bruger eksplicitte syntetiske kalendersessioner samt UNKNOWN-fallback, og kræver senere særskilt verifikation af den rigtige kalenderintegration. En weekendtest alene er utilstrækkelig.

T23–T24 skal kontrollere tekst/kolonner og datagrundlag samt visuelt layout, ikke bare scrollWidth. T28 skal både afvise uautoriserede kald og kontrollere, at rent læse-/visningsarbejde ikke udfører broker-write eller ændrer historiske rapporter.

Planlagt evidens pr. test: faktisk kodeversion, fixture-ID, kommando, resultat (PASS/FAIL/BLOCKED/NOT_RUN), begrundelse og eventuelt screenshot. Ingen xfail/skip må tælles som PASS.

## Faktisk kørt baselinekontrol

3. november 2026, eksisterende runtime på arbejdsgrundlaget 162d41f:

- `python3 -m unittest discover -s tests -p 'test_*.py'`: **254 tests, OK**, 46,245 sekunder. Alle tests bruger lokale/midlertidige databaser og simulerede eller syntetiske kilder.
- `node tests/test_attention.js`: bestået.
- `node tests/test_format.js`: bestået.
- `node tests/test_freshness.js`: bestået for de eksisterende 10/30-minutgrænser. Det er **ikke** evidens for de nye 60s/300s/24h-grænser, som endnu ikke er implementeret.
- Specifikationen er bevaret byte-for-byte fra uploaden. SHA256: `4896d150bb2b077295d73807f049e4dcb6b44057386bd1826ba0c231bba091a7`.
- Testmanifestet er kontrolleret for præcis 28 unikke ID'er T01–T28, syntetiske input og eksplicitte forventninger.

Fordeling: 8 med eksisterende delområde-dækning, 7 delvist dækkede, 10 afventer implementering, 3 mangler kilde-/kalenderreference. Dette er ikke 8 fulde endelige PASS og ikke en godkendelse af hele redesignets accepttest.

Forudgående browserkontrol og screenshots fremgår af DESIGN_REVIEW_AND_DECISIONS_DA.md. De viser den nuværende arbejdsudgave, ikke et nyt færdigt design. Ingen produktionskonto, rigtig Pluto-ordre eller live EODHD-konto er anvendt i denne baselinekontrol.
