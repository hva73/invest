# Pluto: integration pr. bruger

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
