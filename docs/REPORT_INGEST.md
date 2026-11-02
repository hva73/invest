# Rapportindbakke: minimal integrationstest

## Adresser

- Levering: `POST https://escape.nordic-response.dk/api/reports/ingest`
- Visning: log ind på `https://escape.nordic-response.dk/`, vælg **Rapporter & alarmer → Åbn rapportindbakke → Hent seneste rapport**.
- Autentificeret læsning: `GET /api/reports/latest` med normal brugersession. Hver bruger ser kun egne rapporter. Standardkaldet læser nu kun driftsrapporter; tilføj `?is_test=true` for testdata. I rapportindbakken vælges Testdata eksplicit.

Endpointet er først tilgængeligt på webhotellet, når denne kodeopdatering er installeret. Det er deaktiveret (HTTP 503), indtil begge servervariabler er konfigureret.

## Serveropsætning

Konfigurér følgende miljøvariabler i cPanels Python-app, og genstart appen:

- `ESCAPE_REPORT_INGEST_USER=owner` (eksisterende, aktiv modtagerkonto; afsenderen kan ikke vælge konto i JSON).
- `ESCAPE_REPORT_INGEST_KEY`: generér en ny tilfældig hemmelighed med mindst 32 tegn, anbefalet 48 tilfældige bytes kodet som URL-safe tekst. Brug f.eks. Python `secrets.token_urlsafe(48)` på serveren, og gem værdien som servermiljøvariabel. Undlad at sende værdien i chat, committe den, indsætte den i frontend eller føje den til URL'en.

Afsenderen sender `Authorization: Bearer <hemmelighed>` og `Content-Type: application/json` over HTTPS. Ingen login-cookie/CSRF kræves ved levering; Bearer-nøglen er autorisationen. Rotation: erstat servernøglen og afsenderens secret, genstart. Nøglen må ikke genbruges som loginadgangskode eller Pluto-token.

En ekstern afsender skal kunne læse samme secret fra sin egen beskyttede serverkonfiguration eller en understøttet integrations secret-lager. En hemmelig nøgle, som bogstaveligt kun findes hos modtageren, kan ikke autorisere et direkte Bearer-kald fra en anden tjeneste. Indsæt aldrig nøglen i en ChatGPT-opgaveprompt. Hvis en understøttet integration ikke kan gemme og sende den sikkert, er direkte levering ikke klar.

## JSON v1

Alle nedenstående felter er obligatoriske; lister må være tomme. Ekstra felter afvises. Beløb er decimalstrenge med punktum, ikke flydende JSON-tal. Tidsstemplet skal indeholde tidszone. `report_id` er et stabilt ID for denne rapport; genforsøg skal bruge samme ID og samme indhold. Højst 30 poster pr. liste og 16.384 bytes i hele requesten.

```json
{
  "schema_version": 1,
  "report_id": "manual-integration-test-001",
  "generated_at": "2026-11-01T20:00:00Z",
  "source": "Manuel integrationstest",
  "is_test": true,
  "portfolio_values": [
    {"name": "Testportefølje", "amount": "1000.00", "currency": "DKK", "includes_collections": true}
  ],
  "candidates": [
    {"symbol": "TEST", "market": "Testmarked", "reason": "Kun et syntetisk eksempel til test af rapportvisning."}
  ],
  "assessments": [
    {"subject": "Testkandidat", "assessment": "Dette er testdata, ikke en investeringsanbefaling."}
  ],
  "orders": [
    {"reference": "TEST-ORDER-001", "status": "TEST_ONLY", "note": "Ingen ordre er sendt til Pluto."}
  ]
}
```

Maskinlæsbar kopi: `examples/report-ingest-test.json` i repository/ZIP. Det er syntetiske data. Ingen kode summerer portefølje- og Collection-værdier eller omdanner rapportens ordrestatus til brokerhandlinger. `source` er afsenderens egen tekst, ikke bevis for en ChatGPT-afsender eller verificerede data.

## Manuel afsendelse fra en betroet server

Med nøgle og modtager-URL konfigureret som miljøvariabler på afsenderserveren kan eksempelrapporten sendes med Python (kræver ingen ekstra pakker):

```python
import json, os, urllib.request
from pathlib import Path
url = 'https://escape.nordic-response.dk/api/reports/ingest'
request = urllib.request.Request(
    url,
    data=Path('examples/report-ingest-test.json').read_bytes(),
    method='POST',
    headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + os.environ['ESCAPE_REPORT_INGEST_KEY']
    }
)
with urllib.request.urlopen(request, timeout=20) as response:
    print(response.status, json.loads(response.read()))
```

Send kun til den faste HTTPS-adresse. Eksempelkaldet er til betroet serverbrug; nøglen skal ikke ind i browserkonsollen. Forvent HTTP 201 `{"ok":true,"id":1,"duplicate":false}` (ID varierer). Gentagelse giver 200 og `duplicate:true`. Samme rapport-ID med ændret indhold giver 409. Manglende/forkert nøgle: 401. Ufuldstændig serverkonfiguration: 503. Forkert Content-Type: 415. For stor/tom body: 413. Ugyldig struktur: 400. Rapportindhold eller nøgle returneres ikke ved fejl.

## Gennemført lokal ende-til-ende-test

Kør `python tests/browser_report_ingest.py`. Testen genererer en midlertidig nøgle, starter appen mod en midlertidig SQLite-database, sender eksempelrapporten via HTTP uden cookies, logger ind i Chromium og åbner rapportindbakken ved 390 px. Den kontrollerer værdi, kandidat, vurdering, ordrestatus, testmarkering, fejlstatusser, dubletter, ejerskabsadskillelse og at ingen handelsforslag er oprettet. Screenshot: `/tmp/escape-report-ingest-test.png`.

Dette beviser modtagelse og visning i testmiljøet. Det er ikke en levering til produktionswebhotellet, og det beviser ikke, at ChatGPT Tasks kan foretage kaldet.

## Næste undersøgelse: ChatGPT-automatisering

Ingen understøttet afsenderintegration er endnu verificeret i denne session. ChatGPT Plus antages ikke at give API-adgang eller vilkårlige udgående HTTP-kald fra planlagte opgaver. Et almindeligt svar eller en notifikation fra en opgave er ikke en webhook-levering.

Før automatisk aktivering skal vi verificere den konkrete automatiserings understøttelse af eksterne handlinger i planlagte kørsler, sikker secret-opbevaring og autentifikation samt JSON-format, tidsplan, genforsøg og leveringskvittering. Hvis den konkrete platform ikke understøtter dette, kræves en separat afsender/connector; modtagerendpointet alene løser ikke det. Ingen ChatGPT-opgave eller Pluto-handel er oprettet eller ændret af denne integrationstest.

## Privat MCP-forbindelse
Den alternative OAuth-beskyttede MCP-rapportintegration er beskrevet i [MCP_REPORTS.md](MCP_REPORTS.md). Den genbruger disse rapportfunktioner og samme database. API-nøglen ovenfor bruges ikke til MCP. ChatGPT-kompatibilitet og planlagt levering er ikke verificeret i produktion.

## JSON v2
Endpointet accepterer nu også version 2 op til 256 KiB. V1-formatet og grænsen på 16 KiB bevares. Se [REPORT_V2.md](REPORT_V2.md) for fuld kontrakt, null-værdier, kildekrav, historik og uddybninger. Eksisterende gemte rapporter omskrives ikke.
