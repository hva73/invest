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
