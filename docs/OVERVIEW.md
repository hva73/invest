# Overblik med adgang til datagrundlaget

Overblikkets rapportdel har nu følgende klikmål:

- Porteføljeværdi åbner rapporteret værdi, kontanter, øremærkning, datatid, kilder og relevante positioner. Tilknyttede Collections indgår kun i positionsudsnittet, når rapporten eksplicit siger includes_collections=true. Der beregnes ingen sum af positionerne.
- Kontanter og øremærket åbner samme porteføljes oplysninger med relevant overskrift og eget sammenligningsgrundlag, når dette findes. Beløbene beskrives ikke som fri købekraft.
- Positioner, ordreposter og kandidater åbner hele hver sin liste. Ordrelisten viser også tidligere/færdige ordreobservationer og hævdes ikke at være en liste over åbne ordrer.
- De tre statusantal åbner den tilsvarende kandidatgruppe. Et nul åbner en forklaret tom tilstand; man kan skifte til de andre grupper i dialogen.
- Ticker og Se vurdering åbner kandidatens konkrete vurdering, katalysatorer, risici og næste handling med adgang til den oprindelige analyse. Grav dybere bruger den eksisterende analysepakke med korrekt rapport- og kandidat-ID.

Dialogerne viser rapportens data, ingen nye brokerpositioner eller kontotal. De kan lukkes med knap eller Escape og returnerer tastaturfokus til udgangspunktet. Automatisk fuld genrendering er fortsat pauset, mens en dialog er åben.

## Farver og pile

Kandidaters kompakte kursfelt viser `currentPrice`, `dailyChange` og `dailyChangePercent` fra det eksisterende, læsebeskyttede Pluto-opslag. Dagstal har grøn ↑, rød ↓ eller neutral visning ved nul/ukendt. Kursens faktiske tid og hentetid holdes adskilt. Det kompakte felt deler cache og opdateringsbudget med graferne i Radar/rapportvisningen. Usynlige felter hentes først ved visning; der tilføjes ingen baggrundshandler eller planlagte job. Ukendte eller mislykkede opslag får ingen opdigtede dagstal.

Rapporterede portefølje-/kontantbeløb får en separat **værdiændring siden en tidligere rapport**. Backend anvender Decimal med høj præcision og returnerer tidligere beløb, forskel, valuta, begge datatider og den oprindelige rapportreference. Sammenligningen kræver samme stabile portefølje-ID, valuta, kind, parent og includes_collections samt kendt strengt stigende observationstid. Den seneste tidligere hovedrapport vælges efter genereringstid; uddybninger, testdata og sent modtaget ældre historik erstatter ikke grundlaget. Flere pengeposter med samme valuta summeres ikke for at opfinde et sammenligneligt kontantbeløb.

Værdiændringer kan skyldes indbetalinger, udbetalinger og handler. De mærkes derfor ikke som afkast eller dagsudvikling. Kilden er fortsat afsenderens rapport og ikke en genverifikation hos Pluto. Manglende beløb/tider, ændret valuta eller ændret overlapgrundlag giver neutral visning. Optællinger har pile som navigation, ikke grøn/rød markedsretning. Handlingsstatus beholder sin egen rød/gul/grøn-betydning.

## Verifikation

`tests/test_overview.py` dækker præcise decimaldifferencer, null, valutaskift, uændret datatid, Collection-overlap, dublerede pengebeløb og udvælgelse af tidligere hovedrapport. Detaljeprojektionen ændrer ingen databaseposter.

`tests/browser_overview.py` bruger syntetiske data: 11 positioner, 15 ordrer, 12 kandidater, simulerede positive/negative Pluto-opslag, klik på alle nøgletal, tom/udfyldt statusgruppe, kandidatens analysepakke, sammenligningsrapport, Escape/fokus og layout fra 320 til 1920 pixels. Ingen eksterne servicekald eller forslag sendes. Eksisterende Latest Desk- og markedsgrafbrowserflows kontrollerer samspillet med de øvrige visninger.
