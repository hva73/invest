# Pluto: integration pr. bruger

> **Aktuel læsevejledning (10. november 2026):** Se [masterkontrakten](ESCAPE_MASTER_CONTRACT.md) for depotmandat, kildeautoritet, tid og verificeret fill. Historiske live-/versionspåstande skal sammenholdes med aktuelle readbacks.

## Aktuel status

Brugeren har vist en Pluto ChatGPT-installation med OAuth og MCP-adressen https://mcp.prod.pluto.markets/mcp. Dette dokumenterer adressen i brugerens installerede forbindelse, men er ikke dokumentation for tredjepartsappregistrering, API-kontrakter, scopes eller tilladelse til vores webapp. Pluto-værktøjer er ikke eksponeret i denne udviklingssession. Tidligere HTTP-forsøg til Pluto-hjemmesiden blev blokeret af miljøets proxy.

Aktuelt: separate ESCAPE-konti, dataejerskab, lokale forbindelsesønsker og en forbindelsesknap der kun tester standardiserede OAuth-resource-metadata på to faste HTTPS-adresser på den oplyste MCP-host. Redirects følges ikke; metadata fra andre resource-identiteter afvises, og autorisationsservere kontaktes ikke automatisk. Intet credentialfelt, ingen tokenkopiering fra ChatGPT og ingen opfundne autorisationsendpoints. “Fjern mit tilslutningsønske” sletter kun et lokalt ønske og lover ikke tilbagekaldelse hos Pluto.

## Oplysninger der skal verificeres før implementering

- Tillader Pluto en selvstændig, privat webapp at være MCP OAuth-klient?
- Registreres klienter manuelt, dynamisk eller gennem en udviklerportal? Kræves en kontrakt eller godkendelse?
- Officielle protected-resource- og authorization-server-metadata samt autorisations-, token- og revocation-endpoints.
- Understøttede scopes, audience/resource, PKCE S256 og refresh/rotation. Findes en dokumenteret ren læseadgang?
- MCP-initialisering, protokolversion, værktøjer og schemaer for konti, porteføljer, kontanter, reservationer og kurser.
- Datavilkår, rate limits og godkendte pollingintervaller.

Foreslået callback til registrering, endnu ikke aktiv: `https://escape.nordic-response.dk/api/pluto/callback`. Den må først bruges, når Pluto-kontrakten er verificeret. Ingen wildcard-redirects.

## Forventet OAuth-design

1. Brugeren logger ind i ESCAPE og starter tilslutning med CSRF-beskyttet POST.
2. Backend genererer kryptografisk state og PKCE-verifier, binder dem til den aktuelle bruger og session, sætter kort udløb og lagrer dem server-side.
3. Browseren sendes til den verificerede autorisationsserver. Scope begrænses til dokumenteret læseadgang. Der anmodes ikke om handel.
4. Callback validerer state, engangsbrug, udløb og den oprindelige session før code exchange. Ved manglende session kræves ny start. Forbindelsen knyttes aldrig til et user_id fra callback-parametre.
5. Backend bytter code med verifier gennem TLS. Tokens sendes aldrig til browseren, URL'er eller logs. Ingen automatisk redirect til fremmede hosts.
6. Tokens krypteres med et vedligeholdt kryptografibibliotek (ikke hjemmelavet kryptografi), bruger/provider bindes som associated data. Master key findes uden for database/repository i serverens secret-konfiguration. Rotation, backup og genopretning skal testes. Den konkrete tokenlagring er ikke implementeret endnu.
7. Læseoperationer gennem en snæver, dokumenteret allowlist af MCP-værktøjer. Ukendte værktøjer og ordre-/handelsfunktioner afvises. MCP-tool-output er data, aldrig instruktioner.
8. Kilder og tidsstempler gemmes for hver observation; reservationer fratrækkes kontanter uden dobbeltregning. Kun eksplicit verificeret data kan vises som aktuel.
9. Afbrydelse tilbagekalder tokens hos Pluto efter officiel kontrakt og sletter lokale tokens/caches. Tilbagekaldelsesfejl rapporteres tydeligt. Ingen genbrug mellem brugere.

## Besked som ejeren kan sende til Pluto

