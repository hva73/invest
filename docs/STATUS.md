# Funktionsstatus v0.4

| Område | Implementeret | Mangler / ikke verificeret |
|---|---|---|
| Brugere | Invitationer, roller, brugeradskillelse, vedvarende sessions, migration af owner | Password reset, 2FA, kontoadministration og sikkerhedsrevision |
| Pluto | Metadata, OAuth authorization-code/PKCE, sessionsbundet engangs-state, dynamisk klientregistrering når annonceret, AES-GCM-tokenlager, tilbagekaldelse når annonceret | Live OAuth-test, dokumenterede læsescopes, mulig provider-godkendelse, MCP-porteføljekontrakter, automatisk tokenrefresh |
| Porteføljer | Separate planlagte porteføljer og ærlige tomme tilstande | Verificerede beholdninger, kontanter/reservationer, priser, afkast og ordrer |
| Radar | Egne kildebelagte idéer, filtre, noter og overførsel af symbol til forslag | Global overvågning, AI-vurdering, automatisk dybdeanalyse |
| Handelsmotor | Long-forslag, hypotetisk kapital/stoprisiko/FX, lokal godkendelse og journal | Brokerintegration, spread/slippage, kontantreservation, reelle handler og performance |
| Datakilder | Adaptere til ECB daglig FX og officielt ECB-pressefeed; kilde- og indlæsningstid; deduplikering | Rigtig indlæsning blokeret fra udviklingsmiljøets netværk; skal verificeres på Nordicway eller efter policyopdatering. Ingen aktiekurser |
| Baggrund | Vedvarende kø, leases, tre forsøg med 15 minutters pause, timeskema, private statusrapporter kl. 08/14/22 Europe/Copenhagen | Cron skal sættes op og verificeres; ingen aktiv konstant overvågning |
| AI | Eksplicit status Ikke tilsluttet; ingen betalte kald | Ejer har kun ChatGPT Plus; API-udbyder, budget og nøgle er ikke valgt |
| Drift | Health, jobhistorik, privat backup ved opdatering, kontrolleret kodeopdatering | Automatisk driftsbackup, retention, ekstern alarm, PostgreSQL, produktionsrevision |

## Testevidens

32 automatiske tests består: HTTP/WSGI-login, migration, kontoisolation, invitationer, CSRF, OAuth-PKCE/callback/replay/udløb/scopekontrol/kryptering/tilbagekaldelsesfejl, kildeparseres validering, jobretry/lease/deduplikering/sommertid og opdatering med databasebackup og rollback ved kopieringsfejl.

En separat Chromium-browsertest består: desktoplogin, oprettelse/godkendelse af forslag, jobkø, invitation og registrering, ny brugers tomme handelsliste samt navigation ved 390px mobilbredde uden vandret side-overløb. Testen bruger kun en midlertidig database og syntetiske testinput. Fysisk iPhone, Safari/PWA-installation og opdatering på Nordicway er endnu ikke testet af agenten.

Pluto og ECB kunne ikke nås fra det aktuelle udviklingsmiljø. Ejeren viste tidligere et HTTP 200 fra Nordicways Pluto-resource-metadataopslag. Dette verificerer ikke authorization-serverens metadata, registrering, læsescopes eller token exchange. OAuth-tests bruger simulerede serversvar. ECB-tests bruger tydeligt mærkede testfixtures, der aldrig indlæses i appens database.

Ingen reelle handler er oprettet, ingen betalte tjenester aktiveret, ingen tokens eller passwords committet. GitHub-opdateringen ændrer ikke Nordicway automatisk.

## v0.5: dynamiske porteføljer

Forudbestemte porteføljekort og formularvalg er fjernet. Hver konto får sin egen porteføljeliste med interne ID'er, kilde og eventuelt provider-ID. Ingen standardnavne oprettes. Lokale enheder kan oprettes/omdøbes; de er udtrykkeligt ikke Pluto-Collections. Eksisterende forslag migreres til lokale porteføljeposter uden at miste deres oprindelige navn. Nye forslag kræver en aktiv portefølje, som tilhører brugeren.

MCP-klienten kan initialisere en sessionsbundet forbindelse, læse tools/list inkl. pagination og vise de faktiske beskrivelser. Synkronisering tillader kun de specifikke read-only-annoncerede listeværktøjer i mcp_client.READ_LISTS, uden obligatoriske argumenter og med et præcist understøttet outputSchema. Ukendte kontrakter afvises før værktøjsudførelse. Understøttede svar valideres før en atomisk afstemning: nye Collections oprettes, omdøbte bevarer ID, fjernede arkiveres. Lokale enheder og andre brugeres data berøres ikke. Listen afstemmes kun ved eksplicit opdatering, ikke endnu automatisk i worker.

