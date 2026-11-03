# ESCAPE Invest – Endelig design- og statusspecifikation

**Version:** 1.0 – godkendt designgrundlag  
**Repository:** `hva73/invest`  
**Arbejdsbranch:** `codex/design-review-wip`  
**Grunddokument:** `docs/DESIGN_REVIEW_AND_DECISIONS_DA.md`

**Status:** Klar til implementeringsplan og syntetiske accepttests. Ingen installation, produktionsændring eller release er godkendt.

## 1. Formål og ufravigelige principper

ESCAPE Invest skal være et kompakt, professionelt og letforståeligt investeringsdashboard, hvor brugeren hurtigt kan se:

- Hvad ejer jeg?
- Hvad tjener eller taber jeg?
- Hvad har ændret sig siden sidst?
- Hvad kræver min opmærksomhed?
- Hvilke nye muligheder er opdaget?
- Hvilke data er aktuelle, forældede eller mangler?

Følgende principper er bindende:

1. Historik er permanent og må ikke slettes eller overskrives ved almindelig filtrering.
2. Aktive visninger må ikke vokse ubegrænset med afsluttede, fravalgte eller arkiverede kandidater.
3. Pluto er autoritativ for faktiske beholdninger, handler og ordrestatus.
4. Rapportens anbefalinger, kandidatens lifecycle og brokerens udførelse er tre uafhængige dimensioner.
5. Ingen grønne/røde tal eller pile uden et dokumenteret sammenligningsgrundlag.
6. Ingen dobbeltoptælling af hoveddepot og AI-Collection.
7. Manglende data må aldrig erstattes af opdigtede værdier.
8. Eksisterende rapporter, candidate_id, trade_cycle_id, journal og lifecycle_history skal bevares.
9. Ændringer skal være bagudkompatible med eksisterende rapporter og MCP-integration.
10. Ingen ændring af handelsmandater, godkendelsesflow, automatisering eller aktiv strategi.

## 2. B1 – Overblik og navigation

### Godkendt

Alle faktiske beholdninger vises på Overblik i én kompakt liste.

### Standardrækkefølge

1. Samlet depotværdi og dagens resultat.
2. Kritiske handlinger og uafklarede ordrer.
3. Alle beholdninger i kompakt visning.
4. Nye købssignaler og væsentlige HOT WATCH-ændringer.
5. Kort status for datakvalitet og seneste synkronisering.

Hoveddepotets samlede værdi inkluderer AI-Collection. AI-værdien må vises separat, men aldrig lægges oven i hoveddepotets samlede værdi.

Fjern gentagne kontokort og rapportopgørelser fra standardvisningen.

Bevar alle otte eksisterende funktioner. Gruppér navigationen visuelt uden at fjerne funktionalitet.

## 3. B2 – Beholdninger på desktop og mobil

### Desktop – standardkolonner

1. Ticker og kort navn.
2. Depot/Collection.
3. Antal.
4. Seneste kurs og originalvaluta.
5. Dagens kursændring i procent.
6. Kursændring siden sidste sammenlignelige måling i procent.
7. Positionsværdi i DKK, hvis verificerbar.
8. Urealiseret P/L i DKK og procent.
9. Seneste individuelle anbefaling.
10. Datatid eller kompakt friskhedsmarkering.

### Mobil – kompakt positionsrække

**Linje 1:** Ticker, depotmarkør og positionsværdi.

**Linje 2:** Dagens ændring med farve/pil og urealiseret P/L med farve/fortegn.

**Linje 3, kun når relevant:** Siden-sidst-ændring, handlingsstatus eller kritisk advarsel.

Seneste kurs og datatid skal være tilgængelige uden at åbne en lang analyse, eksempelvis via en kompakt sekundær tekstlinje eller en let tilgængelig detaljevisning.

### Positionsdetaljer

Vis antal, kostpris, anskaffelsesværdi, seneste kurs, datakilde, tidsstempler, spread, risikovurdering, næste trigger, analyse, historik, relaterede ordrer og kilder.

### Sortering

Standard:

