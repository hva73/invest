# Implementeringsplan — endelig design- og statusspecifikation v1.0

Grundlag: [godkendt specifikation](DESIGN_STATUS_SPEC_V1_DA.md). Arbejdsbranch: `codex/design-review-wip`. Dato: 3. november 2026.

**Grænse:** Lokalt udviklings-/testarbejde er adskilt fra release, installation og produktionsændringer. Der laves ingen installation, release, brokerhandling, ændring af aktiv strategi eller scheduler. Planen ændrer ikke rapportpayloads og er ikke en påstand om, at hele redesignets tests allerede består.

## 1. Konkrete afvigelser i eksisterende kode

| ID | Nuværende kode/data | Krævet adfærd | Løsning / praktisk begrænsning |
|---|---|---|---|
| A01 | Overblikkets `PositionUI.panel` tager udgangspunkt i positionsposter i hovedrapporten. Faktiske Pluto-snapshots vises separat. | Alle faktiske Pluto-positioner, også dem uden analyse. | Ny læseprojektion fra ejede Pluto-depoter; rapportanalyse kobles på, når depot- og asset-identitet kan eftervises. Original rapportvisning bevares som rapportøjebliksbillede. |
| A02 | Rapportens portfolio_id er et afsender-ID. Det er ikke nødvendigvis Plutos external_id eller appens lokale numeriske depot-ID. | Sikker identitetskobling; ticker/navn alene er utilstrækkeligt. | Valgfri, streng brokerreference i nye rapporter eller eksplicit servermapping; kontroller ejerskab og enhedstype. Gamle rapporter accepteres uændret, men kan stå som ikke afstemt. |
| A03 | `market_data.normalized()` sætter previous_close til null. dailyChange og dailyChangePercent leveres uden dokumenteret official-close-tid/grundlag. | Dagsændring skal have dokumenteret sammenligning med officiel lukkekurs. | Bekræft leverandørens definition eller indlæs verificeret close med kilde, valuta, session og tid. Indtil da: ingen påstand om verificeret close-reference; ukendt godkendt sammenligning vises neutralt. Udled ikke official close ved at regne baglæns fra en procent. |
| A04 | Kontotal indeholder profitLoss uden dokumenteret afkastperiode. Rapportsammenligning er rå værdiændring. | Dagens depotresultat er pengestrømskorrigeret. | Kræver sammenlignelige værditidspunkter, korrekt åbningsgrundlag og fuldstændige ind-/udbetalinger/overførsler. Ellers `—`, med forklaring. Eksisterende profitLoss må kun vises som særskilt kildetal med ukendt periode. |
| A05 | Seneste kurs og depotsnapshot overskrives i cache. Der er ingen generel, dokumenteret pristype/markedsfase på alle observationer. | Siden-sidst på to kompatible observationer. | Separat append-only observationslager med event/receive time og sammenligningsnøgle. Deduplikér gentagne source-observationer. Sammenligning afvises ved manglende/ændret valuta, feed, venue, session, pristype eller corporate-action-basis. Ingen tickerkobling på tværs af aktiver. |
| A06 | `freshness()` i app.js bruger generelle 10/30-minutgrænser. Ingen verificeret børskalender er tilknyttet. | Quote 60s, snapshot 300s, analyse 24h samt sessions-/helligdagsregler. | Central visningspolitik med datatype, kilde, session og eksplicit markedskalender. Markedsstatus UNKNOWN forbliver ukendt; ikke beregne weekendlukning for krypto. Ingen ændring af aktiv motorstrategi eller pollingbudget. |
| A07 | Snapshot har original valuta og undertiden valueInPortfolioCurrency/unrealisedPnLInPortfolioCurrency; der er ingen generel verificeret valutakurs med tid. | DKK hvor dokumenterbart; ellers original valuta. | Brug et eksplicit DKK-beløb fra korrekt brokerfelt eller dokumenteret FX med basis/tid. EUR/USD må ikke omregnes med en antaget kurs. P/L-procent kræver sammenligneligt ikke-nul kostgrundlag. |
| A08 | Pluto-positionsadapteren bevarer asset_id, men ikke en generelt dokumenteret broker-position/lots-ID. Depotets holdings-scope er ikke altid eksplicit. | Stabil position, ingen root/Collection-dubletter og ingen falsk lotkobling. | Bevar verificerede provider-ID'er, når kontrakten leverer dem. Depot+asset kan kun bruges som unik aggregeret position, når entydigheden er verificeret. Uklar identitet giver afstemningsadvarsel, ikke skjult post eller automatisk sammenlægning. Collection-værdirækker tælles ikke som ekstra individuelle aktier. |
| A09 | Terminale motorsessioner returneres sammen med andre; rapportmålinger og WAITING_TRIGGER er ikke grupperet efter v1.0. | Aktive, pause, advarsler, afventer og historik særskilt. | Visningsgrupper læses fra dokumenteret state. ERROR/DEGRADED synlige som advarsler; COMPLETED/EXPIRED kun i historie. Intet ændres i sessionshistorik eller kontrolflow. |
| A10 | Ordreoversigten består af flere kilder med forskellig status/komplethed. INACTIVE-læsning er afgrænset. | Aktive/uafklarede og seneste terminale hændelser 24h. | Fælles displayprojektion pr. ejer+depot+ordre-ID med oprindelig status- og fyldningstid. Ukendt statustid må ikke tælles som netop afsluttet. ACCEPTED er ikke et fill-bevis; delvist fyldt CANCELLED beholder udført antal. Ingen ændring af brokerordrer. |
| A11 | Journalen er opdelt i rapportposter, lokale beslutninger, brokerforslag og motorhændelser; forskellige begrænsede historikvinduer. | Samlet læsetidslinje, syv dage, kilde/type/filter og gamle uafklarede kritiske hændelser. | Federeret læseprojektion med stabile kilde-ID'er, pagination, verificeringsmærke og dokumenteret dækning. Gamle kritiske poster kræver en eksplicit løst/uafklaret-tilstand; de må ikke vurderes løst ud fra alder alene. |
| A12 | Positions- og kontoværdier kan farves efter rapport-P/L/profitLoss. Små hjælpetekster og store gentagne paneler. | Absolutte værdier neutrale; farvede ændringer/resultater, kompakte rækker. | Fælles finansielle visningskomponenter og visuelt hierarki. Bevar talpræcision, datagrundlag, klikadgang og fokus/touchmål. |