Ejerens skærmbillede viser godkendt Pluto-login på Nordicway og provider-metadata med mcp:read, mcp:trade, S256, offentlig klient og dynamisk registrering. Det understøtter loginresultatet, men bekræfter ikke det faktiske tools/list-schema eller porteføljedata. Liveværktøjsliste og import skal afprøves på Nordicway. Der gøres ingen påstand om fungerende portfolio-sync mod et endnu ukendt outputformat.

38 automatiske tests og Chromium-smoketesten består, inklusive brugeradskillelse, vilkårlige navne, ID-bevarelse ved navneændring, arkivering, afviste outputkontrakter og MCP JSON/SSE-opslag. Beholdninger, vægtninger, kontanter og markedsværdier er stadig ikke hentet.

## v0.5.1: observeret Pluto-kontrakt uden outputSchema

Ejerens indsendte tools/list beskriver list_portfolios uden argumenter og list_collections med valgfrit portfolioId, begge readOnlyHint=true og uden outputSchema. Den tidligere obligatoriske outputSchema-gate var årsagen til den viste kontraktfejl. Adapteren tillader nu præcis disse to observerede værktøjer uden at kræve outputSchema. get_portfolios/get_collections er ikke længere mulige aliaser. Andre værktøjer med readOnlyHint, herunder draft-editorer, accepteres ikke.

Svar læses enten fra structuredContent eller JSON i MCP-content-tekstblokke. Direkte arrays og eksplicitte portfolios/collections/items/data-listenøgler valideres; id/portfolioId/collectionId og navne matches uden at opfinde værdier. Modstridende ID'er, dubletter, pagination eller totalCount-afvigelser afviser hele importen. Ukendte svar giver en fejl med feltnavne/typer uden kontoværdier og bevarer eksisterende data. De faktiske porteføljesvar fra Nordicway er endnu ikke modtaget eller verificeret.

Importerede enheder får type portfolio/collection og valgfri forældreportefølje samt canTrade-status, når dette findes i svaret. Collection-værdier lægges ikke til porteføljeværdier; økonomiske totaler er stadig ikke hentet. 42 automatiske tests og Chromium-smoketesten består. Testpayloads er syntetiske og kommer aldrig i brugerens database.

## v0.6: beholdninger, værdi og kontanter

Tilføjet portfolio_data.py med fire snævre, observerede læseværktøjer: get_portfolio_value, get_accounts, get_positions og get_collection. Opslag sker pr. bruger og pr. aktiv, importeret portefølje-ID. Positionssider følger nextToken med samme portfolioId og limit=200; gentagne tokens, uforståelig pagination og sidegrænser afvises. Collection-data bruger localCurrency til Collection-værdi, mens kontanter og instrumentværdier beholder deres egne valutaer. accountCurrency bruges aldrig som erstatning.

Ny detaljevisning med gemt værdi, kildetid, indlæsningstid, beholdningsantal, senest oplyste pris, kostpris, værdi, urealiseret resultat samt kontantbalance, reserveret beløb og købekraft. Null bevares som ukendt, ikke som nul. Manglende pris-/værditidspunkt vises eksplicit. Senest registreret værdi mærkes ikke som live. Realiseret resultat og frit investerbare kontanter beregnes ikke ud fra uverificerede antagelser.

Øverste sum bruger kun aktive rodporteføljer og grupperer pr. valuta. Collections og lokale enheder lægges ikke oveni; der vises antal manglende rodværdier. Dette er en sum af gemte observationer med eventuelt forskellige kildetidspunkter, ikke en samtidige liveværdi. Ved fejl bevares gamle snapshots med fejlstatus; ved delvise fejl vises de lykkede sektioner og de konkrete fejl. En helt mislykket læsning erstatter ikke tidligere tal med nye tomme data.

Worker kan planlægge pluto_data-jobs hver time for aktive Pluto-enheder med et endnu gyldigt token. Dette kræver stadig aktiv cron og ophører ved tokenudløb; automatisk OAuth-refresh er endnu ikke implementeret. Portefølje-/Collection-listen skal fortsat opdateres manuelt, så nye enheder kan komme med i jobs.

