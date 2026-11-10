# Forslag fra ESCAPE til godkendelse i Pluto

> **Aktuel læsevejledning (10. november 2026):** Se [masterkontrakten](ESCAPE_MASTER_CONTRACT.md) for gældende depotmandat og forskellen mellem vurdering, forslag, ordre og faktisk fill.

Plutos værktøjsbeskrivelser modtaget 2. november 2026 siger udtrykkeligt, at `propose_orders` opretter et forslag. Ingen ordre placeres og ingen penge reserveres ved dette kald. Brugeren ser en ny kurs og godkender i Pluto-appen, før rigtige ordrer oprettes. Der findes ifølge den modtagne beskrivelse intet værktøj til direkte ordreafsendelse. ESCAPE omgår ikke denne godkendelse.

## Forløbet

1. Åbn **Handelsmotor** og vælg en aktuel KØB/SÆLG-kandidat fra en v2-driftsrapport. Senere kandidatopdateringer indgår; et ældre signal kan ikke sendes, når den aktuelle vurdering har ændret sig. Testdata og historiske rapporter kan ikke sendes.
2. Vælg en aktiv Pluto-enhed, handling og afregningsvaluta. En direkte aktivhandel kræver en hovedportefølje. En Collection-handling vedrører hele Collectionen, ikke kun rapportens ticker.
3. Ved direkte aktiver: søg hos Pluto og vælg det konkrete aktiv ud fra navn, ISIN og valuta. Vælg selv størrelse, ordretype og gyldighed. Beløb og antal udledes ikke af rapportens fritekst. Salg kræver antal; beløbskøb afhænger af Plutos understøttelse af brøkandele. LIMIT/STOP_LIMIT kræver limitpris, STOP/STOP_LIMIT kræver stoppris, i aktivets valuta og med højst to decimaler. MARKET kan kun bruge DAY. Udvidet handelstid er ikke aktiveret.
4. **Hent Pluto-estimat** kontrollerer den aktuelle porteføljeadgang og henter konto-/ordreobservationer, aktivdetaljer og et estimat. Dette opretter ingen forslag hos Pluto. Der vises op til 50 aktive ordreobservationer; oversigten hævdes ikke fuldstændig, og der opfindes ingen afstemning af købekraft eller reservationer.
5. Gennemgå konto, aktiv/Collection, størrelse, valuta, ordretype, estimat og observationerne. Estimatet kan bruges til afsendelse i højst to minutter. Ændringer i formularen fjerner den viste gennemgang, så der skal hentes et nyt estimat.
6. Bekræft gennemgangen og vælg **Send forslag til Pluto**. Den gemte og gennemgåede ordre bruges; nye klientfelter kan ikke udskifte payloaden ved afsendelsen. Aktuel adgang, kilde og estimatets gyldighed kontrolleres igen.
7. Åbn Pluto-appen, og gennemgå forslaget og Plutos nye kurs før endelig godkendelse. ESCAPE kan hente forslagsstatus med den returnerede `orderIntentId`. `accepted` betyder godkendt forslag, ikke dokumenteret udført handel. Faktiske ordrer/beholdninger følges fortsat via Plutos læseopslag.

Der findes separate handlinger for direkte køb/salg, køb af en ejet Collection for et beløb og salg af en procentdel af en ejet Collection. Andre Collection-handlinger (nye allokeringer, rebalancering, reinvestering og kontantflytning) er ikke tilsluttet denne version. Rapportens stop-/målplan opretter ikke automatisk yderligere beskyttelsesordrer.

## Afgrænsning og sporbarhed

`trade_service.py` tilbyder kun faste læse-/forslagsfunktioner. Der findes intet endpoint til frie MCP-kommandoer, direkte eksekvering, automatisk godkendelse eller annullering. ChatGPT-rapportforbindelsen får ingen brokeradgang. Alle HTTP-handlinger kræver app-session, CSRF og eget dataejerskab.

