# Overblik med adgang til datagrundlaget

Forsiden viser nu først kompakte kontokort fra Pluto og derefter analyseoverblikket. Det tidligere ekstra kontoresumé, hele portefølje-/Collection-træet og det generiske Næste handling-afsnit er fjernet fra forsiden. Porteføljer samler de aktuelle porteføljer og deres Collections; arkiverede og lokale enheder kan foldes ud særskilt.

Kontoværdi, oplyst resultat og kontantbalance er klikbare. Kontanttal åbner ved kontantafsnittet, mens værdi/resultat åbner ved deres kildegrundlag. Beholdninger og ordrestatus har egne direkte links. Kildealder opdateres fortsat og kan foldes ud. Plutos profitLoss mærkes som oplyst resultat med ukendt afkastperiode, når perioden ikke leveres; det kaldes ikke dagsafkast. Grøn/rød resultatpil baseres kun på det oplyste resultat. En kontoværdi eller saldo får ingen opdigtet vækstpil, når et ændringsgrundlag mangler; dens højrepil betyder navigation.

Rapportens porteføljetal er samlet i Porteføljetal fra analysen. Dette afsnit er som udgangspunkt foldet sammen, når der findes anvendelige Pluto-kontotal; ellers står det åbent. Kategorierne og datagrundlagene sammenblandes ikke. Brugerens eget valg af fold-ud-afsnit bevares ved genrendering.

Overblikkets rapportdel har nu følgende klikmål:

- Porteføljeværdi åbner rapporteret værdi, kontanter, øremærkning, datatid, kilder og relevante positioner. Tilknyttede Collections indgår kun i positionsudsnittet, når rapporten eksplicit siger includes_collections=true. Der beregnes ingen sum af positionerne.
- Kontanter og øremærket åbner samme porteføljes oplysninger med relevant overskrift og eget sammenligningsgrundlag, når dette findes. Beløbene beskrives ikke som fri købekraft.
- Positioner, ordreposter og kandidater åbner hele hver sin liste. Ordrelisten viser også tidligere/færdige ordreobservationer og hævdes ikke at være en liste over åbne ordrer.
- De tre statusantal åbner den tilsvarende kandidatgruppe. Et nul åbner en forklaret tom tilstand; man kan skifte til de andre grupper i dialogen.
- Ticker og Se vurdering åbner kandidatens konkrete vurdering, katalysatorer, risici og næste handling med adgang til den oprindelige analyse. Grav dybere bruger den eksisterende analysepakke med korrekt rapport- og kandidat-ID.

Dialogerne viser rapportens data, ingen nye brokerpositioner eller kontotal. De kan lukkes med knap eller Escape og returnerer tastaturfokus til udgangspunktet. Automatisk fuld genrendering er fortsat pauset, mens en dialog er åben.

## Farver og pile

Kurs- og dagsændringstallet åbner nu en grafdialog med samme cache og et rullende døgn som udgangspunkt. Uge er et tilvalg. Escape/luk returnerer tastaturfokus til det valgte tal, selv om kurselementet genrenderes. Grafen åbnes uden et ekstra opslag, når data stadig er inden for cacheperioden.

Kandidaters kompakte kursfelt viser `currentPrice`, `dailyChange` og `dailyChangePercent` fra det eksisterende, læsebeskyttede Pluto-opslag. Dagstal har grøn ↑, rød ↓ eller neutral visning ved nul/ukendt. Kursens faktiske tid og hentetid holdes adskilt. Det kompakte felt deler cache og opdateringsbudget med graferne i Radar/rapportvisningen. Usynlige felter hentes først ved visning; der tilføjes ingen baggrundshandler eller planlagte job. Ukendte eller mislykkede opslag får ingen opdigtede dagstal.

Rapporterede portefølje-/kontantbeløb får en separat **værdiændring siden en tidligere rapport**. Backend anvender Decimal med høj præcision og returnerer tidligere beløb, forskel, valuta, begge datatider og den oprindelige rapportreference. Sammenligningen kræver samme stabile portefølje-ID, valuta, kind, parent og includes_collections samt kendt strengt stigende observationstid. Den seneste tidligere hovedrapport vælges efter genereringstid; uddybninger, testdata og sent modtaget ældre historik erstatter ikke grundlaget. Flere pengeposter med samme valuta summeres ikke for at opfinde et sammenligneligt kontantbeløb.

Værdiændringer kan skyldes indbetalinger, udbetalinger og handler. De mærkes derfor ikke som afkast eller dagsudvikling. Kilden er fortsat afsenderens rapport og ikke en genverifikation hos Pluto. Manglende beløb/tider, ændret valuta eller ændret overlapgrundlag giver neutral visning. Optællinger har pile som navigation, ikke grøn/rød markedsretning. Handlingsstatus beholder sin egen rød/gul/grøn-betydning.

## Verifikation

`tests/test_overview.py` dækker præcise decimaldifferencer, null, valutaskift, uændret datatid, Collection-overlap, dublerede pengebeløb og udvælgelse af tidligere hovedrapport. Detaljeprojektionen ændrer ingen databaseposter.

`tests/browser_overview.py` bruger syntetiske data: 11 positioner, 15 ordrer, 12 kandidater, simulerede positive/negative Pluto-opslag, klik på alle nøgletal, tom/udfyldt statusgruppe, kandidatens analysepakke, sammenligningsrapport, Escape/fokus og layout fra 320 til 1920 pixels. Ingen eksterne servicekald eller forslag sendes. Eksisterende Latest Desk- og markedsgrafbrowserflows kontrollerer samspillet med de øvrige visninger.

## Oprydning på de øvrige sider

- Porteføljer viser aktuelle Pluto-værdier og Collections som en sammenhængende liste. Tal åbner de konkrete detaljer. Rapporttal, arkiverede enheder og lokal administration er tilgængelige i tydelige fold-ud-afsnit.
- Radar og fulde analyser har klikbare rød/gul/grøn-statusantal, der filtrerer den viste kandidatgruppe; Vis alle nulstiller filtret. Der ændres ikke i rapportens indhold eller sorteringsgrundlag.
- Radarens manuelle idéformular åbnes efter valg af Tilføj en markedsidé.
- Analyser erstatter det uklare menunavn Rapporter & alarmer. Den dobbelte analyseindbakke er fjernet; datakørsler, kilder og jobhistorik er samlet under et fold-ud-afsnit. De eksisterende jobkontroller og kørsler er uændrede.
- Handelsjournalen viser ikke længere fire tomme resultatfelter uden beregningsgrundlag. Rapporterede hændelser, brokerforslag og lokale beslutninger bevarer deres eksisterende adskillelse.

De syv hovedsider er gennemgået i Chromium ved 320–1920 px med syntetiske data. Browserkontroller dækker direkte kontonavigation, positive/negative resultatpile, kildealdre, lokale formularer, analysearkiv, filtre, grafdialog, tastaturfokus, åbne afsnit efter refresh og betroede mobile touch-gestures for træk-opdatering. Der er ikke foretaget en ny fysisk iPhone/Safari-test i udviklingsmiljøet. De eksisterende backend- og JavaScript-regressioner er bevaret. Ingen produktionsrapport, Pluto-handel, ordre eller timeautomatisering ændres af denne UI-opdatering.
