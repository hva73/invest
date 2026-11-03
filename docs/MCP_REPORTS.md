# ESCAPE ↔ ChatGPT: privat MCP-rapportforbindelse

## Status og grænser

MCP-modtagersiden er implementeret og testes lokalt gennem den faktiske Passenger/WSGI-adapter. Brugeren har nu bekræftet manuel levering og tilbagekontrol fra ChatGPT i produktion; se [REPORT_V2.md](REPORT_V2.md) for kvittering og afgrænsning. **Planlagt automatisk levering er fortsat ikke verificeret**. Dette er en privat rapportintegration; ikke en ny AI-motor, ingen ekstra AI-API og ingen Pluto-værktøjer.

Forsøg på at læse de officielle dokumentationssider fra udviklingsmiljøet blev blokeret af netværksproxyen med HTTP 403. Implementeringen bruger MCP Streamable HTTP/JSON og OAuth authorization-code med PKCE. ChatGPTs aktuelle kontoadgang, udviklertilstand, OAuth-klientmetoder, callback og evne til at køre skriveværktøjer i planlagte opgaver skal verificeres i den konkrete ChatGPT-konto. En vellykket lokal protokoltest er ikke bevis for disse produktfunktioner.

Officielle kilder til den efterfølgende kontrol:

- https://developers.openai.com/apps-sdk/build/auth/
- https://platform.openai.com/docs/guides/developer-mode
- https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- https://help.openai.com/en/articles/10291617-tasks-in-chatgpt

## Adresser efter installation

| Funktion | URL |
| --- | --- |
| Privat MCP | `https://escape.nordic-response.dk/mcp` |
| Beskyttet ressource-metadata | `https://escape.nordic-response.dk/.well-known/oauth-protected-resource/mcp` |
| OAuth-metadata | `https://escape.nordic-response.dk/.well-known/oauth-authorization-server` |
| Klientregistrering | `https://escape.nordic-response.dk/oauth/register` |
| Godkendelse | `https://escape.nordic-response.dk/oauth/authorize` |
| Token | `https://escape.nordic-response.dk/oauth/token` |
| Tilbagekaldelse | `https://escape.nordic-response.dk/oauth/revoke` |

Stateless Streamable HTTP: JSON-RPC 2.0 i POST `/mcp`, JSON-svar; GET/DELETE returnerer 405. Ingen langvarige processer, SSE-stream eller session-affinitet er nødvendig på cPanel. Understøttede versioner: `2025-06-18` og `2025-03-26`; klienten skal acceptere en understøttet version ved initialize-forhandling. Initialiseret-notifikation giver 202 uden indhold. JSON-RPC-batches understøttes ikke. Requesten begrænses til 300 KiB; v1-rapporten til 16 KiB og v2 til 256 KiB. Se REPORT_V2.md. Forkert Origin afvises; server-til-server-klienter kan udelade Origin.

## Sikker opsætning i cPanel

Installer den nye ZIP via det eksisterende `apply_update.py` med appen stoppet. Database og eksisterende OAuth/ingest-nøgler bevares. Ingen nye Python-pakker kræves.

Python-appens miljøvariabler:

| Variabel | Værdi |
| --- | --- |
| `ESCAPE_PUBLIC_URL` | `https://escape.nordic-response.dk` (eksisterende variabel) |
| `ESCAPE_MCP_ENABLED` | `1` |
| `ESCAPE_MCP_REDIRECT_URIS` | Den **præcise HTTPS callback-URL**, som den konkrete ChatGPT-klient bruger. Flere kan separeres med komma. Ingen wildcards. |

Der kræves ingen ny delt API-nøgle til MCP. Udelad `ESCAPE_MCP_ENABLED`, eller sæt den til `0`, for at slukke integrationen. Manglende callback-allowlist betyder, at klientregistrering afvises; aldrig løs dette med en wildcard-URL.

Klientregistreringen accepterer public clients med `token_endpoint_auth_method: "none"`. Klient-ID genereres på serveren; callback kontrolleres mod den præcise administratorvalgte allowlist. Authorization-code + PKCE **S256** er obligatorisk. `resource` skal være den fulde MCP-URL i både godkendelses- og tokenanmodningen. Scopes er `reports:read` og `reports:write`; klienten kan få kun læseadgang. Hvis ChatGPT i den konkrete konfiguration kræver en anden klientautentifikation, er dette **en kompatibilitetsblokering**, ikke noget man skal omgå ved at dele en ingest-nøgle eller deaktivere PKCE.