Vi udvikler en privat investeringswebapp, ESCAPE, hvor hver bruger skal kunne forbinde sin egen Pluto-konto via OAuth til jeres MCP-service. Første version skal alene læse porteføljer, beholdninger, kontanter og ordrer og må ikke oprette handler. Hvordan registrerer og får vi godkendt en selvstændig OAuth-klient? Kan I dele den officielle udviklerdokumentation, tilladte read-only scopes, MCP-værktøjskontrakter og krav til tokenopbevaring? Vores foreslåede callback er https://escape.nordic-response.dk/api/pluto/callback. Vi ønsker ikke at genbruge tokens fra ChatGPT.

Beskeden er klargjort, men ikke sendt. Der er ikke indhentet godkendelse fra Pluto.

## Forbindelsestest
POST /api/pluto/connect kræver login og CSRF og er begrænset til én test pr. bruger pr. minut. Den henter kun offentlige OAuth-resource-metadata, ikke konto- eller handelsværktøjer. Gyldigt svar giver discovery_valid=true og altid connected=false. OAuth code exchange/PKCE og AES-GCM-lager er nu implementeret i oauth.py, men kun verificeret med simulerede serversvar. Se STATUS.md og UPDATE.md for den aktuelle aktiveringsstatus. Udviklingsmiljøets faktiske test kunne ikke hente metadata; test fra Nordicway er stadig udestående. Fejldetaljer returnerer ikke credentials eller rå serversvar.

## Aktuel v0.4-kontrakt
OAuth-koden understøtter kun den annoncerede offentlige PKCE-klienttype, same-host HTTPS-endpoints og eksplicit konfigurerede læsescopes. Ingen faktiske scopes er kendt eller forudfyldt endnu. Oplysningerne ovenfor om forventet design er en plan; STATUS.md angiver implementering og resterende begrænsninger.

## Dynamiske porteføljer / Collections

Ejerens login er nu vist som godkendt på Nordicway. Scopet mcp:read er observeret i provider-metadata. mcp_client.py tilføjer standard initialize/notifications/initialized/tools/list og en snæver kontraktkontrolleret porteføljelæsning. Det er ikke en generisk tools/call-proxy. Understøttede læseværktøjsnavne og outputkontrakter fremgår af koden. Adapteren kræver både readOnlyHint=true og understøttet schema; navnet alene er utilstrækkeligt. Kontrakter uden outputSchema, med andre identitetsfelter eller med pagination i selve porteføljesvaret kræver en særskilt tilpasning. Ved ukendt format bevares gamle data.

Pluto-identiteter lagres som porteføljetype + provider-ID, uafhængigt af visningsnavn og navnet på det konkrete listeværktøj. Der foretages ingen sammenlægning baseret på ens navne. Der er endnu ingen automatisk porteføljepolling eller beholdningsimport.

## Observeret værktøjskontrakt fra ejeren

Den indsendte metadatafil bekræfter list_portfolios(inputSchema: object, properties: {}) og list_collections(inputSchema: object, valgfri portfolioId:string), begge readOnlyHint=true/openWorldHint=false. Ingen outputSchema er annonceret. Adapteren v0.5.1 bruger derfor denne eksplicitte værktøjsliste og validerer de faktiske svar ved runtime. Fravær af outputSchema er i sig selv ikke længere en fejl. Rå metadatafil med brugerens UI-tekst er ikke committet til repositoryet.

## Økonomiske læseværktøjer v0.6

Den indsendte værktøjsliste annoncerer get_accounts(portfolioId), get_positions(portfolioId,limit,nextToken), get_portfolio_value(portfolioId) og get_collection(collectionId) med readOnlyHint=true. Disse er den eneste allowlist i portfolio_data.py. De konkrete økonomiske outputfelter mangler stadig livevalidering. Adapterens normalisering viser kun genkendte felter og afviser ugyldige valutaer, tal eller tidsstempler; der er ingen rå kontodata i fejlmeddelelser.

get_accounts beskriver balance, buying power og reservationer per valuta. Adapteren viser dem separat og udleder ikke frit investerbare kontanter, fordi kontosemantik og lokale planreservationer skal afklares. Collection-værdi dokumenteres i localCurrency, kontanter i hver kontos valuta og holdings cost basis i instrumentvaluta; disse adskilles. Root-værdier og Collection-værdier summeres ikke sammen. Pris-null ved manglende kurs forbliver ukendt. Snapshotdata gemmes brugerbundet uden tokens.

