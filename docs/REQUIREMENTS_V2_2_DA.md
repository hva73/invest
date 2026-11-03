# ESCAPE INVEST — TILLÆG V2.2
## Endelig kravspecifikation til Codex
**Dato:** 3. november 2026<br>
**Status:** Implementering før endelig færdiggørelse<br>
**Prioritet:** Høj<br>
**Grundlag:** Eksisterende ESCAPE Invest v2, Trading Radar v3.8 og HOT WATCH v1.0

---

## 1. FORMÅL

Dette dokument er et tillæg til den eksisterende kravspecifikation for ESCAPE Invest.

ESCAPE Invest skal fungere som et samlet kontrolcenter for vores AI-understøttede investeringer med:

- Globale markedssignaler og beslutninger
- To Pluto-depoter uden dobbeltoptælling
- Individuelle positionsvurderinger
- Aktiv kandidat- og beslutningshistorik
- HOT WATCH og tidsstemplede observationer
- Ordrestatus og faktiske handelsresultater
- Verificerbar rapportlevering og datakvalitet

**VIGTIGT:** Dette er en udvidelse af eksisterende funktionalitet, ikke en ny applikation eller en erstatning for det eksisterende rapportformat.

Bevar eksisterende v1/v2-kompatibilitet, historik, API-endpoints, candidate_id, journal og fungerende visninger.

## 2. BESLUTNINGSMODEL — NYT KRAV

Hver aktiv handelskandidat skal have præcis én aktuel beslutning:

**KØB**
- Konkret købssignal
- Maksimal limitpris
- Foreslået beløb i DKK
- Tidshorisont og udløbstid
- Risikobudget, forventet upside/downside
- Dokumenteret exitmetode
- Godkendelsesstatus

**AFVENT**
- Kandidaten forbliver på aktiv watchlist
- Vis konkret årsag til at afvente
- Vis næste dokumenterbare trigger
- Vis deadline og seneste datatid
- Revurderes ved næste relevante scanning

**FRAVÆLG**
- Fjernes fra aktiv watchlist
- Historikken bevares
- Afvisningsårsag og tidspunkt registreres
- Kan genaktiveres ved dokumenteret ny katalysator eller væsentlig kurs-/volumenændring

En AFVENT-beslutning er en endelig beslutning for den aktuelle måling, ikke en uafsluttet analyse.

Der må ikke automatisk ændres fra AFVENT til KØB uden en ny dokumenteret beslutning.

Eksisterende positionsvurderinger BEHOLD, OVERVÅG, AFVENT, REDUCÉR og SÆLG skal fortsat understøttes separat fra kandidatbeslutninger.

## 3. KANDIDATHISTORIK OG BESLUTNINGSJOURNAL

Bevar stabile candidate_id på tværs af rapporter.

Tilføj eller udvid understøttelsen af:

- Første opdagelsestidspunkt
- Seneste observationstidspunkt
- Aktuel beslutning
- Tidligere beslutninger og statusovergange
- Beslutningsbegrundelse
- Katalysator og kilde
- Kurs ved første opdagelse
- Kurs ved beslutning
- Seneste verificerede kurs
- Næste trigger og deadline
- Eventuel tilknyttet ordre og handelsresultat

Historikken skal være append-only, hvor det er relevant. Tidligere rapporter og beslutninger må ikke overskrives af nyere vurderinger.

Ved genaktivering af en FRAVÆLG-kandidat genbruges samme candidate_id, og genaktiveringsårsagen journalføres.

Ingen dubletter for samme kandidat og begivenhed.

## 4. HOT WATCH — NY FUNKTION

Implementér HOT WATCH som særskilt visning i ESCAPE Invest.

HOT WATCH er et tidsafgrænset observationsworkflow, ikke en permanent streamingtjeneste.

For hver måling skal følgende kunne registreres og vises, når data findes:

- Ticker, børs og Pluto-aktiv-ID
- Observationstid i UTC og dansk tid
- Pluto-kurs og eventuelt separat kurstidspunkt
- Bid/ask og tilhørende timestamps
- Spread i absolut værdi og procent
- Seneste handler og volumen
- Intradagbevægelse og momentum
- Feedtype, venue og eventuel forsinkelse
- Aktuel beslutning
- Næste trigger
- Deadline
- Tilknyttet depotposition og ordrestatus

### HOT WATCH-historik

Vis udviklingen mellem observationer:

- Kursændring siden sidste måling
- Spreadændring
- Volumenændring
- Momentum: accelererende, aftagende eller ukendt
- Ændret beslutning og begrundelse

Manglende observationer må ikke udfyldes ved interpolation eller gætværk.

HOT WATCH skal kunne vise flere observationer af samme ticker uden at skabe nye kandidater for hver måling.

**MERC-forløbet den 3. november bruges som konkret accepttest.**

Systemet skal kunne vise købskurs, beholdning, observationer, salgsbeslutning, eventuelle aktive salgsordrer og faktisk fyldning som adskilte hændelser.

Der må ikke vises "solgt", før Pluto har bekræftet fyldningen.

### On-demand