ESCAPE-login og et eksplicit samtykke er obligatorisk for hver ny godkendelse. Callback, scopes og den indloggede konto vises før godkendelse. Browserflow bruger eksisterende session og CSRF-beskyttelse. Modtagerens user_id kommer kun fra samtykket, aldrig fra rapportens JSON.

Adgangstokens udløber efter en time. Refresh-tokens udløber efter 30 dage og roteres ved brug. Genbrug af et allerede brugt refresh-token tilbagekalder hele den tilknyttede godkendelse. Koder er engangs og udløber efter to minutter; samtykkeanmodninger efter ti minutter. Kun token-/kodehashes lagres i databasen. Der er ratebegrænsning på registrering, autorisation, tokenudstedelse og MCP-kald.

Tilbagekaldelse: **Forbindelser → Rapportforbindelser → Tilbagekald alle rapportforbindelser**. Det gælder kun den indloggede bruger. Det påvirker ikke Pluto-login. Også afsenderen kan bruge OAuth `/oauth/revoke`. En deaktiveret ESCAPE-konto kan ikke bruge godkendelsen.

Den eksisterende nøgle til `/api/reports/ingest` er separat og kan **ikke** bruges som MCP-adgangstoken. Ingen hemmeligheder skal indsættes i ChatGPT-samtaler, opgaveprompter, frontend, URL-parametre eller repository. OAuth sender nødvendige kortlivede koder/tokens direkte til den godkendte klient efter standardflowet.

## Forbind til ChatGPT: kontrolleret fremgangsmåde

1. Installer opdateringen i ESCAPE. Kontrollér at HTTPS virker uden certifikatfejl.
2. I ChatGPT-kontoens indstillinger: undersøg **Apps / Apps & connectors → Avanceret / Developer mode**. Navne og tilgængelighed kan variere. Hvis der ikke findes en understøttet mulighed for at tilføje en privat remote MCP-app, stop her; ChatGPT Plus alene dokumenterer ikke adgang til den.
3. Start oprettelse af en privat app/connector med navnet **ESCAPE Reports**, URL `https://escape.nordic-response.dk/mcp`, transport Streamable HTTP og OAuth. Vælg dynamisk klientregistrering/public PKCE, hvis denne valgmulighed understøttes.
4. Find den præcise callback-URL i klientens aktuelle opsætning eller officielle dokumentation. Sæt denne som `ESCAPE_MCP_REDIRECT_URIS` i cPanel, sæt `ESCAPE_MCP_ENABLED=1`, gem og genstart appen. Hvis callback ikke kan findes, skal den afklares; gæt ikke og del ikke en hemmelig nøgle for at komme videre.
5. Start/genstart **Connect** fra ChatGPT. ESCAPE skal åbne sin egen HTTPS-login-side. Log ind på den konto, der skal modtage rapporterne. Godkend de viste rapportrettigheder. En ukendt callback eller en godkendelse du ikke selv startede, skal afvises.
6. Kontrollér at ChatGPT viser værktøjerne `validate_report`, `send_report` og `get_latest_report`. Ingen broker-/handelsværktøjer skal være tilgængelige gennem denne app.
7. Bed først om `get_latest_report` med `{"is_test":true}`. Tomt resultat er tilladt. Bed derefter om at sende eksemplet nedenfor som testdata; godkend eventuel skrivehandling i ChatGPT.
8. Bed om `get_latest_report` med `{"is_test":true}` og sammenlign `report_id`, `received` og indholdet. Se samme rapport i ESCAPE under **Rapporter & alarmer → Åbn rapportindbakke → Rapporttype: Testdata → Hent seneste rapport**.
9. Gentag `send_report` med helt samme ID og indhold: `duplicate:true` forventes. Standardkald `get_latest_report` uden argument læser kun driftsrapporter og skal ikke returnere denne test.

