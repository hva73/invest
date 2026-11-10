# Komplet rapportlevering og fælles validering

> **Aktuel læsevejledning (10. november 2026):** Se [masterkontrakten](ESCAPE_MASTER_CONTRACT.md) for de gældende kodegrænser og forskellen mellem skemavaliditet og verificeret marked/broker.

## Fund og afgrænsning

Gennemgangen omfatter `mcp_reports.py`, `report_ingest.py`, `report_v2.py`, rapporttabellerne, import-API og automatiserede tests. Den faktiske afviste driftsrapport og OpenAI's interne sikkerhedsafgørelse er ikke tilgængelige i udviklingsmiljøet. Der er ikke sendt nogen rapport eller foretaget Pluto-opslag i produktion under arbejdet.

Konkrete fund før rettelsen:

- MCP's sammenflettede v1/v2-skema krævede kun fælles felter og kunne dermed annoncere strukturer som gyldige, selv om backend krævede alle felter i den valgte version, også nullable felter. Versionsbetingelser sikrer nu den eksakte struktur. `schema_version` er fortsat synligt som `[1,2]` for at undgå den tidligere v1-first-flattening.
- Backend stoppede ved første fejl. Objektfejl sagde blot, at felter ikke matchede, og MCP erstattede også referencer og ID-konflikter med en generisk besked.
- Nogle referencekontroller lå kun i gemmefunktionen. De er flyttet til den fælles validator og kan nu køres uden lagring, med samme ejer-/kategoriopslag.
- De eksisterende grænser er 80 kandidater, 150 kilder, 30 porteføljer, 150 positioner, 100 ordrer, 100 journalposter, 20 regioner og 256 KiB kanonisk v2-JSON. De oplyste 12 kandidater / 11 kilder / 4 regioner / 11 positioner / 15 ordrer overskrider ingen af disse antalgrænser. Store analyser kan stadig overskride tekst-/bytegrænser; det rapporteres konkret, og indholdet trunkeres aldrig.
- Rapportlagringen fjernede ikke kandidater. Reducerede inputrapporter kan blive accepteret og dermed blive den nyeste hovedrapport. Der gives nu en særskilt advarsel, hvis kandidater fra seneste hovedrapport mangler. Serveren ændrer ikke afsenderens valg automatisk.

Dette dokument påstår ikke, at et af fundene var årsagen til den konkrete OpenAI-blokering. En afvisning i OpenAI's sikkerhedstjek er ikke et valideringssvar fra ESCAPE. Adskil (1) klientens godkendelses-/sikkerhedsafgørelse, (2) klientens cachede værktøjsdefinition og inputkontrol, (3) HTTP/OAuth/transportfejl og (4) et faktisk `structuredContent.errors` fra ESCAPE. Uden ESCAPE-svar eller en bekræftet serveranmodning kan serverens skema ikke udpeges som årsag. `is_test:true` ændrer kun kategori; `send_report` er stadig et skriveværktøj og kan stadig kræve klientgodkendelse. `validate_report` annonceres korrekt som read-only, men det er ingen garanti for OpenAI-klientens godkendelse. Ingen sikkerhedstjek omgås.

## Fælles kontrakt

`report_validation.py` er den centrale validator. V2's feltdefinition ligger fortsat i `report_v2.SCHEMA`; v1's skema ligger i `report_validation.schema_v1`. Versionsbestemte JSON Schema-betingelser og backend bruger disse samme definitioner. Referencer, beløbsrelationer, verifikationskrav og databasekontekst kontrolleres desuden centralt. Et rent JSON Schema kan ikke kontrollere en anden rapports eksistens på en bestemt konto.

Ingen rapportfelter eller enum-værdier er tilføjet, og ingen normale antalgrænser er sænket. Eksisterende v1/v2-eksempler består. Alle oprindelige rapporter forbliver uændrede.

| Indhold | Korrekt form |
| --- | --- |
| Ukendt pris/omkostning | Hele money-feltet er `null`, fx `price:null`, ikke `{amount:null,currency:null}` |
| Kendt beløb | `{amount:"125.50",currency:"DKK"}`; beløb er decimalstreng, ikke JSON-tal |
| Ukendt antal/volumen | `null`; kendt antal/volumen er ikke-negativ decimalstreng |
| Ukendt marked | price/volume/spread/fees er null ved verification unknown/unverified |
| Nullable felter | Skal stadig være til stede; udeladt felt er ikke det samme som null |
| Tider | RFC 3339 med eksplicit tidszone, fx `2026-11-02T12:00:00+01:00` eller `Z` |
| Stabile ID'er | 1–100 tegn i `A–Z a–z 0–9 _ . : -`; entydige i hver objekttype |
| Ekstra felter/enums | Afvises med præcis sti; ukendte data må ikke smugles ind under nye felter |

Kandidater kan have verificeret handelsbarhed og samtidig ukendt pris/volumen. Handelsbarhedsflaget kontrollerer afsenderens kilde/tid, ikke Pluto. Kendte markedsværdier kræver verificerede kildehenvisninger og observationstid. Markedsvalutaer skal stemme med money-felterne. Eksisterende regler mod dobbelttælling af Collections og hovedporteføljer bevares.

Kildehenvisninger kontrolleres på alle niveauer, inklusive katalysatorer og regioner. Positioner/ordrer skal referere til porteføljer i rapporten. Kandidatreferencer kan pege på samme rapport eller eksisterende kandidathistorik på samme konto og i samme kategori. Journalens position-/ordrehenvisninger skal findes i rapporten og må ikke modsige et eksplicit kandidat-ID på det refererede objekt. Dublerede ID'er og dublerede kildehenvisninger rapporteres. Genbrug af kandidat-ID med en anden ticker udløser en advarsel, da legitime tickerskift også findes; afsenderen skal sikre instrumentidentiteten. For uddybninger kontrolleres `analysis_for` mod originalrapport og kandidat på samme konto og i samme kategori.

