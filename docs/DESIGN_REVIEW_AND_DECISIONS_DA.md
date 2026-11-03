# ESCAPE Invest — designgennemgang og afklaringsspecifikation

Dato: 3. november 2026. Status: arbejdsgrundlag til ejer og ChatGPT/Trading Radar. **Ingen installation eller ny designrelease endnu.** Den ventende MCP 2.5.1-læserettelse skal med i den samlede kommende leverance.

## Hvad er undersøgt?

Koden til alle frontendmoduler, filtrering og rapport-/positionsprojektioner er gennemgået. Alle otte hovedvisninger — Overblik, Porteføljer, Radar, HOT WATCH, Handelsmotor, Handelsjournal, Analyser og Forbindelser — er åbnet i lokal browser ved 320–1920 px. Derudover er porteføljedetaljer med beholdninger/kontanter/ordrer og individuelle positionsdetaljer kontrolleret. Der er taget billeder ved 390 og 1440 px og visuelt gennemgået centrale skærme.

Kontrollen anvender syntetiske rapporter og simulerede Pluto-svar. Der er ingen produktionscookies, EODHD-nøgler eller Pluto-login til rådighed her. Derfor er en tom eller gammel værdi i testmiljøet ikke bevis for, at samme felt mangler hos ejeren. En faktisk datakomplethedskontrol skal skelnes fra gennemgangen af, hvordan appen håndterer manglende data.

## Bekræftede fejl og rettelser i arbejdsudgaven

1. **Farver blev overskrevet:** `.market-number-link { color:inherit }` overstyrede `.market-positive`/`.market-negative` på klikbare dagsændringer. En browsertest genskabte fejlen: positiv BTC-dagsændring fik den almindelige lyse tekstfarve i stedet for grøn. Retningen er nu bevaret på positiv, negativ og neutral ændring, også ved hover. Pile kommer fra ændringens fortegn.
2. **To filtre kunne modarbejde hinanden:** Radarens opmærksomhedsfilter kunne ophæve den eksisterende skjulning af lukkede/arkiverede kandidater. Filtrene kombineres nu: livscyklus OG opmærksomhed. Der indføres ingen nye livscyklusregler. Optællingerne i opmærksomhedsfilteret følger valgt livscyklusgruppe.
3. **Modstridende driftsbesked:** Forbindelsessiden havde en fast tekst om, at Pluto OAuth ikke var konfigureret, selv når forbindelsen ovenover var godkendt. Teksten er rettet til at henvise til den faktiske status og skelne opdateringsbackup fra planlagt driftsbackup.

Rettelserne er arbejdsændringer; de er ikke installeret hos ejeren. Den store designomlægning og nye skjulnings-/udløbsregler er ikke implementeret uden afklaring.

## Observationer pr. visning

