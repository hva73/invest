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

## Genbrug af markedsfeatures i én simulation

`market_features_batch` modtager én `MarketFeatureInput` pr. evaluering og
returnerer et selvstændigt metric-opslag pr. input i samme rækkefølge.
Kalderen leverer en ordnet, verificeret samplehistorik som `Evidence`
og angiver provider, feed, timeframe, revision, entitlement og featureversion
for det konkrete datasæt. Entitlement-etiketten skal identificere den samme
datatilgang, som er verificeret for hver enkelt modtager.

Kun instrument og testkategori fra `Scope` indgår i opslaget sammen med
markedsfelter, kilde-ID'er, tider, replaytid og de effektive perioder i
`features()`. En ændring i nogen af disse værdier giver et nyt opslag.
Input skal være tilgængeligt ved evalueringstidspunktet. For bars skal
hele intervallet være lukket ved den angivne tilgængelighedstid.
Utilgængelig featurehistorik giver et tomt opslag. `evaluate` afgør som
hidtil, hvilke metrics den enkelte regel kræver.

Kalderen kombinerer de afledte facts med sin egen evidens og kalder
`evaluate` for hver bruger og hvert depot med den aktuelle strategi,
positionskontekst og risiko. Hver beslutning får sin egen oprindelse.
Batchen gemmer højst 128 sæt features i hukommelsen. Når den er fuld,
beregnes nye sæt ved behov, og alle opslag udløber ved retur.
Grænsefladen bruges til lokal simulation. Schedulerintegration er separat.

For en delt testhistorik kan kalderen bruge
`shared_market_features_batch(history, subscribers)` med én `MarketHistory`
pr. instrument og replaytid. Historikken indeholder en `MarketIdentity` og
de ordnede observationer. Batchen validerer og kopierer markedsfelterne én gang
til en uforanderlig visning. Der beregnes ingen historikchecksum i denne sti.
Batchen grupperer modtagerne efter de effektive featureperioder og kalder
`features()` én gang pr. gruppe. Grupperne lever kun under kaldet.

Hver `MarketSubscriber` leverer sit eget `Scope` og tidsstemplet `Evidence`
for en `MarketAccess` fra kalderens verificerede, lokale entitlement-kilde.
Bevillingen skal være tilgængelig og uudløbet ved replaytidspunktet og matche
bruger og hele markedsidentiteten. Scope skal matche instrument, børs og
testkategori. Kilde-ID'er bevarer sporbarheden. Kalderens lokale resolver
står for at attestere bevillingen og leverandørevidensen.

Den delte sti kræver verificerede prisobservationer fra EODHD eller Pluto
med matchende kilde, feed, børs, valuta og instrument. Bars skal matche
historikkens timeframe og være lukket ved tilgængelighedstiden. Den nyeste
prisobservation (for bars gælder lukketid) skal være inden for den globale
datatidsgrænse. Manglende eller for gamle bid/ask-tider gør spread ukendt,
men afviser ikke en ellers gyldig prishistorik. Historisk markedsstatus
grupperer observationer; den dokumenterer ikke aktuel handelsadgang.
Fremtidig evidens afvises fortsat. Individuel risikogate gælder uændret.
Ugyldig historik giver tomme opslag for hele kaldet. En ugyldig bevilling
eller et ugyldigt scope giver kun den pågældende modtager et tomt opslag.
Individuelle beslutninger bruger fortsat `evaluate` med egen risiko og
positionskontekst og beholder deres eksisterende oprindelsesformat.

## Strategiskift i Position Watch

`switch_position_strategy` returnerer en uforanderlig overgang for en
eksisterende, verificeret beholdning i testkategorien. Kaldet bruger
positionens fulde `Scope`, den oprindelige `DecisionOrigin` for entry og et
positions-readback som `Evidence`. Kalderen attesterer readbackets kilde og
leverer `scope_digest`, `entry_digest` samt HOT WATCH-felterne `status`,
`position`, `quantity`, `cost_price` og `as_of`. Readbackets hændelsestid
skal matche `as_of`, være tilgængelig på skiftetidspunktet og højst være
300 sekunder gammel, som i HOT WATCHs positionsgate. Hele evidensen
fastholdes med kilder og tider, inklusive eventuelle P/L-input og native
stop-oplysninger, præcis som leveret.

Kaldet leverer et allerede læst katalog med nøglerne
`(owner_id, strategy_id, version)` og værdierne `(spec, checksum)`.
Ejerens post har forrang for den fælles post med `owner_id=0`. Motoren
validerer begge strategier og deres checksums. Overgangen binder scope,
entry-oprindelsen, forrige og ny strategi samt det effektive tidspunkt.
Ved efterfølgende skift leverer kaldet seneste overgang som `previous`.
Det nye readback skal være nyere end det foregående og fra eller efter
den forrige overgang. En identisk gentagelse returnerer samme overgang.
Hver ny overgang peger på digest for den foregående.

Ved exit-evaluering leverer kaldet seneste overgang som `position_switch`
og dens nye strategispec. Evalueringen kræver samme scope og en
positionskontekst med matchende `scope_digest`, `entry_digest` og `as_of`
fra eller efter skiftet. Exit-oprindelsen binder overgangens digest og bruger den gældende
risikogate. Strategiskiftet har ingen ordre- eller stophandling.
Grænsefladen er lokal simulation uden persistence, UI eller live-rute.

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

For hver beregning opløser replay historikken én gang og deler dens
uforanderlige markedsfelter mellem alternativerne. Samme effektive
featureperioder kræver ét kald til `features()`. Hver strategi får sine
egne facts og sin egen beslutningsoprindelse. To journalberegninger med
samme tidsstempel kan have forskellig historik og behandles hver for sig.
Bars skal være lukket ved modtagelsen, og den seneste observation skal
ligge inden for den globale datatidsgrænse for at kunne genberegnes.
Den delte abonnentsti `shared_market_features_batch` er utilgængelig i
Strategy Lab, da journalen kun dokumenterer den autoriserede brugers watch
og ikke indeholder historisk evidens for en leverandørbevilling.

Manglende historik, utilstrækkelig opvarmning og uverificerbare revisioner
fjerner de berørte facts. Eksisterende treværdilogik og risikogate afgør,
om de faktisk blokerer strategien; en sand alternativ regelgren bevares.
Ubrugte ændrede parametre kræver ingen historiklæsning. Historik uden for den læste
journal kan ikke udfylde huller. Replay kan genbruge fangede bar-metrics ved
ens parametre og en verificerbar aktuel observation. Det kan kun
genberegne fra bars med en dokumenteret historisk revision. Den nuværende
journal gemmer ingen sådan reference for indlejrede EODHD trade-bars eller
separat cachet warmup. Disse genberegninger blokeres med
`FEATURE_BAR_REVISION_UNVERIFIED`, når selve observationen kan bruges.

Regressionstesten læser 12 gemte beregninger med én journalforespørgsel.
Med replaygrænsen sat til tre bruges henholdsvis ét, to og tre sampleinput
pr. ændret strategi, hvorefter svaret markerer afkortning.
Med tre strategier fordelt på to periodesæt falder antallet af featurekald
for de 12 beregninger fra 36 ved separate replay til 24 ved ét samlet replay.

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
