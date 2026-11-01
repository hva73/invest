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