52 forskellige automatiske tests består (samlet suite med 51, efterfulgt af målrettet finansregression med ekstra valutaseparationstest). Chromium-smoketesten består også med porteføljedetaljer og finansielle testfelter. Alle finansielle testpayloads er syntetiske og gemmes kun i midlertidige testdatabaser. Ejerens rigtige økonomiske Pluto-svar er ikke modtaget eller verificeret; adapteren kan kræve tilpasning til felterne på Nordicway.

## v0.6.1: porteføljeværdi fra equity

Ejerens live-fejltekst på Nordicway viste get_portfolio_value-felterne timestamp:str, equity:str, profitLoss:str og currency:str. normalize_value accepterer nu equity som porteføljeværdi og timestamp som kildetid. profitLoss klassificeres ikke som realiseret/urealiseret afkast uden dokumenteret semantik. Modstridende value/equity-felter afvises. Alle 12 relevante finansielle tests består, herunder to nye regressionstests. Selve beløbet er endnu ikke verificeret i ejerens UI efter rettelsen.

## v0.6.2: samlet billedgennemgang

Ejerens billeder viser beholdningsrækker, men fortsat equity-formatfejl fra et gemt snapshot og ukendte kontantbalance-/købekraftfelter. Equity-rettelsen indgår i den nyeste kode; efter installation kræves et nyt Pluto-opslag for at erstatte gamle snapshotfejl. Kontosektionen giver nu en afgrænset diagnose med feltnavne/datatyper, hvis balance eller købekraft er ukendt, selv når reservationen kan læses. Den gætter ingen beløb og lækker ingen kontoværdier i diagnosen.

Små ikke-nul-beløb bruger nu betydende cifre i visningen og afrundes ikke fejlagtigt til 0,00. Ekstremt små tal under JavaScripts Number-område vises med deres decimale eksponenttekst frem for nul. Antal vises med dansk formatering. Kursens kildetid forbliver ukendt, når Pluto ikke leverer et fortolkeligt tidspunkt. Der udledes ikke en ny kurs fra positionsværdi/antal.

55 Python-tests, formatteringsregression med Node og Chromium-smoketesten består. Kontantbalance/købekraft er fortsat uafklaret for ejerens faktiske kontosvar; næste opslag skal give den nødvendige feltdiagnose. Skærmbilleder med private beløb er ikke gemt i repositoryet.

## v0.6.3: observerede kontofelter og Collection-indpakning

Ejerens nye billeder bekræfter, at equity/timestamp nu bliver vist som porteføljeværdi og kildetid. Kontodiagnosen viser currency, cash, withdrawalPower og reservedForOrders. Adapteren læser nu cash som kontantbalance og withdrawalPower som særskilt hævbart beløb. Withdrawal power bliver aldrig omdøbt til buying power eller frit investerbare kontanter. Købekraft er fortsat ukendt, hvis buyingPower ikke leveres, og dette alene giver ikke længere en fejl, når de kendte kontofelter kan læses.

Det observerede Collection-svar har collection:dict, holdings:dict, accounts:list og value:dict. Metadata og økonomiske sektioner bevares separat. Indlejrede listeindpakninger understøttes i højst tre niveauer med faste nøgler, ikke gennem vilkårlig søgning efter arrays eller sammenlægning af dict-værdier. Pagination og count-uoverensstemmelser afvises. Ved ukendte holdings bevares de succesfuldt læste værdi-/kontosektioner, og beholdningsfejlen vises. Ny diagnose viser kun tilladte strukturnøgler og typer; ukendte nøgler skjules for ikke at lække eventuelle kontoid'er brugt som dictionary-nøgler.

59 Python-tests, formatteringsregression og Chromium-smoketesten består. De faktiske felter inde i holdings- og value-objekterne er ikke vist i ejerens billeder; understøttelse af den konkrete Collection skal fortsat verificeres på Nordicway efter installation. Ingen private beløb eller kontonavne fra billederne er gemt i repositoryet.

## v0.6.4: tydeligt hierarki og nøglebaserede Collection-beholdninger

Ejeren har bekræftet, at Pluto-rodporteføljens værdi omfatter Collections. Opsummeringen var allerede afgrænset til rodporteføljer; denne regel er fortsat regressionstestet. Collections vises nu indrykket under den portefølje, hvis provider-ID matcher deres parent_external_id. Ingen tilknytning gættes ud fra navn, bruger eller beløb. Enheder uden kendt tilknytning vises separat. Collection-detaljer forklarer, at værdien allerede indgår i forældrens samlede værdi.