Hvis ChatGPTs forbindelse fejler, registrér status/fejltekst uden tokens. `503`: integration deaktiveret eller public URL forkert. `invalid_redirect_uri`: callback ikke tilladt. `invalid_target`: resource er ikke den eksakte MCP-URL. `invalid_grant`: udløbet/brugt kode, PKCE, klient-ID eller resource matcher ikke. `401` på `/mcp`: token mangler, udløbet eller tilbagekaldt. En vellykket ChatGPT-forbindelse må først dokumenteres efter ovenstående reelle test.

## Værktøjerne

### `send_report`

Argumenterne er **direkte et JSON v1- eller v2-rapportobjekt**, ingen ekstra `report`-wrapper. Se [REPORT_INGEST.md](REPORT_INGEST.md) og `examples/report-ingest-test.json` for alle felter og grænser. `schema_version`, `report_id`, `generated_at`, `source`, `is_test`, `portfolio_values`, `candidates`, `assessments`, `orders` er obligatoriske. Ukendte felter afvises; skrivning kræver `reports:write`.

Eksempel på MCP-request (OAuth-token må kun håndteres af klientens sikre integrationslag):

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "method": "tools/call",
  "params": {
    "name": "send_report",
    "arguments": {
      "schema_version": 1,
      "report_id": "chatgpt-mcp-test-001",
      "generated_at": "2026-11-01T20:00:00Z",
      "source": "Manuel MCP-integrationstest",
      "is_test": true,
      "portfolio_values": [],
      "candidates": [],
      "assessments": [{"subject":"MCP-test","assessment":"Kun syntetisk test. Ingen handler."}],
      "orders": []
    }
  }
}
```

Vellykket `structuredContent`: `{"ok":true,"id":1,"duplicate":false}` (ID varierer). Værktøjet er markeret som skrivende, ikke-destruktivt og idempotent. Modstridende indhold med samme ID giver `isError:true` og ændrer ikke den eksisterende rapport. Det er ikke tilladt at genbruge samme ID for både test og drift; brug forskellige stabile rapport-ID'er.

### `get_latest_report`

Argument `{"is_test":true}` læser kun testdata. `{"is_test":false}` eller `{}` læser kun driftsdata. Kræver `reports:read`. Returnerer `{"report":null}` eller `{"report":{"id":1,"received":"...","data":{...}}}` som både JSON-tekst og structuredContent. Rapportindhold er ubetroet afsenderdata, ikke instruktioner eller verificerede brokerdata.

## Database, testdata og handelsadskillelse

Begge værktøjer kalder `report_ingest.save/latest`. De bruger den eksisterende `ingested_reports`-tabel i `var/escape.db`, samme formatvalidering, user_id-ejerskab og unikhed på `(user_id, report_id)`. Der er **ingen parallel rapportdatabase**. En migration tilføjer indekseret `is_test` og klassificerer eksisterende rækker ud fra deres gemte JSON. Testdata får ikke lov til at fortrænge den seneste driftsrapport. Rapportindbakken kræver nu et eksplicit valg af Testdata for at se tests; gamle testrapporter slettes ikke.

Rapportværdier summeres ikke og ændrer aldrig Pluto-porteføljer, Collections, kandidatlister, kontanter, handelsforslag eller ordrestatus. Der eksponeres ingen netværksproxy, vilkårlige SQL-kald, Pluto-token, brokerfunktion eller eksekvering af rapporttekst.

## Lokal ende-til-ende-test

```bash
python -m unittest discover -s tests -v
node tests/test_format.js
python tests/browser_mcp_reports.py
python tests/browser_report_ingest.py
python tests/browser_smoke.py
```

`browser_mcp_reports.py` starter den faktiske WSGI-app med midlertidig SQLite og syntetisk OAuth-klient, registrerer klienten, gennemfører rigtig browserlogin og samtykke, udveksler engangskode med PKCE og kalder initialize/tools-list/send/read. Derefter kontrolleres Testdata-visning på 390 px og en tom driftsindbakke. Ingen Pluto-kald foretages. Screenshots `/tmp/escape-mcp-consent-test.png` og `/tmp/escape-mcp-report-test.png` er lokale testartefakter.

HTTP-tests dækker forkert callback/resource/klient/PKCE, kodereplay, refreshrotation og genbrug, udløb, Origin, CSRF, scopes, tilbagekaldelse, dubletter, datapartitioner og ejerskab. Dette erstatter ikke en virkelig ChatGPT-kompatibilitetstest på webhotellet.

## Planlagte ChatGPT-opgaver: separat næste milepæl

En manuel samtales værktøjsadgang beviser ikke, at planlagte ChatGPT-opgaver kan bruge samme app, OAuth-forbindelse eller skriveværktøj. Der er ikke oprettet en opgave i denne ændring. Før automatisk levering loves, kræves en understøttet kontofunktion og en planlagt test med `is_test:true`, som leverer uden manuel værktøjsgodkendelse **hvis platformen tillader det**, efterfulgt af kontrol i ESCAPE. Sikkerhedsgodkendelser må ikke omgås.

Indtil dette er verificeret, er anvendelsen en manuelt startet ChatGPT-analyse med mulig værktøjslevering efter godkendelse. MCP-serveren kalder ikke en AI-tjeneste og medfører ingen ekstra AI-motorbetaling, men ChatGPTs plan-/kvoteregler er stadig platformens egne.

## Find manglende callback uden at gætte

Hvis `ESCAPE_MCP_REDIRECT_URIS` mangler, afviser serveren registrering. En afvist registrering gemmer nu en begrænset diagnosticering: højst fem observerede HTTPS-callbacks uden query/fragment på de præcise værter chatgpt.com eller chat.openai.com, samt øvrige værtsnavne uden stier. Dette er ubetroede forespørgselsdata og ikke bevis for afsenderidentitet; intet tillades automatisk. Tokens, hemmeligheder, queryværdier og request bodies gemmes ikke.

Efter installation: Start et nyt Tilslut-forsøg i ChatGPT. Åbn derpå ESCAPE som administrator → Forbindelser → Rapportforbindelser → Vis rapportforbindelser. Den seneste afviste callback vises sammen med tidspunkt. Sammenhold den med dit netop startede forsøg og klientens opsætning. Tilføj kun den verificerede, præcise adresse som `ESCAPE_MCP_REDIRECT_URIS` i cPanel, gem og genstart. Forsøg derefter igen. Hvis callbacken ikke kan verificeres, skal den afklares før godkendelse. Andre brugere kan ikke se registreringsdiagnosticeringen.

## Rapportvisning v2
V2 tilføjer struktureret Intelligence-rapport, kilder, kandidathistorik, dokumenteret konsolidering og uddybende analysepakker. Eksisterende v1-kald og OAuth-forbindelser bevares. Se [REPORT_V2.md](REPORT_V2.md). Brugerbekræftet manuel tovejslevering er dokumenteret dér; det ændrer ikke status for planlagte opgaver.


## Rapportvalidering fra server 2.2.0

Se [REPORT_VALIDATION.md](REPORT_VALIDATION.md). `validate_report` er et separat læseværktøj med samme inputskema og centrale validator som `send_report`. Det er tilgængeligt med reports:read eller reports:write; send_report kræver fortsat reports:write. Genindlæs ESCAPE-pluginets værktøjer efter installation. Ingen ændring af OAuth-scopes eller nøgler. Valideringskald bruger afgrænset ratebegrænsning i proceshukommelsen (pr. Passenger-worker), så selv transportens tællere ikke skriver til SQLite. Øvrige MCP-kald beholder deres fælles databasetællere og har også procesbeskyttelse.


## Leveringsdiagnostik fra 2.2.1

Se [MCP_DELIVERY.md](MCP_DELIVERY.md). send_report bevarer skriveklassifikation og rettigheder. Kvitteringer har nu delivery_trace_id og X-ESCAPE-Request-Id; privat Passenger-log kan skelne modtagelse, lagring, dublet og afvisning uden rapporttekst eller tokens. Bevar eksisterende timekørsel. En OpenAI-sikkerhedsafgørelse kan ikke forklares eller omgås af servermetadata.

## HOT WATCH Engine 2.5.0

Nye, separat godkendte scopes: `hotwatch:read` og `hotwatch:manage`. Eksisterende rapportscopes giver ikke automatisk motoradgang. `start_hot_watch`, `control_hot_watch` og `get_hot_watch_engine` er additive motorværktøjer; `kind=candidate` henter den permanente statusprojektion. Se [API og faseafgrænsning](HOTWATCH_ENGINE.md) og [kandidatstatus](CANDIDATE_STATUS_MODEL.md). Ingen af værktøjerne opretter faktiske handler.
