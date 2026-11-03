# Afleveringsstatus — 3. november 2026

Grundlag: [komplet V2.2-tillæg](REQUIREMENTS_V2_2_DA.md) og den oprindelige positionsopgave. Dette omfatter også de gendannede designændringer, som endnu ikke var lagt på GitHub ved miljøafbrydelsen.

## Implementeret

- Individuelle positionsvurderinger, eget depot/positions-ID, datamangler, uafhængige BTC-positioner, kildegrundlag, positionshistorik og relevante ændringer. Arkiv bevarer rapportens egen vurdering; overblik kan vise senere uddybning. Aktuelle Pluto-kurser bruger eksisterende read-only kontrakt.
- Faktisk Collection-specifikation er bevaret på portefølje- og detaljesider. Værdier og resultat følger fælles farver/pile og åbner underliggende oplysninger på Overblik, Porteføljer og Analyser. Ingen opdigtet retning ved ukendt ændring.
- Valgfri eksplicit KØB/AFVENT/FRAVÆLG-beslutning, fuld købsplan, aktiv/hvilende kandidatregister, dokumenteret genaktivering og append-only beslutningshændelser. Kandidater mistes ikke, fordi en senere rapport udelader dem. Legacy-signaler er bevaret og skaber ikke automatisk en ny beslutning.
- Separat HOT WATCH-lagring og on-demand modtagelse, tidslinje, kilde-/datatid/venue/feed/forsinkelse, sammenlignelige ændringer, tilknyttet position/ordrer og hele kandidatforløbet. Seneste verificerede kurs bevares med egen tid, selv ved en senere ukendt observation.
- Ordretype, priser, godkendelse, rå status, fyldt antal og udførelsespris adskilt. Accepteret med nul fyldning bliver ikke et salg. Nyere rapportstatus kan vises efter seneste watch-måling.
- Root og AI summeres ikke; root-minus-AI kræver samme tid, valuta, metode, parent-forhold og verificerede kildereferencer. Tilgængelig/reserveret/øremærket/ukendt likviditet kan oplyses særskilt.
- Struktureret regionsdækning, fire forventede regioner med ukendt-markering ved manglende opdatering, særskilt EOD-/intradaggrundlag og dokumenterede huller.
- Leveringsbeviser for ny modtagelse/validering/lagring og senere digest-kontrolleret tilbageslæsning. Konflikt, valideringsafvisning og ukendt levering holdes adskilt. Gamle rapporter får ikke opdigtede historiske kvitteringer.

## Genbrug og database

Genbruger v1/v2-schema, central validering, immutable rapportarkiv, kandidatlinks, journal, ejerskab, is_test, idempotens, OAuth-scopes, eksisterende markedskurscache, analysepakker, diagramsystem, porteføljesnapshots og opdateringsscript.

Nye additive SQLite-tabeller: `report_position_links`, `candidate_decision_events`, `hot_watch_observations`, `report_delivery_evidence`. Der er ingen omskrivning af eksisterende rapportpayloads/digest og ingen ændring i broker-, ordre- eller scheduler-tabeller som følge af rapporter/observationer. Se [kontrakt og migration](V2_2_WORKFLOWS.md).

## API og generator

Nyt: autentificeret GET/POST `/api/reports/hot-watch`, GET `/api/reports/position-history`, MCP `record_hot_watch` (reports:write) og `get_hot_watch` (reports:read). Rapportvisninger får additive metadata; de rå lagrede rapportdata er uændrede. send_report/validate_report accepterer valgfrie v2-felter fra samme kontrakt. MCP-serverversion 2.4.0; rapportens schema_version er fortsat 2.

Der medfølger schemafiler, komplet syntetisk positionsrapport og separat syntetisk watch-måling samt generatorvejledning. Se [positionsfelter](POSITION_ASSESSMENTS.md) og [V2.2-workflows](V2_2_WORKFLOWS.md).

## Verifikation

- **206 Python-tests bestået** i den samlede suite, herunder eksisterende v1/v2, atomisk afvisning, idempotens, konflikt, ejerskab/kategori, read-only validering, 12 positioner, uafhængige BTC-poster, separat dybdeanalyse/arkiv, genaktivering, observationshistorik, HTTP-login/CSRF og MCP-scopes.
- **3 JavaScript-tests bestået**: signalprioritet, præcis talvisning og kildefriskhed.
- Browser-tests bestået: `browser_positions.py`, `browser_intel.py`, `browser_overview.py`, `browser_latest_desk.py`, `browser_layout_preview.py`, `browser_market_charts.py`, `browser_data_refresh.py`, `browser_report_v2.py`. Samlet kontrollerer de 320–1920 px, focus/Escape, kliks underliggende data, Collection-specifikation, historik, clipboard-fallback, grafer, dataopdatering og uændret testadskillelse. Mobil-/desktop-skærmbilleder er visuelt gennemgået.
- Syntetisk MERC-forløb dokumenterer anskaffelse/beholdning, flere målinger, salgsbeslutning, accepteret STOP med 0 fyldning og en senere delvis fyldning som separate fakta. Der er ingen livebroker-kald i dette acceptforløb.
- En syntetisk regressionsrapport med ID `escape-v2-production-check-001` bevarer payload/digest under migration og efterfølgende observationer. Den faktiske driftsrapport er ikke tilgået eller ændret.

## Begrænsninger og installation

Der er ikke foretaget produktionsinstallation, faktisk MERC-forløb/import, rigtige Pluto-handler eller ændring af eksisterende timeautomatisering. Rigtige MERC-observationer og individuelle analyser skal leveres med deres faktiske kilder/tider. Ældre data uden nye felter forbliver læsbare og viser ukendt/legacy/data mangler.

En server kan ikke se en OpenAI-blokering, der sker før kontakt, eller bevise klientens modtagelse af et svar. Den tidligere konkrete blokering kan derfor ikke forklares ud fra denne implementering. Maks. 500 HOT WATCH-målinger pr. forespørgsel og 50 kandidat-/positionsrapportobservationer i historikvisninger; begrænsning oplyses, og rapportpayloads bevares. Der beregnes ikke realiseret resultat, hvis leverede kost-/fyldnings-/omkostningsdata er utilstrækkelige eller tvetydige.

Installér manuelt med det medfølgende apply_update.py under `opdatering/positionsvurderinger/`; genindlæs derefter MCP-værktøjerne. Ingen nye produktionsafhængigheder. [Installationsvejledning](UPDATE.md).