Collection-holdings kan nu læses fra et objekt med ID-nøgler, når samtlige værdier er beholdningsposter med instrumentidentitet og quantity. Et enkelt navngivet listeomslag kræver samme postvalidering; allocations/weights uden quantity accepteres ikke som beholdninger. Assets-listeomslag understøttes. Ukendte nøgler vises stadig ikke i diagnosen, men deres værdiers strukturelle typer vises i afgrænset dybde uden private feltværdier.

62 automatiske tests, formatteringstest og Chromium-smoketest består. Browseren kontrollerer nu også, at en Collection placeres inde i forælderens visuelle gruppe. Ejerens faktiske indre holdings-format er endnu ikke verificeret efter rettelsen; fortsat fejl skal diagnosticeres fra den nye strukturtekst. Kontant-/Collection-værdiopslag, som lykkes, bevares som selvstændige sektioner.

## v0.7: Collection-wrapper og visuelt løft

Den nyeste live-diagnose viste en enkelt objektindpakning omkring et objekt med positions:list, localCurrency og accountCurrency. Collection-læseren følger nu også en sådan entydig enkelt-objektgren inden for den eksisterende dybdegrænse. Antalskontrol og afvisning af nextToken/partial-respons bevares. En ny regressionstest dækker den observerede struktur med syntetiske værdier. Faktisk beholdningsimport på Nordicway skal stadig verificeres efter opdatering.

UI opdateret med marineblå flader, diskrete guldtoner, større værdital, instrumentmærker og tydeligere hierarki. Urealiseret positivt resultat vises grønt med opadgående SVG-pil, negativt rødt med nedadgående pil og faktisk nul neutralt. Null giver hverken pil eller falsk nul. Pile angiver urealiseret resultat mod kostpris, ikke dagsmomentum eller en historisk prisudvikling. Der er ingen konstruerede kurver, trendprocenter eller porteføljeafkast fra det uafklarede profitLoss-felt.

Tekniske delvise fejl samles under en fungerende fold-ud datastatus; beskedfarver adskiller information, hentning, succes, advarsel og fejl. Kildetider vises i dansk tid med sekunder, og navigation til nye visninger ruller til toppen. Interne lokale portefølje-ID'er er fjernet fra kortenes tekst. Eksisterende ID-baserede handlinger og brugeradskillelse bevares.

64 Python-tests, Node-formatterings-/piletests og Chromium-flow på desktop/390px mobil består. Desktop-/mobilbilleder fra midlertidige testdatabaser er visuelt kontrolleret; ingen faktiske markedsdata eller private brugerkonti bruges i skærmtesten. Fysisk iPhone/Safari skal stadig afprøves af ejeren.

## v0.8: ACTIVE_BUY og allokeret kapital

ACTIVE_BUY detekteres i positioners status/type og holdes ude af gennemførte beholdninger. Afventende poster vises i en selvstændig sektion med kilde, status, ønsket antal, udtrykkeligt oplyst udført antal, eksplicit allokering og separat ordrebeløb. Der udledes ikke allokering fra cost basis, markedsværdi eller ønsket antal, og et ordrebeløb fortolkes ikke automatisk som reservation.

To yderligere observerede læseværktøjer bruges: list_orders(portfolioId,statusGroup=ACTIVE,limit=50) og get_collection_activity(collectionId,limit=100,nextToken). Collection-ordrer filtreres på eksplicit Collection-ID; manglende forældreportefølje gættes ikke. Den aktive ordrelistes grænse på 50 og manglende/ukendt pagination gør oversigten udtrykkeligt delvis. Activity-sider hentes med tokenkontrol og højst 20 sider. Kun ACTIVE_BUY fra aktivitet behandles som afventende køb; historiske afsluttede aktiviteter bliver ikke nye beholdninger.

Observationer sammenlægges kun, når de deler et eksplicit orderId eller tradeId. Uden sikker fælles reference vises kilderne separat og der beregnes intet samlet ekstra reservationsbeløb. Konflikter markeres. reservedForOrders forbliver brokerens kontoobservation, vises én gang pr. konto og ændres ikke af ordreimporten. Kontantbalance, porteføljeværdi og Collection-værdi reduceres ikke af den nye tabel. Frit investerbart beløb er stadig ukendt, indtil dækningen mellem konkrete allokeringer og reservationer er verificeret.

