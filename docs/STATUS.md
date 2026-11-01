# Funktionsoversigt

| Område | Implementeret | Resterende |
|---|---|---|
| Porteføljer | Separate navne, eksplicit manglende kilde og synkronisering | Pluto MCP-kontrakt, autentifikation, beholdninger, reservationer, kurser, ordrer |
| Global radar | Markeds- og aktivfiltre, ærlig tom tilstand | Dataleverandør, kildeproveniens, katalysatorer, AI-vurdering, Grav dybere |
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