Understøt, at nye HOT WATCH-målinger kan modtages fra Trading Radar og vises med det samme.

Der skal ikke implementeres en permanent WebSocket-daemon som del af dette tillæg.

## 5. DEPOTER OG KONSOLIDERING

ESCAPE Invest skal fortsat understøtte:

1. Pluto root / samlet konto
2. ESCAPE AI Trader
3. Hoveddepot eksklusive AI Trader

**Root inkluderer AI Trader.**

Root og AI Trader må aldrig summeres som to uafhængige samlede værdier.

Hoveddepot eksklusive AI må kun beregnes som root minus AI, når talgrundlag, valuta, tidspunkt og værdiansættelsesmetode er sammenlignelige.

Hvis dette ikke er opfyldt, vis "ukendt" frem for en misvisende beregning.

For hver position vises:

- Depot
- Ticker og aktiv
- Antal
- Anskaffelsespris, hvis tilgængelig
- Seneste Pluto-kurs
- Markedsværdi
- Urealiseret resultat
- Individuel vurdering
- Begrundelse
- Næste handling
- Aktive ordrer og fyldninger
- Datatid og datakilde

Samme ticker i begge depoter skal kunne have forskellige vurderinger og ordrer.

Kontanter opdeles i disponible, reserverede, øremærkede og ukendte beløb.

## 6. ORDRESTATUS OG GODKENDELSE

Udvid ordrevisningen, så følgende klart adskilles:

- Forslag
- Afventer godkendelse
- Godkendt
- Accepteret / aktiv
- Delvist udført
- Fuldt udført
- Annulleret
- Afvist
- Udløbet

Brug Plutos faktiske ordrestatus som autoritet. Visningsstatus må kun afledes med dokumenterede regler.

Eksempel:

STOP SELL ACCEPTED med filled_quantity = 0 betyder en accepteret, men ikke udført ordre.

Vis også:

- Ordretype
- Limit-/stoppris, hvis relevant
- Bestilt antal
- Fyldt antal
- Gennemsnitlig udførelseskurs
- Oprettelsestidspunkt
- Seneste statusændring
- Realiseret resultat, hvis beregneligt

Ingen hoveddepotordre uden udtrykkelig brugergodkendelse.

AI Trader skal respektere Plutos faktiske ejer-godkendelsesflow. Der må ikke antages autonom handelsadgang ud fra samlingens navn eller beskrivelse.

ESCAPE Invest må ikke selv oprette, ændre eller annullere Pluto-ordrer som følge af en rapport.

## 7. GLOBAL MARKEDSOVERSIGT OG DÆKNING

Rapportvisningen skal understøtte de fire eksisterende regioner:

- Europa / Norden
- USA / Canada
- Asien / Stillehav
- Råvarer / Metaller

Vis for hver region:

- Undersøgte børser
- Status: OK / FEJL / IKKE KØRT
- Antal screeningresultater
- Faktisk datadato
- Seneste nyhedskontrol
- Antal nye signaler
- Antal Pluto-verificerede kandidater
- Antal frasorterede
- Dokumenterede dækningshuller

Vis tydeligt, når screening er baseret på senest afsluttede handelsdag og ikke på intradagdata.

Der må ikke stå "global dækning gennemført", hvis væsentlige regioner ikke blev undersøgt.

## 8. DATAKVALITET OG KILDER

Alle relevante markedsobservationer skal kunne knyttes til:

- Datakilde
- Faktisk datatidspunkt
- Verificeringsstatus
- Marked/venue
- Feedtype
- Dokumenteret forsinkelse
- Eventuel primærkilde til nyheden

Bevar v2-formatets eksisterende regler:

market.price = pengeobjekt eller null

market.volume = streng eller null efter det faktiske skema

market.verification = verified / unverified / unknown

Forsinkede, men verificerede EODHD-data kan være verified, når faktisk datatid og forsinkelse er tydeligt dokumenteret.

Pluto-kurser skal mærkes "Pluto-kurs". De må ikke automatisk betegnes som forsinkede.

Manglende priser, spread, volumen eller gebyrer må ikke opfindes.

Alle source_ids skal referere til eksisterende kilder.

## 9. RAPPORTLEVERING OG DRIFTSSTATUS

Udvid den eksisterende rapportoversigt med en tydelig leveringsstatus:

- Modtaget
- Valideret
- Gemt
- Læst tilbage og verificeret
- Afvist ved validering
- Leveringsfejl
- Ukendt status

En rapport må først betegnes "sendt og læst tilbage", når modtagelse og efterfølgende kontrol er bekræftet.

Bevar eksisterende rapport-ID-format:

escape-hourly-YYYYMMDD-HH00-v2

Rapporttype:

intraday

Skemaversion:

schema_version: 2

Der må ikke oprettes dubletter ved genforsøg med samme report_id.

Hvis samme ID modtages med andet indhold, skal det håndteres som en konflikt, ikke som en tavs overskrivning.

Rapporthistorikken skal være uændret og læsbar.

Testdata og driftsdata skal fortsat være fuldstændigt adskilt.