Ingen af A03/A04/A06/A07 kan løses ved blot at udfylde rapportens tomme felter med AI-genererede værdier. Der bestilles ingen nye datatjenester.

## 2. Faser og kontrolpunkter

### Fase 1 — datakorrekthed og statusfiltrering

**Filer:** ny `dashboard_projection.py` og `display_policy.py`; additive integrationer i app.py, portfolio_data.py, candidate_lifecycle.py, report_ingest.py og hotwatch_api.py efter behov.

- Byg én autoritativ læseprojektion fra aktive ejede Pluto-enheder, med oprindelige kildetider og eksplicit snapshot-komplethed.
- Bevar sidst kendte positioner ved læsefejl, marker dem ikke aktuelt verificerede. Udeladelse i en rapport ændrer ikke faktisk ejerskab.
- Kobling til analyse kræver præcis depotreference og asset_id. Ved konflikt beholdes brokerfakta, rapportudsagn og advarsel separat.
- Implementér statusmatricen nedenfor som displaypolitik, ikke som omskrivning af lifecycle eller brokerstatus.
- Kritiske poster skal være tilgængelige uafhængigt af almindelige standardfiltre. Filteroptællinger og viste poster beregnes fra samme delmængde.
- Test ejer-/testisolation, samme ticker i to depoter, nul/ukendt antal, uafklarede poster og genaktivering uden tab af historik.

**Kontrolpunkt:** T06–T09, T11–T16, T25–T28. Dele, der afhænger af nye kilder, skal være eksplicit ukendte/afgrænsede, ikke fejlagtigt grønne.

### Fase 2 — finansielle komponenter og friskhed

**Filer:** ny `static/financial-ui.js` og `static/display-policy.js`, eventuelt backend `market_context.py`; tilpas market_data.py, asset_quotes.py, static/app.js og static/style.css. Føj nye runtimefiler til installerens allowlist før eventuel release.