`pluto_trade_contract.json` indeholder strukturelle inputkontrakter udtrukket af brugerens modtagne værktøjsliste. Ingen kontoidentiteter, tokens eller den fulde indsatte tekst er medtaget. Live-kontrakt og readOnlyHint skal matche; ved ændring blokeres handlingen. Eksterne beskrivelser bruges ikke som instruktioner, og der tilføjes ingen nye OAuth-scopes eller formodede tilladelser. Hvis Pluto kræver en anden tilladelse, skal den dokumenteres; kodeopdateringen giver den ikke automatisk.

Appens forslag gemmer kilde, kandidat-ID, valgt lokal Pluto-enhed, nøjagtige providerargumenter, estimat, gennemgangsnøgle, reference og svar. Appens forslagsjournal holdes adskilt fra rapportobservationer og tidligere lokale hypotetiske beregninger. De gamle beregninger ligger foldet sammen og sender stadig intet til Pluto.

Dobbelttryk og samtidige sendeforsøg kan højst kalde forslagsværktøjet én gang. Afsendelse markeres atomisk før netværket. Timeout, tabt svar eller ukendt svarformat giver `uncertain`; identiske forslag genafsendes ikke automatisk, heller ikke fra en gentaget rapport. Et afsendt forslag, hvor udførelsen ikke er afklaret, kan blokere et nyt identisk forslag: kontrollér det i Pluto frem for at forsøge at omgå blokeringen. Kilde, tilladelse eller kontraktændringer før afsendelse stopper kaldet.

## Validering og første installation

Testene bruger midlertidige databaser og simulerede brokersvar; de kontakter ikke Pluto og sender ingen rigtige forslag. De dækker køb/salg, Collection-adskillelse, udløb, kontraktændring, ændret adgang, timeout, manglende reference, gentagne rapporter, samtidige klik, CSRF, brugeradskillelse, formularændringer, journal og mobilbredder 320–1440 px.

Værktøjslisten dokumenterer inputfelterne, men indeholder ikke outputskemaer. Søgeresultater understøtter entydige lister i root, `assets`, `results` eller `items`; aktivdetaljer skal returnere matchende `id`/`assetId` i root eller `asset`. Forslagsreferencen forventes som `orderIntentId` i root, sådan som værktøjsbeskrivelsen angiver. Ukendte formater blokeres eller markeres uafklarede; de må ikke gættes. Estimat og provider-svar vises som originaldata, indtil de konkrete produktionsformater er bekræftet.

Installer frisk ZIP med `apply_update.py` under fx `escape_app/opdatering/handelsforslag/`. Der er ingen nye Python-afhængigheder eller plugin-skemaændringer. Start appen og genindlæs siden. Første produktionskontrol bør være søgning og **Hent Pluto-estimat**; det validerer de faktiske svar uden at oprette et forslag. En reel afsendelse kræver derefter brugerens eksplicitte gennemgang og endelig godkendelse i Pluto.


## Test uden KØB/SÆLG-signal

**Handelsmotor → Test Pluto-forbindelsen** er tilgængelig, selv når rapporterne kun har AFVENT, OVERVÅG eller BEHOLD. Søg efter aktivet, vælg en hovedportefølje, testretning, valuta, størrelse, ordretype og gyldighed, og vælg **Hent testestimat**. Ved tom forslagsliste er testsektionen allerede foldet ud.

`POST /api/trade/preview` bruger en separat læsevej uden rapportkrav. Den validerer brugerens aktive enhed og de samme tal- og ordretypefelter og kalder alene portefølje-, konto-, ordre-, aktiv- og estimatopslag. Den gemmer ingen brokerkladde, genererer ingen gennemgangsnøgle og returnerer intet forslags-ID. Testresultatet kan ikke sendes. `/trade/estimate` og `/trade/send` kræver fortsat et aktuelt KØB/SÆLG-signal og et gyldigt, gennemgået estimat som før. Session, CSRF og brugeradskillelse gælder også for testen.

Den nye browserprøve `browser_layout_preview.py` gennemfører et testestimat med kun et OVERVÅG-signal og kontrollerer, at ingen forslagsværktøjer er kaldt, og at forslagstabellen er tom. Testen dækker også alle syv hovedskærme og porteføljedetaljer ved 320–1920 pixels med lange navne, delvise/ukendte kildetider, forskellige valutaer og meget små kryptopriser.
