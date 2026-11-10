# Rapportlevering: evidens, afgrænsning og diagnostik

> **Aktuel læsevejledning (10. november 2026):** Se [masterkontrakten](ESCAPE_MASTER_CONTRACT.md) for præcis readback og forskellen mellem afsenderpåstand og brokerverificering.

## Konklusion fra undersøgelsen

Brugeren har efter den oprindelige blokering verificeret en vellykket automatisk driftslevering kl. 15 dansk tid med 12 kandidater, 11 positioner, 15 ordreposter, 13 kilder og 4 regioner. Rapporten blev valideret, sendt og læst tilbage. Dette er brugerens produktionsobservation; udviklingsmiljøet har ikke uafhængig læseadgang til den aktuelle produktion.

Den observation taler imod en generel fejl i ESCAPEs understøttelse af is_test=false eller den udvidede v2-struktur. Den tidligere besked »Dette værktøj blev blokeret af OpenAI's sikkerhedstjek. Dobbelttjek det, du sender.« indeholder ikke et ESCAPE-valideringsresultat og er ikke en fejltekst defineret i serverkoden. Der er ikke evidens til at fastslå, hvilket konkret indhold, hvilken kaldskontekst eller hvilket internt OpenAI-kriterium der udløste blokeringen. Den nøjagtige årsag er fortsat ukendt. Ingen sikkerhedskontrol er forsøgt omgået.

At get_latest_report efter forsøget viste den tidligere rapport, bekræfter alene den observerede tilbagekontrol på det tidspunkt. Den fulde arkivhistorik og webhotellets logs er ikke undersøgt herfra. Udviklingssessionen har hverken produktionslogin, logadgang eller en tilgængelig ESCAPE-connector. Der er ikke indsat syntetiske rapporter i den faktiske driftsdatabase.

## Hvad der er testet

| Område | Evidens |
| --- | --- |
| Fuld v2, testkategori | Syntetisk 12/11/15/11/4-rapport gennem autoriseret lokal MCP/HTTP, validering, lagring, tilbagelæsning og identisk genforsøg |
| Fuld v2, driftskategori | Samme syntetiske rapportstruktur med is_test=false i en separat midlertidig database; samme report_id kan derfor prøves uden eksisterende test-ID-konflikt |
| Passenger/WSGI og OAuth | Lokal WSGI-adapter, OAuth PKCE, browserlogin/samtykke, fuld syntetisk driftslevering, tilbagelæsning og dublet; browserens HTTPS-adresse videresendes til lokal testserver |
| Normale øvrige autoriserede veje | Session + CSRF-import og eksisterende Bearer-ingest accepterer syntetisk is_test=false; manglende login/nøgle/CSRF afvises |
| Test/drift-forskel | Samme centrale validator og save-funktion. Kategorifilter og historik-/analysis_for-referencer er adskilt efter is_test |
| ID-konflikt | Et allerede gemt test-ID med is_test ændret til false afvises som report_id_conflict; nyt ID accepteres; originalen bevares |
| Sideeffekter | Alle øvrige tabeller forbliver uændrede i leveringstesten, bortset fra forventede rapport-/kandidatlinks og transportens ratetællere. Ingen Pluto-kald eller ordre-/jobændringer |
| Vellykket 15-kørsel på webhotellet | Rapporteret og verificeret ved tilbagelæsning af brugeren, ikke gentaget fra udviklingsmiljøet |
| OpenAI's interne blokering | Ikke reproduceret eller tilgængelig som serverdiagnostik |
| Historiske webhotellogs | Ikke tilgængelige i denne session |

De automatiske fixtures har SYNTHETIC/SYNTHETISK i rapport-ID, kilde, selskabsnavne og analyser og findes kun i midlertidige databaser. De viser ingen faktisk investeringsanalyse eller markedsverifikation. Brugerens præcise JSON fra det afviste kald er ikke udleveret; det er derfor struktur, kategorilogik og normal leveringsvej, der er verificeret, ikke identitet med den konkrete payload.

Samme rapport-ID er unikt pr. bruger på tværs af test og drift. Et kategoriskift ændrer indholdet og kræver nyt ID. Denne eksisterende regel er bevaret og er ikke udpeget som årsag til den rapporterede OpenAI-blokering.

## Sikker diagnostik fra MCP 2.2.1

Hver autentificeret, JSON-parset send_report-anmodning får et tilfældigt trace_id. Serveren skriver JSON-linjer med event=escape_report_delivery og UTC-tid:

- received: anmodningen er nået til MCP-handleren efter autentifikation og JSON-parsning.
- processed / stored: save er afsluttet med en gemt rapport.
- processed / duplicate: samme indhold fandtes allerede; intet overskrevet.
- processed / rejected: konkrete valideringsfejlkoder, uden rapportværdier eller fejltekster.
- processed / conflict: report_id_conflict.
- processed / rpc_rejected: værktøjet/protokolkaldet blev afvist, fx utilstrækkeligt scope.
- processed / transport_rejected: fx ratetællerens slow_down efter modtagelse.
- processed / server_error: en uventet serverfejl; exceptionstekst logges ikke.

Sporingen omfatter internt bruger-ID, schema_version, is_test, antal modtagne poster ved succes og et report_ref, der er de første 16 hextegn af SHA-256(report_id). Rapport-ID, tokens, cookies, kodeord, kilde-URL'er, virksomhedsnavne, vurderinger, positioner og ordreindhold logges ikke. Logmetadata er stadig kontotilknyttet og skal opbevares privat.

trace_id følger med som HTTP-header X-ESCAPE-Request-Id og som delivery_trace_id i MCP-kvitteringens structuredContent, når denne findes. Det indsættes ikke i rapportens payload eller database. validate_report skriver fortsat ingen databaseposter og får ikke denne leveringslog.

Passenger-adapteren skriver til WSGI's wsgi.errors. Webhotellets konfiguration bestemmer, hvilken privat Passenger-/errorlog der modtager strømmen. Den faktiske logplacering er ikke verificeret. Den lokale HTTP-server bruger stderr. En logfejl blokerer ikke rapportlevering.

stored dokumenterer lagring på ESCAPE, ikke at OpenAI-klienten modtog kvitteringen. Kontrollér rapporten ved tilbagelæsning. En manglende event er heller ikke i sig selv bevis for en OpenAI-blokering: anmodningen kan være stoppet før autentifikation/JSON-parsning, af proxy/netværk eller af manglende/roterede logs. En modtaget stored-event kan være efterfulgt af en klient-/netværksfejl, selv om rapporten er gemt.

## Hvordan næste hændelse undersøges

1. Notér report_id, kategori, tidspunkt med tidszone, klientens præcise fejl og eventuelt delivery_trace_id. Del ingen loginoplysninger eller fulde private rapporter i logs.
2. Kontrollér rapportarkivet eller den relevante tilbagekontrol uden at sende rapporten igen. get_latest_report betyder senest modtaget; en senere rapport kan skjule en ældre i dette ene resultat.
3. Find POST /mcp i webhotellets adgangslog og event=escape_report_delivery i Passenger-/errorloggen. HTTP 200 alene betyder ikke en accepteret MCP-værktøjshandling; brug outcome og structuredContent.
4. Sammenhold UTC-tid, trace_id og report_ref. Dansk tid 2. november 2026 er UTC+1; intervallet kl. 14–15 dansk svarer til kl. 13–14 UTC.
5. Brug afvisningskoden fra ESCAPE, hvis den findes. Ved OpenAI-blokering uden serverevidens rapporteres årsagen som uafklaret i klientforløbet; ændr ikke rapportindhold eller værktøjsklassifikation for at undvige kontrollen.

Der fandtes før denne opdatering ingen særskilt MCP-leveringsaudit i appen. app.Handler.log_message er slået fra; Apache/Passenger kan stadig have egne adgangs-/fejllogs. Den nye logning er fremadrettet og kan ikke rekonstruere tidligere kald.

## Bevarede rettigheder og fungerende implementering

send_report har fortsat samme navn, inputstruktur, scopes og annotations: readOnlyHint=false, destructiveHint=false, idempotentHint=true og openWorldHint=false. Beskrivelsen forklarer nu eksplicit, at false skriver en privat driftsrapport, mens true skriver i testindbakken; begge er skrivehandlinger. Den påstår ikke at være read-only eller en ordrehandling. validate_report er fortsat read-only.

Der tilføjes ingen særskilt alternativ afsendelsesmetode for at omgå OpenAI. Eksisterende validator, save, rapporter, kategoriregler, brokerfunktioner og tidsautomatisering er bevaret. Nye metadata giver ingen garanti for klientens sikkerhedsgodkendelse. Serverversionen stiger alene til 2.2.1 for at kunne identificere diagnostikken og beskrivelsesændringen; schema_version for rapporter er fortsat 1/2, og OAuth-scopes/protokolversioner er uændrede. Den eksisterende timekørsel skal ikke redigeres.