72 Python-tests, formatteringstest og Chromium-flow består. En ekstra browserkontrol verificerer to syntetiske ACTIVE_BUY-poster i en separat tabel; ingen faktisk ordre er oprettet eller ændret. Ejeren har oplyst to ACTIVE_BUY på sin Collection, men deres faktiske status-/beløbsfelter og referencer skal stadig verificeres efter deployment. Antallet to er aldrig hardcodet i produktkoden.

## v0.9: Collection-priser via aktiv-ID og mærkede beregninger

Ejerens læseprøve af get_collection bekræfter holdings.portfolioView.positions med assetId, quantity, quantityAvailable, averageEntryPrice, costBasis og asset(id,name,ticker,currency). Pris, individuel markedsværdi og individuelt urealiseret resultat mangler helt; de er ikke null. Adapteren bevarer nu aktiv-ID og afviser modstrid mellem assetId og asset.id.

asset_quotes.py kan supplere manglende Collection-priser med præcis get_asset(assetId), kun når værktøjet annonceres som read-only med understøttet input. Ingen tickersøgning, tvetydigt instrumentvalg eller kopi af gennemsnitlig købspris som aktuel pris. Der er højst 20 unikke opslag pr. opdatering og cache pr. opdatering, ikke på tværs af brugere. Ingen pris gives status live; prisens kildetid og indlæsningstid er adskilt, og manglende kildetid bevares som ukendt.

Når antal er positivt og valuta kan matches, beregnes en manglende positionsværdi som antal × senest kendte pris med Decimal. Kun for denne beregnede værdi kan manglende urealiseret resultat beregnes som værdi minus kostpris i samme valuta. Beløbene mærkes som beregnede og er ikke Plutos oplyste positionsresultater. Eksisterende broker-beløb overskrives ikke. Manglende ID/pris/valuta eller fejl giver ukendte beløb og en afgrænset diagnose. ACTIVE_BUY er allerede filtreret fra gennemførte positioner og får ingen prisbaseret holdingsværdi.

Collection-/portefølje-profitLoss vises særskilt som Plutos oplyste resultat, uden påstand om realiseret/urealiseret opdeling eller afkastperiode. Source equity og profitLoss ændres ikke af de beregnede instrumentbeløb. Ingen FX-konvertering foretages, og Collection-instrumenter lægges ikke til rodporteføljens total.

79 Python-tests, formatteringsregression og Chromium-flow består. Browseren verificerer særskilte mærkater for beregnet værdi, beregnet urealiseret resultat og Plutos oplyste resultat. Testkurser og beløb er syntetiske og ligger kun i midlertidige testdatabaser. Det faktiske get_asset-prissvar mangler endnu liveverifikation på Nordicway og kan kræve felttilpasning; ingen påstand om fungerende aktuelle markedspriser før den kontrol.

### Mobilkort og indlejrede aktivpriser
- get_asset price.currentPrice understøttes med kontrol af prispostens assetId og aktivets valuta. Dagsændring bruges ikke som urealiseret resultat.
- ACCEPTED alene flyttes til særskilt uafklaret udførelsesstatus; tælles ikke som afventende eller gennemført. ACTIVE_BUY uden aktivnavn vises som køb af den kendte Collection.
- Ordrekort på alle skærme; kontanter og beholdninger som kort på mobil. Kompakt navigation med alle funktioner, større trykflader og sekundære oplysninger under detaljer.
- Validering: 81 Python-tests samt JavaScript-formatering og browserkontrol. Eksterne Pluto-svar er ikke hentet i denne test.

### Manuel nyhedshentning i Opportunity Radar
Knappen Opdatér nyheder henter det officielle ECB-feed direkte i den autentificerede forespørgsel uden worker eller cron. CSRF kræves; en fælles 60-sekunders pause begrænser hentninger. Nyheder deduplikeres og tidligere data bevares ved fejl. Offentlige nyheder deles mellem brugere; private markedsidéer er fortsat adskilte. Seneste succes og fejl vises. Ingen AI-analyse, handelssignaler eller betalte datakilder.
Verifikation: automatisk testpakke og browser; særskilt test for manuel hentning, pause, deduplikering og bevarelse ved fejl. Live ECB-kald fra udviklingsmiljøet blokeres af netværksproxy (403); webhotellets adgang skal verificeres med knappen efter installation.
