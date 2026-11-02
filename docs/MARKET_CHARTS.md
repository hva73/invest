# Kurser og kandidatgrafer fra Pluto

Kandidatkort i Opportunity Radar og v2-rapportvisningen viser et aktuelt Pluto-opslag ved siden af navn og handlingsstatus. Grafen erstatter ingen rapportdata og påvirker ingen signaler eller handler.

## Visning

- Senest kendte `price.currentPrice` vises i aktivets valuta.
- `price.dailyChange` og `price.dailyChangePercent` vises direkte med grøn ↑ ved plus, rød ↓ ved minus og neutral visning ved nul/ukendt. Der omregnes ikke fra procent til beløb eller omvendt.
- **Dag** er standard. Den viser leverede punkter i det rullende døgn frem til seneste observation i `performance.series` (start eksklusiv, slut inklusiv; 24 punkter ved ubrudte timedata). Intervallet følger tidsstemplerne, ikke kalenderdagen. Ved en ældre slutdato vises »Døgn frem til« og datoen. Timer uden observationer udfyldes ikke. Ét punkt giver ét punkt, ingen konstrueret kurve.
- **Uge** er et tilvalg og viser de observerede punkter fra `ONE_WEEK` med Plutos separate `performance.returnPct`.
- Grafens farve og mærket **Udsnit** følger første til sidste viste observation. Dagsændringen ovenover følger fortsat Plutos separate dagstal. Grafen viser antal punkter og betegnes som et udsnit. Prisskalaens grænser vises i aktivets valuta, og skalaen spænder over mindst 1 % af udsnittets midterkurs. Ingen ekstra kurspunkter eller lukkekurs konstrueres. Handlingsstatus AFVENT/KØB/SÆLG beholder sin egen betydning og farve.
- For NASDAQ/NYSE-aktier og ETF'er markeres punkter mellem normal førmarkedsstart kl. 04.00 og ordinær åbning kl. 09.30 i New York som førmarked. IANA-tidszonen håndterer sommertid. Børshelligdage og særlige kalenderændringer er ikke verificeret. Grafen hævdes aldrig at være en komplet handelsdag.
- Grafens tidspunkter og akse vises i Europe/Copenhagen. Plutos tidsstempler med `Z` læses som UTC, også med nanosekundpræcision i inddata. Originalt tidsstempel bevares; webvisningen bruger normaliseret millisekundformat.

Det modtagne eksempel havde dagsændring og en uge med 82 omtrent timevise punkter, heraf to på seneste dato. `close` læses som prisen på et historikpunkt, ikke automatisk som officiel dagslukning. Eksemplet gav ikke en selvstændig kurstid for `currentPrice` eller en særskilt forrige lukkekurs. Der udledes derfor ingen kurstid fra `performance.to` eller sidste grafpunkt, selv når prisen matcher. Kurstid og referencekurs markeres som manglende. Hentetid og seneste grafpunkt vises separat.

## Hentning, identitet og cache

`market_data.py` bruger udelukkende `search_assets` og `get_asset` med `period=ONE_WEEK` gennem de eksisterende, validerede læsekontrakter. Kun en kandidat i brugerens egen v2-rapport kan bruges. Session og CSRF kræves. Input indeholder rapport-ID, kandidat-ID og eksplicit testkategori; disse kontrolleres før netværket.

Ét entydigt eksakt tickerfund kan vælges automatisk. Flere eller tvetydige fund kræver brugerens valg af aktiv/børs. Det valgte aktiv-ID skal findes i den aktuelle Pluto-søgning og matche det modtagne aktiv. Man kan ændre valget via datadetaljerne. En gemt kobling genbruges kun for samme bruger, kandidat og forventede ticker.

Quote- og seriecache er pr. bruger og aktiv. Automatiske opslag bruger fem minutters cache; manuel opdatering har mindst 30 sekunder mellem læseforsøg på samme aktiv. En fejl bevarer et tidligere svar og dets oprindelige hentetid med en advarsel. Priser fra andre valutaer, modstridende aktividentitet, ukendte tidszoner, modstridende samtidige punkter, fremtidige punkter og forkert periode bliver ikke tegnet som en gyldig serie. Dubletter med samme tid og pris foldes sammen. Manglende data bliver ikke til nul.

Browseren henter for synlige kort, højst to samtidig, og holder pause i skjulte faner. Testkort hentes kun efter eksplicit klik og viser et aktuelt Pluto-opslag adskilt fra test-/rapportdata. Periodevalg bruger den samme hentede serie. Knappen Opdatér og træk-ned-funktionen opdaterer også synlige grafer og genbruger igangværende opslag. Der tilføjes ingen cronjob, handelsrettigheder, dataleverandør eller API-nøgle.

## Test og installation

`test_market_data.py` dækker konkret responsestruktur, manglende kurstid, dagsændring kontra ugeafkast, tidszoner, cachealder, bruger-/testadskillelse, tvetydige fund og fejl. `browser_market_charts.py` kontrollerer dag/uge, grafpunkter, førmarked, positive/negative farver uafhængigt af handlingsstatus og layout fra 320 til 1920 pixels. Testdata er syntetiske og ligger alene i midlertidige databaser. Ingen markedseksempler indlæses i produktionsdatabasen.

Installer en frisk ZIP med `apply_update.py` under fx `escape_app/opdatering/kursgraf/`, med appen stoppet. Start og genindlæs. Appen henter selv nye kurser fra brugerens Pluto-forbindelse; de første reelle responsesvar og aktivmatch skal fortsat bekræftes på webhotellet. Der er ingen nye afhængigheder, nøgler, plugin-skemaer eller ændringer af de gemte rapporter.