1. Kritisk handling.
2. Depot/Collection.
3. Positionsværdi, størst først.

Tilbyd sortering efter dagsændring, urealiseret resultat, værdi og ticker.

Samme ticker i to depoter skal fremstå som to forskellige positioner.

## 4. B3 – Farver, pile og finansielle referencer

| Felt | Sammenligningsgrundlag | Præsentation |
|---|---|---|
| Dagens kursændring | Seneste sammenlignelige kurs mod forrige officielle lukkekurs | Grøn ↑ / rød ↓ / neutral → |
| Siden sidst | To tidsstemplede observationer af samme pristype | Grøn ↑ / rød ↓ / neutral → |
| Seneste kurs | Absolut markedspris | Neutral |
| Positionsværdi | Aktuel værdi | Neutral |
| Urealiseret P/L | Aktuel værdi minus dokumenteret kostgrundlag og relevante kendte omkostninger | Grøn + / rød − |
| Realiseret P/L | Bekræftede handler, anskaffelsesgrundlag og omkostninger | Grøn + / rød − |
| Dagens depotresultat | Sammenlignelige porteføljeværdier korrigeret for pengestrømme | Grøn ↑ / rød ↓ |
| Kontanter, antal og kostpris | Ingen resultatmæssig reference | Neutral |

Vigtige regler:

- Farver skal fungere på klikbare tal, links og ved hover.
- Positiv kursudvikling og negativt urealiseret resultat kan vises samtidigt.
- En position i gevinst kan godt have anbefalingen SÆLG.
- Handlingers farver må ikke forveksles med kursretning.
- Ukendt sammenligningsgrundlag vises neutralt som `—`.
- Ingen beregning af siden-sidst ved blanding af inkompatible feeds, markedsfaser, valutaer eller prisdefinitioner.
- Tidsstempler skal kunne eftervises.
- For premarket/aftermarket skal reference og markedssession fremgå.
- Depotresultat må ikke beregnes som ren forskel mellem to kontoværdier, hvis indskud, hævninger eller andre pengestrømme gør sammenligningen misvisende.

## 5. B4 – Kandidater og lifecycle

Lifecycle-statusser:

- DISCOVERED
- ANALYZING
- HOT_WATCH
- WAITING_TRIGGER
- BUY_SIGNAL
- ORDER_PENDING
- POSITION_OPEN
- EXIT_WATCH
- CLOSED
- ARCHIVED

Beslutningsstatusser:

- KØB
- AFVENT
- FRAVÆLG

Brokerudførelse håndteres separat.

### Godkendt

WAITING_TRIGGER placeres i en separat, sammenklappet gruppe. Gruppen viser antal, prioritet, næste trigger og deadline.

### Standardvisning

| Lifecycle | Primær visning | Overblik | Historik |
|---|---|---|---|
| DISCOVERED | Radar – nye fund | Nej | Ja |
| ANALYZING | Radar – under analyse | Nej | Ja |
| HOT_WATCH | HOT WATCH – aktiv | Ved væsentlig ændring | Ja |
| WAITING_TRIGGER | HOT WATCH – sammenklappet afventergruppe | Kun ved relevant trigger | Ja |
| BUY_SIGNAL | Radar/HOT WATCH og relevant handelsforslag | Ja | Ja |
| ORDER_PENDING | Handelsmotor | Ja | Ja |
| POSITION_OPEN | Beholdninger ved verificeret Pluto-ejerskab | Ja | Ja |
| EXIT_WATCH | Beholdninger/HOT WATCH | Ved relevant risiko | Ja |
| CLOSED | Historik | Nej | Ja |
| ARCHIVED | Arkiv | Nej | Ja |

FRAVÆLG uden faktisk position, aktiv ordre eller dokumenteret ny trigger skjules fra aktive kandidatlister.

FRAVÆLG med faktisk Pluto-position må aldrig skjule beholdningen.

CLOSED og ARCHIVED må ikke komme tilbage i aktive lister på grund af opmærksomhedsfiltre.