## 10. BRUGERFLADE — AFSLUTTENDE FORBEDRINGER

Bevar det eksisterende design og tilføj funktionaliteten uden at gøre rapporterne unødigt tunge.

### Oversigt

Øverst vises:

- Samlet Pluto-værdi
- Hoveddepot eksklusive AI
- AI Trader
- Disponibel likviditet
- Seneste rapporttid
- Leveringsstatus
- Nye købssignaler
- Aktive HOT WATCH-kandidater

### Kandidatkort

Vis beslutning, kurs, nyhed, katalysator, risiko, næste trigger og seneste ændring.

### HOT WATCH

Separat visning med tidslinje, observationer, beslutningshistorik og tilknyttede positioner/ordrer.

### Positioner

Vis individuel vurdering og begrundelse for hver position.

### Historik

Mulighed for at følge en kandidat fra første opdagelse til afsluttet handel eller fravalg.

### Grav dybere

Bevar eksisterende funktionalitet og analysis_urls.

Hvis der ikke findes en gyldig analyse eller et gyldigt link, skal brugerfladen vise dette tydeligt frem for at generere et falsk link.

## 11. IMPLEMENTERING OG KOMPATIBILITET

Inden ændringer gennemføres:

1. Undersøg den eksisterende kode, datamodel, API-kontrakter og faktiske v2-schema.
2. Genbrug eksisterende felter og relationer, hvor det er muligt.
3. Tilføj kun nye felter eller tabeller, hvor funktionaliteten kræver det.
4. Brug additive databaseændringer og nødvendige migrationer.
5. Bevar gamle rapporter, kandidater, kilder, ordrer og journalposter.
6. Hold eventuelle nye HOT WATCH-observationer adskilt fra historiske rapportpayloads.
7. Implementér ikke opdigtede backendfelter eller endpoints.
8. Hvis rapportskemaet skal udvides, skal eksisterende schema_version 2 fortsat kunne læses og modtages uændret.

Foretræk separate, versionskompatible lagringsstrukturer til nye observationsdata frem for at bryde eksisterende v2-kontrakten.

## 12. ACCEPTTEST FØR AFLEVERING

Codex skal teste og dokumentere:

- Eksisterende v1-rapporter kan fortsat læses.
- Eksisterende v2-rapporter kan fortsat modtages og læses.
- Tidligere v2-test med `escape-v2-production-check-001` forbliver uændret.
- Testdata vises kun i Testdata.
- Samme report_id skaber ikke dubletter.
- Forskelligt indhold med samme report_id overskriver ikke historik.
- Candidate_id bevares mellem rapporter.
- AFVENT forbliver aktiv og FRAVÆLG bliver hvilende.
- Genaktivering journalføres korrekt.
- HOT WATCH-målinger kan gemmes og sammenlignes.
- MERC kan vises med flere observationer og separat ordrestatus.
- Accepteret ordre med nul fyldning vises ikke som solgt.
- Delvis fyldning vises korrekt.
- Root og AI Trader dobbeltoptælles ikke.
- Samme ticker kan vurderes forskelligt i to depoter.
- Manglende markedsdata vises som ukendt.
- Alle kildehenvisninger og analyse-URL'er valideres.
- Alle fire rapportregioner vises med korrekt dækningsstatus.
- Leveringsstatus afspejler faktisk validering, lagring og tilbageslæsning.
- Ingen test skaber eller ændrer rigtige Pluto-handler.
- Eksisterende automatiske rapportkørsler ændres ikke.

## 13. AFLEVERING

Codex skal afslutte med en kort teknisk status, der dokumenterer:

1. Hvad der er implementeret.
2. Hvilke eksisterende funktioner der er genbrugt.
3. Hvilke databaseændringer der er foretaget.
4. Hvilke API-kontrakter der eventuelt er udvidet.
5. Resultatet af accepttestene.
6. Eventuelle resterende fejl eller begrænsninger.

Ingen funktion må betegnes færdig, hvis den kun er visuelt implementeret uden fungerende datagrundlag.

**PRIORITERING VED TIDSPRES**

P0: Dataintegritet, v1/v2-kompatibilitet, depotkonsolidering, ordrestatus og rapportlevering.

P1: Beslutningsstatus, kandidathistorik, individuelle positionsvurderinger og HOT WATCH-datalagring.

P2: HOT WATCH-tidslinje, forbedret brugerflade og udvidet statistik.

**SLUTKRAV**

ESCAPE Invest skal kunne dokumentere:

Hvad opdagede Trading Radar?

Hvornår blev det opdaget?

Hvilke data og kilder understøttede signalet?

Hvilken beslutning blev truffet?

Hvordan ændrede vurderingen sig?

Blev der oprettet en ordre?

Blev ordren faktisk udført?

Hvad blev det dokumenterede økonomiske resultat?

Alt dette skal kunne følges uden at miste historik eller forveksle anbefalinger med handler.

**Implementér dette som sidste udvidelse af den eksisterende ESCAPE Invest v2-løsning. Bevar det fungerende system, gennemfør relevante tests og aflever en verificerbar status.**