| Visning | Konkrete fund | Forslag, der kræver fælles prioritering |
|---|---|---|
| Overblik | Kontotal gentages som Pluto-overblik og rapportkontroloverblik. Alle positionsvurderinger ligger før næste analysehandlinger. Mange ens paneler uden tydeligt hierarki. Et testeksempel med 12 positioner gav ca. 8.169 px samlet mobilside. | Ét primært kontoområde, kort handlingsliste og kompakt positionsoversigt. Rapporttal og lange analyser åbnes i detaljer. Afklar, hvad første skærmbillede skal prioritere. |
| Porteføljer | Portefølje, Collection, kontanter og rapporttal gentager indhold. Collection-specifikationer åbner som standard og kan blive lange. Beholdningstabellen bliver til høje kort ved smalle containere. | Klar indrykning af Collections, tættere positionstabeller/rækker, detaljer ved klik. Afklar, om Collection-indhold skal åbne automatisk. Undgå dobbeltoptælling. |
| Positionsvurderinger | Hver position gentager navn, badge, rapportværdi, tidsstempel, P/L, analyseuddrag, risiko og separat kurskort. Også 8–10 px sekundær tekst. | Samlet kompakt positionsrække med tydeligt adskilte dagsændring og urealiseret resultat; fuld analyse/kilder/graf i detaljevisning. Afklar standardkolonner og sortering. |
| Radar | Store analyse- og statusblokke for hver kandidat. Livscyklus, købsvurdering og udførelse fylder meget, men må ikke blandes sammen. Gamle kandidater kan være aktive uden en godkendt aldersregel. | Kort liste som standard, eksplicit valgt statusfilter og samlet historik i detaljevisning. Bevar egne nyhedsidéer og rapportkandidater som forskellige kilder. |
| HOT WATCH | Motor og rapportobservationer deler side, men har forskellige datagrundlag og aktivitet. Motoren lister også terminale sessioner; gamle observationsgrupper mærkes hvilende, men vises stadig. | Tydelig opdeling mellem motor og indsendte målinger. Aktiv/afventende/fejl/historik efter godkendt matrix. Service- og datakildestatus skal kunne forstås uden teknisk jargon. |
| Handelsmotor | Rapporterede ordreobservationer ligger før selve handlingsflowet. Mange ukendte felter og et åbent testestimat fylder skærmen. Gamle og afsluttede rapportordrer vises uden særskilt aktivliste. | Aktuelle forslag og verificerede åbne ordrer først; uklare ordrer separat; testestimat og historiske poster i tydelige sekundære områder. Afklar præcis standardstatusliste. Ingen ændring af godkendelsesflow. |
| Handelsjournal | Flere journaltyper vises i store gentagne blokke. Få samlede filtre og uklar forskel på rapporteret hændelse, eget forslag og brokerudførelse. | Kompakt tidslinje med kilde/type og status; filtrering uden sletning. Afklar relevante standardtyper og tidsinterval. |
| Analyser/arkiv | En hel rapport bliver meget lang med alle hovedafsnit og gentagne kilder, positioner og ordrer. Historiske kilder er korrekte i arkivet, men kan forveksles med aktuelt overblik. | Kort indholdsfortegnelse/resumé, tydelig rapportdato/kategori og detaljer pr. afsnit. Original historisk rapport skal stadig kunne vises komplet. |
| Forbindelser | Ens paneler giver forbindelsesstatus, driftsteknik og diagnoseværktøjer næsten samme vægt. Fast OAuth-tekst var modstridende. | Kompakt statusoversigt; tekniske diagnoser og historiske registreringsfejl i detaljer. Vis faktisk tilstand frem for statiske generelle påstande. |

## Beslutninger, ChatGPT/ejer skal præcisere

Svar med B1–B12. Forslagene er til godkendelse eller korrektion, ikke allerede vedtagne regler.

### B1 — Første skærmbillede og navigation

Hvilke 3–5 oplysninger skal altid være øverst på Overblik? Prioritér eksempelvis kontoværdi, dagens resultat, samlede urealiserede resultater, kritiske handlinger, åbne ordrer og HOT WATCH. Skal alle beholdninger ligge på Overblik, eller skal Overblik kun vise relevante handlinger samt et link til hele beholdningslisten? Skal navigationens otte områder bevares, grupperes eller omdøbes?

### B2 — Standardrække for en beholdning

Angiv præcis hvilke felter der skal ses uden klik på desktop og mobil. Muligheder: ticker/navn, depot/Collection, antal, seneste kurs, dagsændring %, dagsændring i beløb, markedsværdi, urealiseret resultat beløb/%, analysehandling, næste trigger og datatid. Hvilke skal flyttes ind i detaljer? Skal standardrækkefølge være depot → handlingsbehov, depot → værdi, alfabetisk eller noget andet? Samme aktie i to depoter skal fortsat være to positioner.

### B3 — Rød/grøn, referencegrundlag og pile

Bekræft eller ret følgende betydning pr. felt:

| Felt | Forslag til sammenligningsgrundlag |
|---|---|
| Dagsændring | Grøn ↑ ved positiv og rød ↓ ved negativ leverandøroplyst dagsændring; neutral → ved nul |
| Seneste kurs | Skal selve kursen følge dagsretningen, eller kun ændringsfeltet? |
| Markedsværdi af position | Skal selve værdien farves efter urealiseret resultat, eller være neutral med separat farvet P/L? |
| Urealiseret resultat | Grøn ↗/rød ↘ i forhold til anskaffelsesværdi i sammenlignelig valuta; neutral ved nul |
| Kontoværdi | Skal farven følge dagens resultat, Plutos samlede profitLoss eller kun vises på det særskilte resultatfelt? |
| Antal, kostpris, kontanter | Normalt neutral; ønskes andet, skal referencegrundlaget angives |

Handlingernes rød/gul/grøn må ikke udlægges som kursretning. En position kan være i plus og samtidig have SÆLG-vurdering. Manglende/uforenelige sammenligningsdata skal være neutrale, aldrig gættede grønne/røde. Forklar særskilt om pile skal betyde dagens kursretning eller bevægelsen mellem to hentninger.

