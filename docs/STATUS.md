# Funktionsoversigt

| Område | Implementeret | Resterende |
|---|---|---|
| Porteføljer | Separate navne, eksplicit manglende kilde og synkronisering | Pluto MCP-kontrakt, autentifikation, beholdninger, reservationer, kurser, ordrer |
| Global radar | Vedvarende manuel observationsliste med HTTPS-kilde, kildetid, egen klassifikation, katalysator, risiko og næste handling; markeds-/aktivfiltre; vis analysegrundlag og overfør symbol til forslag | Dataleverandør, kildeproveniens, katalysatorer, AI-vurdering, Grav dybere |
| Handelsmotor | Validerede long-forslag, kapitalbehov, FX-antagelse, omkostninger, stoprisiko, lokal godkendelse | Spread, kontantreservation, mæglergodkendelse, idempotent ordreafsendelse, afstemning, afslutning |
| Journal | Vedvarende oprettelses- og godkendelseshændelser | Verificerede udførelser og afkaststatistik |
| Rapporter | Tydeligt inaktiv plan i dansk tidszone | Scheduler, nyhedsdeduplikering, børs-kalendere, alarmer og levering |
| UI | Dansk mørkt responsivt dashboard, navigation, formularer, filtre | Visuel browser/iPhone-test og tilgængelighedsrevision |
| Sikkerhed | Scrypt, HttpOnly/SameSite-session, CSRF, loginbegrænsning, CSP, SQL-parametre, validering | Produktionsserver, TLS, ekstern sessionslager, flerbrugerroller, sikkerhedsrevision |
| PWA | Manifest, SVG-ikon og service worker uden cache af kontodata | HTTPS- og fysisk installationstest, platformsspecifikke rasterikoner |
| Drift | Lokal SQLite, health-endpoint, automatiske HTTP-tests, backupvejledning | PostgreSQL, automatisk backup/restore-test, ekstern overvågning, privat hosting |

Ingen markedsdata er genereret. Handelsinput er brugerens hypotetiske antagelser. Lokale godkendelser sender aldrig ordrer. Ingen faktisk realiseret performance beregnes ud fra forslag.

## Verifikation
Tre HTTP-integrationstests består: adgangskontrol/CSRF/oprettelse/godkendelse/logout; talvalidering og databasepersistens; loginbegrænsning. JavaScript-syntaks kontrolleret med Node. Browser, PWA-installation, eksterne integrationer og frisk miljøgendannelse er ikke testet.

## Eksterne forudsætninger
Der er ingen Pluto-værktøjer blandt sessionens tilgængelige værktøjer og ingen relevante injicerede credentials. Der må ikke opfindes Pluto-endpoints eller forbindes en vilkårlig MCP-server. Næste integrationsarbejde kræver den officielle forbindelsesdokumentation og godkendt adgang. Nyheder, kurser og AI kræver valg af dokumenterede leverandører, datalicens og serverbaserede credentials. Privat publicering kræver en hostingdestination og TLS. Gem aldrig credentials i chat eller Git.

## Opdatering: observationsliste
Fem automatiske tests består inklusive HTTP-oprettelse af observationer, adgangskontrol, CSRF, afvisning af usikre links og tidsstempler samt persistens. Ingen virkelige nyheder er indlæst af udvikleren. Ingen ekstern kilde hentes fra brugerens link. Brugerens klassifikation er ikke uafhængigt verificeret. Grav dybere viser gemte noter og starter ikke en AI-analyse. Browser- og hostingtest af opdateringen er udestående.

## Version 0.3: separate brugere

Invitationsbaserede konti med administrator/member-roller; engangskoder lagres hashed og udløber efter 24 timer. Brugere ser kun egne forslag, markedsidéer og journal og kan kun godkende egne forslag. Sessioner lagres hashed i databasen og er brugerbundne, tidsbegrænsede og kan logges ud på tværs af workers. Loginbegrænsning er delt via SQLite. Den tidligere enkeltbrugerkonto migreres til owner/admin uden ændring af password-hash; gamle data tildeles kun ved entydigt ejerskab.

Forbindelser viser brugerens egen status og kan registrere eller fjerne et lokalt tilslutningsønske. Det er ikke en ansøgning hos Pluto, og OAuth er ikke implementeret. Tokenkryptering bygges først efter verificeret provider-kontrakt og valg af kryptografibibliotek. Ingen Pluto-tokens gemmes nu. Ti automatiske tests består, inklusive migration, invitationers udløb/engangsbrug, HTTP/WSGI CSRF, brugeradskillelse og sessionspersistens. Live deployment og browsertest er ikke udført af agenten.

Forbindelsesknap til Pluto er tilføjet: offentligt standard-metadataopslag, tidsgrænser, afvist redirect, ressourcevalidering og brugerbaseret rate limit. Fjorten tests består. OAuth-login, krypteret tokenlager og porteføljehentning afventer fortsat verificeret provider-kontrakt.