Arkivering er ikke sletning. Historiske kandidater skal kunne genåbnes ved dokumenteret ny katalysator.

En manglende kandidat i næste rapport er ikke en sletteinstruktion.

## 6. B5 – Friskhed, deadlines og gamle data

### Godkendte standardgrænser

| Datatype | Grænse | Handling |
|---|---|---|
| HOT WATCH live-quote | 60 sekunder ved aktivt marked | Markér forældet |
| Intradag-snapshot | 5 minutter ved åbent marked | Markér forældet |
| Positionsanalyse | 24 timer | Markér analyse forældet |

En væsentlig ny begivenhed kan gøre en analyse forældet før 24 timer.

### Øvrige regler

- Ved lukkede markeder bruges seneste relevante handelssession med tydelig sessionstid.
- Weekender og helligdage må ikke fejlagtigt behandles som almindelige åbne handelstimer.
- Dokumenteret feed-forsinkelse skal fremgå.
- En kandidat uden deadline må ikke automatisk slettes eller erklæres udløbet.
- Købsforslag kræver konkret gyldighedsperiode; udløb af et forslag ændrer ikke en faktisk brokerordre.
- Gamle nyheder bevares med oprindelig publiceringstid, men må ikke fremstå som NYE.
- Manglende ny rapport skal markeres som forsinket, ikke erstattes af gamle værdier med nyt tidspunkt.
- Faktiske positioner og kritiske advarsler må aldrig forsvinde på grund af dataalder.
- Ældre rapportmålinger vises sammenfoldet som standard.

Implementér friskhedsreglerne centralt, så alle sider bruger samme beregning.

## 7. B6 – Ordrestatus

| Status | Standardplacering |
|---|---|
| PROPOSED | Handelsmotor – forslag |
| AWAITING_APPROVAL | Overblik og Handelsmotor |
| SUBMITTED | Aktive ordrer |
| ACCEPTED | Aktive/uafklarede ordrer |
| PARTIALLY_FILLED | Aktive ordrer og faktisk position |
| FILLED | Seneste hændelser og journal |
| CANCELLED | Seneste hændelser og journal |
| REJECTED | Journal og relevant advarsel |
| EXPIRED | Historik |
| UNKNOWN | Særskilt uafklaret ordregruppe |

ACCEPTED betyder ikke FILLED.

Ved delvist fyldt og efterfølgende annulleret ordre skal faktisk fyldt antal bevares, mens den resterende ordre markeres afsluttet.

Afsluttede ordrer vises som udgangspunkt i seneste hændelser i 24 timer, derefter i historikken.

UNKNOWN må ikke automatisk omklassificeres til afsluttet.

En overskredet rapportdeadline må aldrig ændre en faktisk Pluto-ordre.

Ingen ændring af eksisterende godkendelsesflow.

## 8. B7 – HOT WATCH-sessioner

| Sessionstatus | Standardvisning |
|---|---|
| CREATED | Afventer opstart |
| VALIDATING | Under opstart |
| ACTIVE | Aktiv |
| PAUSED | Separat pausegruppe |
| DEGRADED | Driftsadvarsel |
| ERROR | Kritisk driftsadvarsel |
| EXPIRED | Historik |
| COMPLETED | Historik |

Afsluttede sessioner må ikke fremstå som aktiv overvågning.

Motorens observationer og rapportafsenderens anbefalinger skal mærkes med tydelig kilde.

Vis seneste måling, datatid, status og næste relevante trigger. Lange observationshistorikker åbnes i detaljer.

## 9. B8 – Pluto-afstemning

Pluto er autoritativ for:

- Faktiske depoter og Collections.
- Beholdningsantal og ejerskab.
- Brokerordrer og udførelsesstatus.
- Bekræftede fills.
- Tilgængelige handelsfunktioner.

Alle verificerede Pluto-positioner skal fremgå af beholdningslisten, også uden analyse.

Kobl rapportvurderinger via depotidentitet, asset_id og stabil positions-/handelsforløbsidentitet. Ticker alene er utilstrækkeligt.

Ved konflikt:

1. Vis verificeret Pluto-status som faktisk handelsstatus.
2. Bevar rapportens oprindelige oplysninger i historikken.
3. Vis tydelig afstemningsadvarsel.
4. Foretag ingen automatisk køb/salg eller omskrivning af historik.

Ved Pluto-udfald må senest kendte beholdning kun vises som ikke aktuelt verificeret, med oprindeligt tidspunkt.

Root inkluderer AI. Ingen dobbeltoptælling.

## 10. B9 – Datakontrakt

### Position

| Felt | Primær ansvarlig |
|---|---|
| portfolio_id / Collection | Pluto |
| position_id / stabil kobling | Pluto og app |
| asset_id | Pluto |
| ticker / navn | Pluto |
| antal | Pluto |
| kurs / valuta | Pluto eller verificeret EODHD-kilde |
| kurstid | Faktisk kilde |
| kostpris | Pluto, hvis tilgængelig |
| markedsværdi | Pluto eller verificerbar appberegning |
| urealiseret P/L | Pluto eller appberegning |
| individuel anbefaling | ChatGPT/rapport |
| begrundelse / næste trigger | ChatGPT/rapport |
| analyse- og kildetid | ChatGPT/rapport |
| siden-sidst-ændring | Appberegning |

### Kandidat

| Felt | Primær ansvarlig |
|---|---|
| candidate_id | Rapport og appens persistens |
| trade_cycle_id | Rapport og appens persistens |
| ticker / børs / asset_id | Pluto-verifikation |
| lifecycle og ændringstid | Rapport + appens append-only historik |
| beslutning | ChatGPT/rapport |
| katalysator og kilder | ChatGPT med verificeret nyhedskilde |
| kurs, volumen, spread, datatid | EODHD/Pluto efter faktisk tilgængelighed |
| deadline og næste trigger | ChatGPT/rapport |
| historiske statusovergange | Appens persistens |

### Ordre

| Felt | Primær ansvarlig |
|---|---|
| ordre-ID | Pluto |
| depot / asset_id | Pluto |
| side / ordretype | Pluto |
| ønsket antal | Pluto |
| fyldt antal | Pluto |
| status og statustid | Pluto |
| faktisk fyldningspris | Pluto |
| rapporteret anbefaling | ChatGPT/rapport |
| kobling til candidate_id/trade_cycle_id | App + verificerbar rapportreference |

### Manglende data

Foreslåede bagudkompatible årsagskoder:

- NOT_PROVIDED
- NOT_FETCHED
- STALE
- SOURCE_ERROR
- NOT_APPLICABLE

Eksisterende schema_version 2 skal fortsat accepteres. Nye maskinlæsbare årsagsfelter må kun indføres med dokumenteret bagudkompatibilitet.

Ukendte værdier vises som `—`, ikke `0`.

Appen skal skelne mellem faktisk kildefejl, manglende data, forældede data og ikke-relevante felter.

Ingen generiske AI-tekster eller opdigtede værdier til at fylde tomme felter.

## 11. B10 – Tal og valuta

- DKK-beløb: normalt 2 decimaler.
- Procenter: 2 decimaler med fortegn ved ændringer.
- Almindelige aktiekurser: relevant præcision, normalt 2–4 decimaler.
- Små kryptokurser: tilstrækkelig præcision til aldrig at fremstå som falsk nul.
- Fractional-antal: bevar nødvendig præcision.
- Originalvaluta vises ved kurs.
- Positionsværdi og P/L vises i DKK, når FX er dokumenteret.
- Ved manglende FX vises originalvaluta.
- Ukendt beløb må aldrig fremstå som nul.
- Dato og klokkeslæt vises på dansk, men bevares tidszonekorrekt i data.
- Fuld præcision skal være tilgængelig i detaljer.

## 12. B11 – Visuelt design

### Godkendt

Behold mørk ESCAPE-stil.

### Designkrav