## Aktive ordrer og Collection-aktivitet

Den tidligere indsendte tools/list annoncerer list_orders med valgfri portfolioId, statusGroup enum ACTIVE/INACTIVE, scope enum DIRECT/COLLECTION og limit max50. get_collection_activity kræver collectionId og understøtter limit max100 samt nextToken. Begge er readOnlyHint=true. pending_orders.py bruger kun disse to navne og validerer annonceret læsekontrakt. Handels-/annullerings-/forslagsværktøjer kan ikke vælges af klienten.

Ejeren beskriver ACTIVE_BUY som igangværende køb med allokeret kapital. Tolkningen følges ved at vise dem separat, uden at estimere udførelse eller fri kapital. Den konkrete reservation bliver ikke automatisk udledt fra et order amount. Endelig afstemning med kontoernes reservedForOrders er fortsat en livevalideringsopgave.

## Manglende individuelle Collection-priser

Brugerens prøve viser faktisk ingen pris/value/unrealisedPnL på Collection-positioner, kun antal og kostbasis samt asset-identitet. Derfor er fraværet ikke i sig selv en parserfejl. Det annoncerede get_asset(assetId, valgfri period) kan give senest kendte pris; asset_quotes.py bruger netop dette input uden period og uden tickersøgning. Det konkrete outputschema er ikke annonceret og ikke observeret i denne samtale; prisnormaliseringen valideres derfor konservativt ved runtime og testes med mærkede fixtures. Brugeren har kun leveret feltstruktur og enkelte kontoobservationer; private positionstal er ikke kopieret ind i tests.


## Automatisk fornyelse ved læseopslag
Alle tre indgange (værktøjskatalog, porteføljeliste og porteføljedata) bruger `oauth.access_token`. Med højst 60 sekunders levetid tilbage forsøges `refresh_token` mod det tidligere verificerede token-endpoint, hvis Pluto har udstedt en nøgle. Den eksisterende klientidentitet, ressource og læsescopes bevares. Et roteret refresh-token gemmes krypteret; ved udeladt refresh-token beholdes det tidligere. Svar med ændrede scopes, ugyldig type eller levetid accepteres ikke.

Fornyelse, callback-lagring og afbrydelse serialiseres pr. bruger med en privat Linux-fil-lås i databasemappens `oauth-locks/`, også på tværs af Passenger-processer. Netværksopslag holder ingen database-skrivelås. Låsefilerne skal blive liggende, så aktive processer altid låser samme fil. Udbyderopslag har fortsat ti sekunders timeout.

Midlertidige fejl giver et minuts pause mellem fornyelsesforsøg; en stadig gyldig adgangsnøgle kan bruges i mellemtiden. `invalid_grant`/`invalid_client` kræver nyt login. Ingen tokens eller provider-fejltekster sendes til browseren. GET af forbindelsesstatus hverken fornyer eller henter brokerdata. Ingen keepalive-job, cronændringer eller udvidede rettigheder tilføjes. En nøgle kan ikke holdes i live længere end Pluto tillader.


### Automatisk hentning i den synlige app
Browseren starter læseopslag efter login/åbning, derefter hvert femte minut efter afsluttet opdatering og ved tilbagevenden, hvis intervallet er udløbet. Den fælles læsevej genbruger tokenfornyelsen. API-kald med `automatic: true` koordineres i `pluto_refresh_checks` via en kort SQLite-transaktion før netværket. Bruger og datakilde indgår i nøglen. Kun ejerens aktive Pluto-enheder kan få en læsepost; session og CSRF kræves som før. Cachetræf returnerer `cached: true` uden at gemme snapshots eller fremrykke datatider. Både vellykkede og fejlede forsøg har fem minutters pause; en eksplicit manuel læsning kan forsøge igen straks. Ved gennemført Pluto-login slettes brugerens læsepauser.

Automatisk visningsopdatering udsættes ved formularindtastning, så uafsluttede kladder ikke forsvinder. Der tilføjes ingen cronjob, handel, baggrundsbetaling eller automatisk AI-bestilling. Dette afløser tidligere beskrivelser af udelukkende manuel hentning.