- Ét format for beløb/kurser/antal/procenter med eksplicit felttype; neutrale kurser/værdier/kontanter.
- Skil total urealiseret P/L, dagsændring og siden-sidst ad i både tekst, reference og datatid.
- Giv hver beregning provenance: kilde, aktuel observation, reference, valuta/FX, markedsfase og verificeringsstatus.
- Tidsregler: aktivt marked quote >60s, snapshot >300s, analyse >24h. Præcis grænse testes før/på/efter. Dokumenteret closed-session-dækning kræves før lukket marked gør en gammel quote legitim.
- Ukendt kalender/venue eller forsinkelse bliver ukendt/mærket; hentetid erstatter aldrig event time.
- Bevar EODHD/Pluto-adaptergulve, backoff og aktive strategiversioner. Hurtigere farveopdatering er ikke et hurtigere markedsfeed.

**Kontrolpunkt:** T01–T05, T13, T17–T22. T22 kræver konkrete venuekalendere med verificerede fixture-datoer, også tidlig lukning og DST, samt 24/7-aktiv som modprøve.

### Fase 3 — beholdninger og Overblik

**Filer:** static/app.js, position-ui.js, overview-ui.js, style.css og eventuelt ny dashboard-ui.js. Eksisterende PositionUI.report bevarer historiske rapportvisninger; aktuel beholdningsliste får selvstændig brokerbaseret model.

- Overblik følger specifikationens fem hovedafsnit. Fjern kontodubletter fra standardvisning; rapporttal åbnes sekundært.
- Alle faktiske positioner i kompakt tabel på desktop og trelinjet mobilrække. Vis seneste kurs/datatid uden lang analyse.
- Desktopfelter og mobillinjer følger B2; lang tekst/kilder/risiko/historik ligger i detaljevisning.
- Sortering: kritisk handling → depot/Collection → dokumenteret sammenlignelig værdi. Ved forskellige valutaer uden DKK-basis må værdier ikke numerisk rangordnes som om valutaerne var ens; brug valuta-undergrupper og tydelig manglende DKK-basis.
- Gruppér navigation visuelt uden at fjerne de otte funktioner. Datakvalitetsstatus skal være kort og tydelig.

**Kontrolpunkt:** T03–T07, T11–T13, T17, T23–T24. Dokumentér faktisk rækkehøjde, tekstkontrast, tastaturfokus og læsbarhed frem for alene at tælle pixels.

### Fase 4 — Radar, HOT WATCH og Handelsmotor

**Filer:** static/candidate-ui.js, report-ui.js, intel-ui.js, engine-ui.js og trade-ui.js.

- Implementér nye fund/under analyse, aktiv HOT WATCH og sammenklappet WAITING_TRIGGER med antal, prioritet, trigger og deadline.
- Adskil motorens signal, rapportbeslutning og faktisk ordreudførelse konsekvent.
- Prioritér faktiske åbne/uafklarede ordrer og godkendelser. Afsluttede hændelser vises højst 24h i seneste hændelser, men forsvinder ikke fra historik.
- Kontroller alle kombinationer af livscyklus- og opmærksomhedsfilter. Terminale poster må kun ses i en eksplicit valgt historiegruppe.
- ERROR/DEGRADED bliver synlige driftsadvarsler. PAUSED separat. Historiske rapportmålinger sammenfoldes.

**Kontrolpunkt:** T07–T10, T14–T16, T27–T28.

### Fase 5 — Journal, Analyser og Forbindelser

**Filer:** ny journal_projection.py ved behov, static/report-ui.js, trade-ui.js, intel-ui.js og app.js.

- Samlet læsetidslinje, standard syv dage og gamle uafklarede kritiske hændelser. Filtrér kilde/type/periode, paginér uden sletning.
- Rapportresumé og indholdsfortegnelse først. Originale rapporter kan åbnes komplet med deres oprindelige poster og timestamps.
- Statuskort viser observeret Pluto/EODHD/MCP/serviceadgang, tidspunkt og konkrete fejl. Konfigureret nøgle eller oplyst abonnement er ikke i sig selv verificeret endpointadgang.
- Tekniske diagnoser, tidligere registreringsfejl og historiske data ligger i detaljer; ingen hemmeligheder i frontend eller screenshots.

