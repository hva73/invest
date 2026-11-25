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
240 beregninger læses i journalrækkefølge. Replays afviser tidsmæssige
tilbagespring. Hver sammenligning viser det gemte signal og årsagskoder
sammen med de simulerede udfald på samme snapshot. Katalogversionerne
verificeres med checksum. Historiske indikatorer genberegnes ikke med
de valgte strategiers parametre.

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