- Kompakt layout og tydeligt visuelt hierarki.
- Mindre gentagelse af de samme tal.
- Tydelige sektioner uden store ensartede paneler.
- Grøn/rød farve på finansielle ændringer.
- Tydelige retningspile.
- Neutral farve på almindelige værdier.
- Læsbar tekst og passende kontrast.
- Kompakte desktop-tabeller.
- Kompakte mobilrækker.
- Store nok trykflader og synlig tastaturfokus.
- Ingen vandret sidescroll i normal mobilvisning.
- Lange beskrivelser, historik og teknik sammenfoldes.
- Kritiske handlinger må ikke skjules bag standardfiltre.

### De otte sider

**Overblik:** Værdi, dagsresultat, handlinger, alle kompakte beholdninger, nye signaler.

**Porteføljer:** Root og AI korrekt hierarkisk, kontanter, beholdninger og ordrer.

**Radar:** Nye fund, aktuelle beslutninger, aktive kandidater; historiske kandidater via filter.

**HOT WATCH:** Aktive kandidater, sammenklappet WAITING_TRIGGER, sessionstilstand, aktuelle ændringer.

**Handelsmotor:** Godkendelser, aktuelle forslag, åbne og uafklarede ordrer først.

**Handelsjournal:** Kompakt tidslinje, kilde, type, status og resultat.

**Analyser:** Resumé og indholdsfortegnelse først; fulde rapporter i detaljer.

**Forbindelser:** Faktisk Pluto/EODHD/ESCAPE-status, synkronisering og fejl; tekniske diagnoser i detaljer.

## 13. B12 – Journal, historik og kildekonflikter

Journalens standardperiode er de seneste 7 dage.

Uafklarede kritiske hændelser vises uanset alder.

Brug én samlet tidslinje med kildemærker:

- Pluto
- Trading Radar
- HOT WATCH Engine
- App/system

Tilbyd filtrering efter hændelsestype og tidsperiode.

Historiske rapporter skal kunne vises fuldstændigt og uændret.

En historisk rapport må gerne indeholde kandidater, som i dag er CLOSED eller ARCHIVED. Aktive filtre må ikke omskrive originalrapporten.

Ved konflikt mellem rapport og Pluto:

- Faktisk brokerstatus følger Pluto.
- Rapportens oprindelige udsagn bevares.
- Afvigelsen markeres.
- Ingen automatisk ordre- eller historikændring.

## 14. Særlige regler mod voksende lister

1. Aktive lister bygges ud fra dokumenteret aktuel status, ikke samtlige historiske rapportposter.
2. CLOSED/ARCHIVED skjules fra aktive visninger.
3. FRAVÆLG uden position/ordre/ny trigger skjules fra aktive kandidatlister.
4. WAITING_TRIGGER vises separat og sammenklappet.
5. Afsluttede HOT WATCH-sessioner flyttes til historikvisning.
6. Afsluttede ordrer flyttes til journal efter perioden for seneste hændelser.
7. Alle faktiske positioner forbliver synlige.
8. Historiske candidate_id og trade_cycle_id bevares.
9. Manglende rapportopdatering må ikke automatisk slette en kandidat.
10. Statusændringer skal kunne eftervises i lifecycle_history.
11. Filtre skal kombineres logisk, så et sekundært filter ikke genåbner terminale poster.
12. Optællinger skal følge samme filtre som de viste poster.

Der må ikke indføres automatisk sletning eller permanent arkivering alene på baggrund af alder.

## 15. Accepttests

Codex skal demonstrere følgende med syntetiske data:

**T01:** Positiv dagsændring giver grøn pil og korrekt fortegn.

**T02:** Negativ dagsændring giver rød pil og korrekt fortegn.

**T03:** Grøn dagsændring og negativt urealiseret P/L vises korrekt samtidigt.

**T04:** Positivt P/L og SÆLG-vurdering vises uden farvekonflikt.

**T05:** Ukendt kurs giver neutral visning og ingen opdigtet procent.

**T06:** Gammel analyse skjuler ikke en faktisk åben Pluto-position.

**T07:** FRAVÆLG med ejet position skjuler kun nykøbskandidaten, ikke beholdningen.