**Kontrolpunkt:** T15–T16, T24–T28 plus ægte syvdages-/kritisk-undtagelsesprøver.

### Fase 6 — samlet test og releaseforberedelse

- Kør hele Python-/JS-regressionen og alle relevante browserforløb. Kør T01–T28 som selvstændige scenarier; ingen samlet PASS, hvis en enkelt kilde-/kalenderafhængig case er ukendt.
- Skærmbilleder 390/1440 px, layoutkontrol ved alle ni angivne bredder; suppler 320 px med lange navne, 12+ positioner og små kryptobeløb.
- Verificér gammel v1/v2-validering, uændrede rapportdigests, idempotens og MCP 2.5.1 kandidat-readback.
- Dokumentér ændrede filer/tabeller, nødvendige kilder/rettigheder, faktiske testresultater, resterende afvigelser og rollback.
- **Stop før release og installation.** En samlet installationspakke/release må først publiceres efter separat godkendelse. Arbejdsbackup på wip-branch er ikke en release.

## 3. Statusmatrix for implementeringen

| Objekt/status | Standardplacering | Historik / undtagelser |
|---|---|---|
| DISCOVERED / ANALYZING | Radar nye fund / under analyse | Ikke standard på Overblik |
| HOT_WATCH | Aktiv HOT WATCH | Overblik ved dokumenteret væsentlig ændring |
| WAITING_TRIGGER | Sammenklappet afventergruppe | Antal, prioritet, trigger, deadline; kun relevant udløst trigger på Overblik |
| BUY_SIGNAL | Radar, HOT WATCH og gyldigt forslag | Overblik; signal er ikke en ordre |
| ORDER_PENDING | Handelsmotor og Overblik | Verificér separat faktisk brokerstatus |
| POSITION_OPEN | Faktiske beholdninger efter Pluto-verifikation | Synlig på Overblik, også uden analyse |
| EXIT_WATCH | Beholdninger/HOT WATCH | Relevant risiko på Overblik |
| CLOSED / ARCHIVED | Historik / arkiv | Kan ikke genåbnes af sekundært filter |
| FRAVÆLG uden ejerskab/aktiv ordre/ny dokumenteret trigger | Skjult fra aktive kandidater | Historik bevares |
| FRAVÆLG med faktisk position | Positionen bevares i beholdninger | Beslutning for nye køb vises separat |
| PROPOSED / AWAITING_APPROVAL | Forslag / godkendelser | Afventer godkendelse på Overblik |
| SUBMITTED / ACCEPTED / PARTIALLY_FILLED | Aktive/uafklarede ordrer | ACCEPTED er ikke FILLED; delvis position bevares |
| FILLED / CANCELLED | Seneste hændelser 24h og journal | Alder fra faktisk status-/hændelsestid; ikke hentetid |
| REJECTED | Journal og relevant advarsel | Afvisningen ændrer ikke tidligere fyldninger |
| EXPIRED ordre | Historik | Ingen automatisk ændring af brokerordre |
| UNKNOWN ordre | Uafklaret gruppe | Aldrig automatisk afsluttet ud fra alder |
| CREATED / VALIDATING / ACTIVE session | Afventer opstart / under opstart / aktiv | Ingen påstand om aktiv service alene ved CREATED |
| PAUSED session | Pausegruppe | Historik bevares |
| DEGRADED / ERROR session | Synlig driftsadvarsel / kritisk driftsadvarsel | Fejl skjules ikke ved gamle data |
| EXPIRED / COMPLETED session | Historik | Ingen aktiv overvågningsbadge |

## 4. Feltkontrakt og bagudkompatibilitet

Fremtidig dashboardprojektion er et nyt læseformat ved siden af eksisterende rapportformat; det skal ikke sendes gennem send_report. Foreslåede nøglegrupper:

- `identity`: lokal ejer-/depotreference, verificeret providerreference, asset_id, stabil positions-/forløbsreference og eventuel koblingsadvarsel.
- `broker_facts`: antal, faktisk ordre-/positionsstatus, seneste verificerede snapshot og komplethed.
- `market`: pris og originalvaluta, event/receive time, venue/session, feedtype/forsinkelse og datakvalitet.
- `comparisons`: dag, siden sidst, P/L og depotresultat med hvert sit grundlag, reference, valuta og tidsstempler.
- `assessment`: uændret rapportanbefaling, grundlag, assessed_at, deadline/trigger og friskhed.
- `missing`: afgrænsede årsager NOT_PROVIDED/NOT_FETCHED/STALE/SOURCE_ERROR/NOT_APPLICABLE; aldrig økonomiske null→0-erstatninger.

Eksisterende report schema_version 2 accepteres fortsat. Valgfri brokerreference, sammenligningsmetadata og manglende-dataårsager til nye rapporter indføres kun, hvor det faktisk er nødvendigt; de skal defineres strengt, dokumenteres og indgå i samme fælles validering. Ingen nye felter føjes ukritisk til gamle gemte rapporter, og en afsenders `verified`-markering giver ikke automatisk brokerautoritet.

Ny observations-/referencehistorik er append-only med ejer/testkategori, deduplikeringsnøgle, kilde og oprindelige tider. Ny journaldisplay må ikke overskrive gamle journalrækker. Opgradering skal kunne læse legacy-rækker uden nye obligatoriske kolonner. Metadata/backfill må ikke opfinde gamle kurs-, fill- eller FX-observationer.

## 5. Datakilder og tekniske punkter, der skal dokumenteres

1. Faktisk dokumentation for Plutos dailyChange-reference og market phase; current previous_close er null.
2. Dækning af pengestrømme og historiske kontoværdier før et dagsresultat kan beregnes.
3. Depot-/Collection-scope i root-holdings samt stabil brokerpositionsidentitet, hvis samme aktiv har flere poster.
4. Mulighed for eksakt rapportdepot→Pluto-reference uden ticker-/navnegæt.
5. Verificeret valutagrundlag med tid; broker-DKK-felt er ikke det samme som en frit genanvendelig FX-kurs.
6. Valg og versionskilde for kalender pr. venue inkl. halvdag, DST, helligdag og 24/7-marked. UNKNOWN skal være ærlig fallback.
7. Definition af “væsentlig HOT WATCH-ændring”/“relevant trigger”: brug kun eksplicit event/regeldokumentation; ingen skjult ny tærskel.
8. Hvordan kritiske hændelser bliver eksplicit løst/kvitteret. Læst er ikke løst; nye journalvisninger må ikke afgøre dette ud fra alder.
9. Aktuel EODHD Active Trader-adgang/feedforsinkelse er stadig ikke verificeret; ingen nye abonnementer eller køb.

Punkterne er datakrav/afvigelser, ikke en begrundelse for at udfylde tomme værdier. Visningsarbejdet kan testes med tydeligt syntetiske referencer imens.

## 6. Release- og rollbackplan — ikke godkendelse til at udføre den

- Hold arbejdet på `codex/design-review-wip`; den ventende MCP 2.5.1-rettelse følger med den kommende samlede kodebase.
- Før en senere installation: konsistent privat SQLite-backup, kodebackup, dokumenteret migrationsversion og validering af installerens filmanifest; stop separat HOT WATCH-service og app under opdatering.
- Additive tabeller/kolonner og optional felter; ingen datakassering. Test opgradering fra nuværende v2.2 og ny database, inklusive rollback til sikker kode med de nye felter til stede.
- Ved fejl: stop processer, gendan kompatibel kode og start kontrolleret. Gendan ikke en gammel database oven i nyere journal-/handelsdata uden særskilt afstemning; en tidsmæssigt sammenhængende snapshot-restore er en anden operation end simpel kode-rollback.
- Efter godkendt installation: kun read-only smoke/readback først, ingen automatiske handler. Kontrollér ejerskab, beholdningsantal, root/AI-værdi, datatider og journalintegritet. Udviklingsmiljøets tests er ikke live-datakildegodkendelse.