### B4 — Kandidater: standardvisning pr. lifecycle

Udfyld for hver status, hvor den skal være synlig som standard: Overblik, Radar, HOT WATCH og Handelsmotor. Angiv også, om den skal være tilgængelig alene via filter/historik.

DISCOVERED, ANALYZING, HOT_WATCH, WAITING_TRIGGER, BUY_SIGNAL, ORDER_PENDING, POSITION_OPEN, EXIT_WATCH, CLOSED, ARCHIVED.

Vigtigt grænsetilfælde: En kandidat med beslutning REJECT/FRAVÆLG kan stadig have en ejet position. Skal den ses i aktive kandidater, kun under åben position eller begge? Historikken og beholdningen må ikke slettes eller skjules som en automatisk følge af REJECT.

### B5 — Alder, deadlines og gamle rapporter

Angiv konkrete tidsregler for kursdata, positionsanalyse, kandidatanalyse, købsforslag, nyheder og rapportresumé. Skal en gammel post skjules fra aktivlisten eller blive stående som forældet? Hvad er reglen uden deadline? Skelnes mellem åbent/lukket marked, weekender og forsinkede feeds? Forældede markedsdata må ikke præsenteres som aktuelle. En datakildefejl må ikke få en faktisk position eller kritisk advarsel til at forsvinde.

### B6 — Åbne, delvise og afsluttede ordrer

Angiv standardplacering for PROPOSED, AWAITING_APPROVAL, SUBMITTED/ACCEPTED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED og UNKNOWN. Skal fuldt fyldte/annullerede/afviste ordrer straks flytte til historik, eller vises i en periode? Hvor vises en delvist fyldt og derefter annulleret ordre? ACCEPTED alene er ikke et sikkert fyldnings- eller åbenhedsbevis. En overskredet rapportdeadline må ikke annullere en faktisk Pluto-ordre.

### B7 — HOT WATCH-sessioner og rapportmålinger

Angiv standardplacering for CREATED, VALIDATING, ACTIVE, PAUSED, DEGRADED, ERROR, EXPIRED og COMPLETED. Skal PAUSED ligge i en særskilt gruppe? Skal ERROR/DEGRADED altid være synlige som driftsadvarsel? Hvor vises målinger fra en session, der er afsluttet? Skal ældre rapportmålinger være sammenfoldet som standard? Motorens signaler og rapportafsenderens anbefalinger skal fortsat kunne skelnes.

### B8 — Beholdningers autoritative kilde og afstemning

Pluto er autoritativ for faktisk ejerskab og udførelse. Hvordan skal rapportens positionsvurdering knyttes til den aktuelle Pluto-position, hvis ticker, antal, depot eller dato afviger? Skal hovedlisten tage udgangspunkt i alle faktiske Pluto-positioner, med en markering når individuel analyse mangler? Hvad vises ved Pluto-udfald? Kandidatens fravær i en senere rapport eller manglende analyse er ikke i sig selv bevis for salg.

### B9 — Datakomplethed og manglende felter

Angiv hvilke felter afsenderen skal levere pr. position, kandidat og ordre, og hvilke kilder de kommer fra. Skeln mellem:

- Faktisk værdi hos Pluto, verificeret markedsobservation og AI-analyse.
- Null fordi kilden ikke leverer feltet, endnu ikke hentet, for gammelt, fejlbehæftet og ikke relevant.
- Manglende data, der skal advare i oversigten, og valgfrie felter, der blot kan ligge i detaljer.

Særligt: positionens stabile ID, depot/Collection, Pluto asset_id, antal, valuta, kurs og kurstid, kostpris, urealiseret resultat samt individuel handling/begrundelse/næste trigger. For kandidater: beslutning, lifecycle, katalysator, deadline, næste trigger og datakilder. For ordrer: stabilt ordre-ID, side/type, ønsket/fyldt antal og status med kildetid. Hvilke af disse kan ChatGPT faktisk levere, og hvilke skal appen hente fra en leverandør?

Alt må ikke udfyldes med generiske tekster eller null-erstatninger for at få en pæn skærm. Manglende data skal have en ærlig visning og en konkret vej til afhjælpning. Eventuelle nye maskinlæsbare felt-/årsagskoder kræver bagudkompatibel schemaændring.

