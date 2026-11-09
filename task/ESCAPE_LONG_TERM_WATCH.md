# ESCAPE Invest — LONG-TERM WATCH
## Opgave til Codex · langsigtet observation af aktier

**Formål:** Udvid ESCAPE med en enkel Long-Term Watch, så vi kan følge interessante aktier i måneder og år — også efter et salg — og lære af vores handler. Byg videre på den eksisterende løsning. **Plug-and-play, ingen unødigt bureaukrati.**

### 1. Fra salg til observation
- Når et faktisk salg er gennemført i Pluto, tilbyd valgene **Afslut** og **Følg langsigtet**.
- Man skal også kunne tilføje aktier manuelt, inklusive aktier vi stadig ejer.
- Brug Pluto asset-ID som identitet; gem navn, ticker, observationsdato, referencekurs og relevante faktiske køb/salg.
- Long-Term Watch er ikke en beholdning. Ingen dobbelttælling i porteføljeværdi, beholdninger eller P/L.
- Mulighed for at fjerne observationer uden at slette handels- eller kurshistorik.

### 2. Daglig historik og graf
- Hent tilgængelig historik ved oprettelse, og gem **én faktisk officiel lukkekurs pr. handelsdag** via eksisterende EODHD-data; opdatér efter hver børsdag i det relevante marked.
- Graf med **1M / 3M / 6M / 1Å / hele perioden**, kurs i beløb og procent, udvikling fra observationsstart og siden sidste salg.
- Markér vores køb og salg med **Plutos faktiske handler**; vis en relevant indeks-/sektorsammenligning når data findes.
- Korrekt split-/corporate-action-justering og sammenlignelige historiske kursserier. Bevar kilde, dato, valuta og justeringsgrundlag.
- **Ingen median, interpolation, konstruerede minut-/dagskurser eller kunstige punkter på lukkedage.** Manglende data forbliver manglende.

### 3. Analytikerkursmål
- Vis laveste, gennemsnitligt og højeste dokumenterede kursmål, antal analytikere, anbefalingsfordeling, kilde, opdateringsdato og tidshorisont, **når disse data er til rådighed**.
- Bevar tidligere kursmål, så ændringer kan vises over tid; vis afstand fra kursen til målene i procent.
- Forældede mål markeres tydeligt. Intet kursmål må gættes eller fremstilles som et sandsynligt afkast.

### 4. Rolig opfølgning
- **Kursen opdateres efter hver handelsdag.**
- Lav en **kort ugentlig vurdering** af tendens, relevante nyheder og udvikling imod mål.
- Fremhæv betydningsfulde begivenheder: regnskaber, ny kapital, store analytikerændringer, selskabsnyheder — ved biotek også kliniske resultater, forsøgsfaser, godkendelser og finansiering.
- Ingen ny realtidsmotor nødvendig; genbrug eksisterende scanning, historik og kilder.

### 5. Læring af solgte positioner
- Vis det **faktisk realiserede** handelsresultat fra Pluto adskilt fra efterfølgende kursudvikling.
- Vis, hvad en tidligere solgt mængde **hypotetisk** ville have været værd i dag, og udviklingen sammenlignet med et relevant marked. Mærk det tydeligt som hypotetisk og uden for regnskabet.
- Formålet er at kunne se, om bestemte typer aktier regelmæssigt sælges for tidligt.

### 6. Kildeansvar
- **Pluto:** Beholdning, ejerskab, ordrefyldninger, faktiske køb/salg, handelspriser og porteføljens økonomiske tal.
- **EODHD:** Historiske og daglige faktiske lukkekurser, markedsgrafer og relevant analyse.
- Eksisterende nyhedskilder/analytikerkilder bruges kun, hvor data er verificerbare. Vis 'data mangler', når de ikke er det.
- EODHD-priser må ikke overskrive Plutos portefølje-/handelspriser.

### 7. Enkel brugerflade
- Ny sektion **LONG-TERM WATCH**, i ESCAPEs eksisterende layout: navn/ticker, kurs, udvikling, analytikermål, tendens og seneste væsentlige begivenhed.
- Klik giver detaljevisning med daglig graf, tidligere handler, kursmålhistorik og nyheder.
- Enkel manuel tilføj/fjern og markering: **Observer / Interessant langsigtet / Revurdér**.
- Kan eksistere samtidig med HOT WATCH, men skal være logisk og operationelt adskilt. Ingen autoordrer, handelsforslag eller ændringer i stop-loss.

### 8. Første praktiske eksempel: CABA
Cabaletta Bio (CABA) skal kunne observeres langsigtet allerede mens vi ejer aktien — og fortsat efter et eventuelt salg. Følg daglig kurs, relevante kliniske milepæle, dokumenterede analytikermål samt vores faktiske historiske handler.

## Udførelse
Genbrug eksisterende arkitektur, UI, datamodeller, historik og datakilder. Lav den mindste enkle og robuste ændring, der giver en **færdig brugbar funktion i én samlet installation**. Almindelig kvalitetskontrol er fint, men **ingen store dokumentationspakker, lange testrapporter eller nyt kontrolhierarki**. Byg det plug-and-play.
