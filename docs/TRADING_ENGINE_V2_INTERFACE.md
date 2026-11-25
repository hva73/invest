# Trading Engine v2 · #273

`trading_engine_v2.evaluate` sammenligner versionslåste HOT WATCH-strategier på
samme grundlag i en lokal simulation. Kaldet bruger et allerede opløst
strategispec og dets gemte checksum fra kataloget. Strategierne beholder deres
eksisterende ID og semver. Evalueringen bruger de deklarative regler i
`hotwatch_strategy`, inklusive Early Catalyst 1.0.0's særskilte watch-regler.
Momentum 1.0.0 kræver MACD ved entry. Early Catalyst 1.0.0 har den
bekræftelse slået fra som standard.

Kaldet modtager et eksisterende HOT WATCH-sample med positionskontekst,
beregnede metrics og gældende risikoinput. Hver evidensværdi har kilde-ID'er,
hændelsestid og tilgængelighedstid. Replay ser kun input med
`event_time ≤ available_at ≤ as_of`. `available_at` skal afspejle, hvornår
hele værdien var kendt, også for afledte metrics og samplets positionskontekst.
Værdierne bruger HOT WATCH-kontraktens JSON-format, inklusive decimalstrenge.

`observation` betyder, at de synlige data afkræfter mindst én nødvendig
regelbetingelse. `blocked` betyder, at evalueringen mangler afgørende
evidens, at strategien eller konteksten ikke kan bruges, eller at risiko
blokerer handlingen. Alternativer inden for en regel kan afgøres af en
tilgængelig gren. Først ved en regelbaseret handling kaldes den fælles
HOT WATCH-risikogate én gang. Entry og exit kræver henholdsvis eksplicit
`entry_allowed` og `exit_allowed` i det fangede risikoinput.

En `decision` returnerer et simuleret BUY, SELL eller REDUCE. Det er en
vurdering af ét snapshot uden liveautoritet. Live-signalstabilisering,
løbende stop- og deadlineovervågning, kvalifikation og brokerflow tilhører
den eksisterende motor.

Scope følger HOT WATCH- og rapportidentiteterne med ejer, testkategori,
børs, asset, depot, kandidat, watch, handelsforløb og eventuel position.
Kaldet skal levere data fra samme scope. Exit kræver et position-ID og en
verificeret beholdningskontekst. Beslutningsoprindelsen bruger det fælles
canonical checksum-format og binder scope, snapshot-ID, replaytid, entry/exit
og den konkrete strategiversion med dens checksum. Den binder også det
fangede sample, metrics og risikoinput med værdier, kilde-ID'er og tider.
Checksummen udelader evidens, der endnu ikke var tilgængelig eller mangler
kilde-ID'er, samt samples med indlejrede tider efter deres tilgængelighedstid.
Ændret synlig evidens giver en ny digest, selv med samme snapshot-ID. Det
gælder også valgfri evidens, når udfaldet er det samme.

`VerifiedExecution` er et særskilt link fra autoritativt ordre- eller
fill-readback. Kaldet, der leverer linket, har ansvaret for kildens verifikation.
`links` matcher beslutningens digest og scope. Ordre-ID udfylder aldrig fill-ID.
Entry og exit kan dermed spores til hver sin versionslåste oprindelse.
Evalueringen producerer alene beslutningsoprindelsen og gemmer ingen data.

## Replay i Strategy Lab

`strategy_lab.compare_v2(connect, uid, data)` bruger samme valg af watch,
testkategori og op til tre strategiversioner som `compare`. Første op til
240 beregninger læses i journalrækkefølge. Én SQL-forespørgsel henter op til
241 journalpar inklusive rækken, der markerer afkortning. Replay afviser
tidsmæssige tilbagespring. Det gemte signal og dets årsagskoder vises sammen
med de simulerede udfald. Beregningens ID, version og checksum skal matche et
eksakt spec i ejerens eller det fælles katalog. Manglende match blokerer
simuleringen med `ORIGINAL_STRATEGY_UNVERIFIED`.

Strategier med ens featureparametre deler de gemte metrics. Ændrede perioder
for glidende gennemsnit, RSI, ATR, breakout/volumen eller momentum kræver
genberegning af de berørte metrics med `features()`. Replay bruger den
komplette, ordnede liste af op til 120 `input_sample_ids` fra beregningen,
opløst inden for samme watch, ejer og testkategori i den allerede læste
journal. De enkelte samples skal have intakt checksum, matchende
markedsidentitet, verificeret kvalitet og dokumenteret tilgængelighed ved
beregningen. Beregningens featureversion og det effektive antal samples skal
stemme. De genberegnede værdier bindes til journalens sample- og
beregnings-ID'er i snapshot-checksummen. En alternativ nyhedsaldersgrænse
kan ikke genbruge den oprindelige nyhedsattestering.

Manglende historik, utilstrækkelig opvarmning for ændrede regel- eller
risikoinput og uverificerbare revisioner vises som blokering for den enkelte
strategi. Parameterkompatible udfald bevares. Historik uden for den læste
journal kan ikke udfylde huller. Replay kan genbruge fangede bar-metrics ved
ens parametre og en verificerbar aktuel observation. Det kan kun
genberegne fra bars med en dokumenteret historisk revision. Den nuværende
journal gemmer ingen sådan reference for indlejrede EODHD trade-bars eller
separat cachet warmup. Disse genberegninger blokeres med
`FEATURE_BAR_REVISION_UNVERIFIED`, når selve observationen kan bruges.

Regressionstesten læser 12 gemte beregninger med én journalforespørgsel.
Med replaygrænsen sat til tre bruges henholdsvis ét, to og tre sampleinput
pr. ændret strategi, hvorefter svaret markerer afkortning.

`hw_samples.received` afgrænser markedsevidensens tilgængelighed. Det
beregnede snapshot inklusive metrics, risiko og positionskontekst kan
først dokumenteres ved `hw_calculations.calculated`. Evidensens kilde-ID'er
peger på de faktiske journalrækker. Depot, aktiv, watch og eventuelt
handelsforløb afstemmes mod beregningens fangede scope-checksum. EODHD
trade-samples kan opdateres på samme række uden at ændre modtagelsestiden.
Disse samples springes over, da beregningen mangler en historisk
revisionsreference. Beholdningsberegninger springes over, da den gemte
positionskontekst mangler et position-ID til v2.

Svaret viser dækning, årsager til udeladelser, første udeladelse, udfald og
første blokering for hver strategi samt historisk latenstid fra
markedshændelse til modtagelse og fra modtagelse til beregning. Der beregnes
ingen P/L eller eksekveringsstatistik. Sammenligningen bruger den gældende
v2-risikogate med de fangede risikoinput. Kaldet læser kun SQLite og har
ingen live-rute.