**T08:** Delvist fyldt, derefter annulleret ordre bevarer faktisk fill og lukker resterende ordre.

**T09:** CLOSED/ARCHIVED skjules fra aktive lister og kan findes i historik.

**T10:** ERROR/DEGRADED-session giver tydelig driftsadvarsel.

**T11:** Samme ticker i to depoter giver to adskilte positioner.

**T12:** Root og AI giver ingen dobbeltoptælling.

**T13:** Manglende FX giver ingen falsk DKK-konvertering.

**T14:** WAITING_TRIGGER er sammenklappet som standard og viser korrekt antal.

**T15:** Historisk kandidat, som mangler i seneste rapport, er fortsat søgbar med bevaret historik.

**T16:** Statusændring på samme candidate_id og trade_cycle_id registreres append-only.

**T17:** Positiv/negativ farve og pile fungerer også på klikbare tal og hover.

**T18:** Siden-sidst-beregning afvises ved inkompatible datakilder eller markedsfaser.

**T19:** Live-quote ældre end 60 sekunder markeres forældet ved aktivt marked.

**T20:** Intradag-snapshot ældre end 5 minutter markeres forældet ved åbent marked.

**T21:** Positionsanalyse ældre end 24 timer markeres forældet, uden at positionen skjules.

**T22:** Lukket marked, weekend og helligdag håndteres korrekt.

**T23:** 12 eller flere positioner vises kompakt på mobil uden unødigt lange gentagne analyseblokke.

**T24:** Responsivt layout fungerer ved 320, 375, 390, 430, 768, 1024, 1280, 1440 og 1920 px.

**T25:** Gamle rapporter kan åbnes komplet og uændret.

**T26:** Konflikt mellem rapport og Pluto vises som afstemningsproblem uden falsk udførelse.

**T27:** Manglende EODHD- eller Pluto-data skjuler ikke kritiske advarsler.

**T28:** Alle eksisterende godkendelses- og handelssikkerhedsregler består regressionstest.

## 16. Implementeringsrækkefølge

**Fase 1 – Datakorrekthed og statusfiltrering**

Fælles statusprojektion, lifecycle-filtre, Pluto-afstemning, historikbevarelse og korrekte optællinger.

**Fase 2 – Finansielle visningskomponenter**

Fælles talformatering, farver, pile, friskhed og sammenligningsgrundlag.

**Fase 3 – Beholdninger og Overblik**

Kompakte desktop-/mobilvisninger, alle positioner, ingen dobbeltoptælling.

**Fase 4 – Radar, HOT WATCH og Handelsmotor**

Statusgrupper, sammenfoldning, handlingsprioritering og oprydning i historiske poster.

**Fase 5 – Journal, Analyser og Forbindelser**

Kompakt tidslinje, historisk arkiv og tydelig driftsstatus.

**Fase 6 – Samlet test og releaseforberedelse**

Browser- og regressionstests, datakontraktkontrol og dokumenteret integrationstest.

Den ventende MCP 2.5.1-læserettelse skal koordineres med den samlede leverance. Ingen installation før særskilt godkendelse.

## 17. Afleveringskrav til Codex

Codex skal levere:

1. Implementeringsplan opdelt i ovenstående faser.
2. Oversigt over ændrede frontendmoduler og eventuelle nødvendige bagudkompatible schemaændringer.
3. Dokumenteret statusmatrix.
4. Dokumenteret feltkontrakt og kildeansvar.
5. Screenshots fra mobil og desktop.
6. Resultater af samtlige accepttests.
7. Liste over eventuelle manglende datakilder og rettigheder.
8. Liste over uafklarede tekniske spørgsmål.
9. Bekræftelse på, at historik, rapporter og handelsflow ikke er ændret utilsigtet.
10. Releaseplan med rollback.

**Stop før installation.**

Hvis eksisterende kode eller data ikke understøtter en regel, skal Codex rapportere den konkrete afvigelse og foreslå en bagudkompatibel løsning. Der må ikke gættes, slettes historik eller ændres handelsadfærd for at opnå et pænere dashboard.