## validate_report

Argumentet er den komplette rapport direkte, uden wrapper, præcis som `send_report`. Ingen DB-rækker ændres—heller ikke MCP-transportens rate-tællere—og der er ingen Pluto-adgang. Læseværktøjet kan benyttes med `reports:read` eller `reports:write`; eksisterende scopes bevares. Transportens valideringsgrænser ligger i afgrænset proceshukommelse pr. worker; øvrige værktøjer beholder de fælles SQLite-grænser.

Resultatet indeholder altid `valid`, `schema_version`, `errors`, `warnings` og `counts`. Hver fejl har `path`, `code`, `message` og ved typefejl/manglende felt også `expected`. Alle uafhængige fund returneres i samme svar; et felt med forkert type undersøges ikke som en anden objekttype. Felternes indhold kopieres ikke ind i fejlteksten.

```json
{
  "valid": false,
  "schema_version": 2,
  "errors": [
    {"path":"candidates[9].market.currency","code":"invalid_type","message":"Expected string or null","expected":"string or null"},
    {"path":"candidates[10].source_ids[0]","code":"unknown_reference","message":"Expected source_id in this report"},
    {"path":"candidates[11].exit_plan","code":"required","message":"Required field; expected object","expected":"object"}
  ],
  "warnings": [],
  "counts": {"portfolios":2,"positions":11,"orders":15,"candidates":12,"sources":11,"regions":4}
}
```

En gennemført validering med ugyldig rapport har MCP `isError:false` og `valid:false`: selve testværktøjet lykkedes. `send_report` returnerer de samme konkrete valideringsfejl med MCP `isError:true`. Autorisation, ugyldig JSON og transportgrænser ligger før rapportvalideringen og kan derfor ikke altid give feltfejl/counts.

## send_report og lagring

Samme validator køres igen i insertionens transaktion, så historik-/kategoriopslag ikke erstattes af tillid til et tidligere validate-kald. Hele rapporten og kandidatlinks gemmes sammen, eller intet gemmes. Der er ingen filter-/normaliseringsvej, som fjerner objekter eller fylder manglende markedsdata ud.

Succes inkluderer de eksisterende `ok`, interne `id`, `duplicate` samt nye `valid:true`, `report_id`, `schema_version`, `counts` og `warnings`. Samme ID og identisk kanonisk indhold giver `duplicate:true` uden ekstra rapport/links. Samme ID med ændret indhold giver `report_id_conflict` (HTTP-import 409) og ændrer ikke originalen. Test og drift deler stadig ID-unikhed pr. bruger; kategorien kan ikke ændres ved genforsøg. Gamle rapporter kan ikke overskrives. Eksisterende visninger bruger fortsat genereringstid til at skelne ny analyse fra sent indlæst historik.

HTTP-import og Bearer-ingest bruger samme validator og giver nu også strukturerede valideringsfejl. Kanonisk rapportstørrelse har fortsat v1 16 KiB / v2 256 KiB. HTTP-import/ingest har desuden en rå bodygrænse på 256 KiB, MCP på 300 KiB inklusive envelope; indrykning kan derfor ramme transportgrænsen før den kanoniske grænse. Brug kompakt JSON ved store rapporter, aldrig fjern indhold for at få et misvisende acceptresultat.

## Leveringsforløb

1. Bevar hele den eksisterende hovedrapport, herunder de 9 kandidaters stabile ID'er og deres kilder. Tilføj BAVA, MRVL og LITE med egne stabile ID'er. Brug alene faktisk tilgængelige oplysninger; ukendte markedsfelter forbliver null.
2. Kald `validate_report` med den komplette 12-kandidatrapport. Ret alle errors og vurder warnings uden at reducere kandidat-/kildeindholdet.
3. Kald først `send_report` med samme komplette objekt, når levering er godkendt. En validering gemmer intet.
4. Kontrollér succes-kvitteringens report_id/version/counts og læs rapporten tilbage i den rigtige kategori. Et blokeret kald må ikke beskrives som leveret.

## Verifikation og installation

`tests/test_report_validation.py` dækker A (9 kandidater), B (12 inklusive BAVA/MRVL/LITE), C (null/ukendte markedsdata) og D (flere samtidige fejl), uændret lagring, dubletter, konflikter, kilde-/journalreferencer, ejer/testgrænser, analysis_for, advarsler og maksimumgrænser. Alle markedsdata i testene er syntetiske. De bekræfter ingen faktisk handelsbarhed eller dagens priser.

Skemaregressionen bruger en uafhængig Draft 2020-12-validator til test, mens produktionsvalidatoren fortsat er stdlib uden nye afhængigheder. `tests/test_mcp_reports.py` kontrollerer via lokal HTTP, at validate_report efterlader hele SQLite-indholdet identisk, at afvist send ikke gemmer deldata, og at importfejl har feltstier. Eksisterende OAuth/WSGI, v1/v2 og browserflows genkøres.

Updateren inkluderer den nye validator. Installer samlet frisk ZIP, start appen, genindlæs websiden og opdatér ESCAPE-pluginets værktøjer. Serverversion er **2.2.0**. Kontrollér validate_report, før den faktiske udvidede rapport leveres. Ingen produktionsrapport eller planlagte opgaver er ændret under udviklingen.