### B10 — Tal, valuta og læsbarhed

Bekræft ønskede decimaler for beløb, aktiekurser, små kryptokurser, antal og procenter. Kan en ensartet standard være beløb 2 decimaler, procenter 2, kurser/antal efter nødvendig præcision, mens helt små tal aldrig afrundes til falsk nul? Skal hovedvisningen være original valuta eller DKK med dokumenteret FX? Må beløb forkortes i oversigten, hvis fuld værdi altid kan åbnes? Ukendte beløb må aldrig vises som nul.

### B11 — Layout og detaljer

Skal desktop bruge kompakte tabelrækker, og mobil en kompakt liste med få hovedfelter? Hvilke afsnit må være sammenfoldet fra start? Hvilke gamle paneler eller dubletter skal fjernes fra standardvisningen? Foretrækkes den nuværende mørke stil med tydeligere kontrast/sektioner, eller ønskes en anden visuel retning? Angiv gerne prioritet mellem tæthed og store trykflader. Kritiske oplysninger skal være læsbare, og kontroller skal kunne betjenes med touch/tastatur.

### B12 — Journal, arkiv og kildekonflikter

Hvilke journaltyper og hvilket tidsinterval vises som standard? Skal fulde historiske rapporter fortsat vise alle oprindelige poster, også lukkede/arkiverede? Forslag: ja; aktivfiltrering gælder aktuelle oversigter, ikke en omskrivning af gamle rapporter. Hvordan præsenteres konflikt mellem rapportpåstand og verificeret Pluto-status? Skal der være én samlet tidslinje med kildemærke, eller separate faner?

## Ønsket svarformat til Codex

1. Besvar B1–B12 med entydige regler. Markér punkter, hvor ejeren skal vælge.
2. Lever en matrix med objekt/status, standardvisning, alternativ placering, sortering, udløbsregel og undtagelser.
3. Lever feltlisten for desktop/mobil pr. hovedvisning og farve-/pilgrundlaget for hvert tal.
4. Lever liste over manglende inputdata med ansvar: ChatGPT/rapport, Pluto, EODHD eller appberegning. Brug ikke værdier, som kilden ikke kan verificere.
5. Foreslå konkrete acceptscenarier: positiv/negativ dag, gevinst med SÆLG-vurdering, ukendt kurs, gammel analyse med åben position, fravalgt kandidat med beholdning, delvist fyldt annulleret ordre, lukket/arkiveret kandidat og session i ERROR.

Der er ikke bestilt ændring af handelsflow, automatisk handel, datakøb, eksisterende scheduler eller historiske rapportpayloads. Der er heller ikke bestilt automatisk sletning eller arkivering. Den færdige løsning skal testes med repræsentative syntetiske scenarier, visuelt på mobil/desktop og efterfølgende med ejerens faktisk tilgængelige datakilder.

## Verifikation af de afgrænsede arbejdsrettelser

- Før-testen fejlede på faktisk beregnet farve for positiv dagsændring (almindelig tekstfarve i stedet for grøn), så problemet var genskabt og ikke kun udledt af klassenavne.
- Udvidet `tests/browser_positions.py` er bestået med positiv, negativ og neutral dagsændring, korrekte pile/farver før og under hover samt eksisterende positions-/Collection-forløb ved 320–1920 px.
- Udvidet `tests/browser_hotwatch_engine.py` er bestået: skift mellem aktive, lukkede, arkiverede og opmærksomhed får ikke skjulte forløb frem i en forkert gruppe.
- `tests/browser_latest_desk.py` er bestået for eksisterende radar-, arkiv- og analyseflow.
- Browsergennemgang af otte hovedvisninger og finansielle detaljer er bestået før/efter de afgrænsede rettelser ved 320, 375, 390, 430, 768, 1024, 1280, 1440 og 1920 px. Der er ingen sideværts side-overløb i disse fixtures; dette siger ikke, at informationsmængden er godkendt.
- De tre eksisterende JavaScript-suiter for beløb, friskhed og opmærksomhed er bestået. Der er ikke ændret backend-/schemastruktur i denne designarbejdsudgave.

[Udsnit af nuværende positionsvisning med rettet dagsændringsfarve](screenshots/design-review/positions-direction-colors-390.png). Dette er et syntetisk testbillede af eksisterende layout, ikke et færdigt redesign. Store blokke og gentagelser afventer svarene ovenfor.
