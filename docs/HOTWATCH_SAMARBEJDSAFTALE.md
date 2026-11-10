# ESCAPE × Trading Radar × HOT WATCH — samarbejds- og driftsaftale

> **Aktuel læsevejledning (10. november 2026):** Senere kontraktmatch og påviste versionsforskelle samles i [masterkontrakten](ESCAPE_MASTER_CONTRACT.md). Tekst om installation giver ikke selv tilladelse til at deploye en konkret version.

**Mål:** Færdiggør hele kæden: RADAR opdager → ESCAPE registrerer → HOT WATCH følger → RADAR revurderer → bruger beslutter eventuel handel. Dette er implementeringsordre til Codex, ikke en påstand om at funktionerne allerede er installeret.


## Gældende arbejdsordre og status — 8. november 2026

Dette afsnit præciserer og har forrang for tidligere formuleringer om straksinstallation og live-start. Udgangspunktet for gennemgangen er `69d1279` på `codex/escape-development`. Købskæden er **ikke færdig**, og der er ikke dokumenteret samlet LIVE PASS. Implementering og lokale tests fortsætter; resultatet gennemgås med Heine, før den samlede live-test startes. Ingen rigtige ordrer eller Pluto-handelsforslag under denne testfase.

### Praktisk prioritering — 9. november 2026

Fungerende overvågning og enkel betjening prioriteres over omfattende dokumentation. Hold kildehenvisninger, journal og status korte; ekstra administrativ dokumentation må ikke i sig selv forsinke overvågning af et verificeret instrument. Ubekræftede katalysatorer er uafklarede, ikke verificerede. Denne prioritering ændrer ikke datakvaliteten, signal- og risikokontrollerne eller brugerens handelsmandat; manglende fakta må ikke gættes. Gennemgå eksisterende skemaer og kode før ændring, og dokumentér den faktiske effekt med relevante tests.

### Handelsforløb og risikogrundlag

ChatGPT-kandidat → verificeret Pluto-instrument → automatisk HOT WATCH → Early Catalyst / dynamisk signal → bruger vælger beløb og sender forslaget → godkendelse i Pluto → verificeret beholdning → separat exit-watch.

- Discovery og EARLY WATCH må starte uden fuldt købsgrundlag. EARLY WATCH er observation og må ikke fremstå som et risikogodkendt køb.
- Brugeren vælger handelsbeløbet. Et konkret risikogodkendt køb kræver et dokumenteret handelsantal, stop i aktivets valuta, valutaomregning til DKK, gebyrer samt frisk depotværdi og eksponering. Det skal afklares og implementeres, hvordan beløbsvalg og et read-only Pluto-estimat indgår i dette grundlag, uden at skabe en cirkel, hvor beløbet kun kan vælges efter et allerede risikogodkendt signal.
- Manglende antal må ikke udledes fra et beløb og en udateret kurs. Manglende stop, valuta eller gebyr må ikke erstattes af standardgæt. Stopgrundlag skal have en udtrykkelig, dokumenteret metode eller brugerangivelse; et analytisk stop er ikke en placeret stopordre.
- De globale risikoregler bevares for alle strategier. Et nyt beløb eller ændret markeds-/depotgrundlag kræver ny kontrol; et tidligere godkendt signal må ikke godkende en anden handelsstørrelse.
- Vis særskilt: **signalbetingelser ikke opfyldt**, **risikogrænse overskredet** og **data mangler**. Hvis flere forhold gælder samtidig, skal de kunne ses samtidig. Lukket marked og for gamle data er ikke et svagt handelssignal.
- Kandidat-watch og exit-watch har separate sessioner. En accepteret ordreintention beviser ikke et fill. Kobling til kandidaten må ikke fremstilles som bevis for, at den observerede beholdning kom fra netop dette forslag. Depot + aktiv og frisk, komplet Pluto-beholdning er grundlag for exit-overvågningen; tvetydig oprindelse forbliver ukendt.

### Verificeret i denne gennemgang

- GitHub-grenen er læst ved `69d1279`; eksisterende Early Catalyst, automatisk kandidatoprettelse, risikogate og dele af beholdningskoblingen er inspiceret. Gennemgangen er endnu ikke afsluttet.
- Pluto, EODHD og Endavu har svaret på read-only opslag for GOGO. EODHD og Endavu leverede daterede historiske/seneste observationer; de er ikke dokumentation for en frisk live-kurs søndag. Pluto-opslaget gav pris uden kurstidspunkt.
- Pluto `estimate_order` for et kontrolbeløb på 20 DKK returnerede et `estimate`-objekt med `commission`, `commissionCurrency`, `accountNotionalCurrency`, `filledAccountNotionalCurrency`, `assetBankFx` (base/quote/rate) og `quantity: null`. Et særskilt estimat for én aktie blev afvist med utilstrækkelig købekraft. Ingen ordre eller forslag blev oprettet. Kontrolbeløbet er ikke et valgt handelsbeløb eller en sessionsstandard.
- Den rettede serverscript-kontrol `tasks/pluto_readonly_risk_probe.py` er **stadig ikke kørt mod applikationsserverens forbindelse**. Direkte plugin-opslag dokumenterer et svarformat, men erstatter ikke denne kontrol eller en test af ESCAPEs fortolkning af svaret.

### Resterende arbejde og accept

1. Færdiggør beløbsvalg, verificeret risikogrundlag og genkontrol gennem det eksisterende estimat-/forslagsflow. Test null-antal, manglende/ændret stop, valuta og gebyrer samt globale størrelse-, tabs- og eksponeringsgrænser. Ingen risikoklar status ved ukendte input.
2. Gennemgå og test hele kandidat → Early Catalyst → dynamisk signal-kæden, inklusive tilbagekaldelse ved for gamle eller ændrede data, revurdering, genbrug af sessioner og respekt for manuel pause/stop. Kontroller, at visningen skelner mellem signal, risiko og datamangler.
3. Gennemgå og test koblingen til verificerede beholdninger, herunder eksisterende beholdning før et nyt forslag, accepteret men ikke udført forslag, delvise fills, flere depoter, tvetydig oprindelse og solgt position. Exit-watch må ikke stoppe med kandidaten.
4. Kør den rettede read-only kontrol på applikationsserveren og kontroller adapterens håndtering af de faktiske felter. Dokumenter manglende adgang som en konkret blocker; ingen påstand om gennemført serverkontrol uden resultat.
5. Opdater status med ændringer, relevante testresultater og resterende fejl, og gennemgå det med Heine. Først derefter startes den samlede live-test med faktiske readbacks ved åbent relevant marked. Godkendelse af live-test er ikke tilladelse til testordrer.

## Installationsstatus — 8. november 2026

Købsplan, risikobinding og statusdiagnostik er implementeret og lokalt testet. Se [installationspakken og dens præcise test-/driftsstatus](EARLY_CATALYST_INSTALL_2026_11_08.md). Ovenstående liste over resterende arbejde er udgangspunktet for gennemgangen, ikke en påstand om at alle punkter fortsat mangler. Serverens read-only kontrol, visuel browserkontrol og faktiske markedsreadbacks er stadig efterinstallationskontroller; der foreligger ikke LIVE PASS. Separat exit fungerer på depot + aktiv; en accepteret intention dokumenterer ikke beholdningens oprindelige køb eller fill.

## Night Intelligence Mode — gældende tillæg

Ejerens tillæg af 8. november 2026 er indsat i [den fælles samarbejdsaftale, afsnit 2a](ESCAPE_TRADING_AGREEMENT_V3_9.md#2a-tillæg--night-intelligence-mode). Global scanning og teknisk rapportering fortsætter hver time; rutinemæssige brugerrettede rapporter holdes tilbage kl. 23–06 dansk tid. Kl. 07 leveres Morning Intelligence; kl. 08–22 gælder normal rapportering. Relevante Pluto-verificerede kandidater overdrages straks gennem det validerede flow, også om natten, og faktisk aktivering læses tilbage. Tidskritiske signaler og alvorlige fejl må fortsat meddeles straks. Ingen ændring af risikoregler eller handelsmandat.

## Ansvar og autoritet

- **Trading Radar / ChatGPT:** opdager og vurderer kandidater med stabilt `candidate_id`, Pluto-verificeret instrument, kilde, observationstid, begrundelse, beslutning (`KØB`/`AFVENT`/`FRAVÆLG`), næste trigger og revurderingsfrist. Ingen ordre uden gældende mandat og faktisk Pluto-flow.
- **ESCAPE:** eneste autoritative register for kandidathistorik, rapporter, `watch_id`, motorsessioner, status, fejl, deadlines og hændelser. Rapporter må ikke slette historik ved udeladelse.
- **HOT WATCH:** selvstændig regelmotor, der følger aktive sessioner, beregner signaler og gemmer tidsstemplede observationer. Den må **ikke** oprette, ændre eller annullere Pluto-ordrer.
- **Pluto:** autoritet for instrumentklasse, beholdning, ordrer og faktiske fills. Et signal er ikke en handel.
- **Codex:** implementerer, tester og installerer ændringerne på serveren. Ingen parallel statusmotor eller dubletdatabase.

## Den konkrete kæde

1. **Læs før skriv:** Ved hver radar-kørsel hentes seneste ESCAPE-rapport, komplet kandidathistorik og samtlige relevante HOT WATCH-motorsessioner inkl. paginering. Brug `get_hot_watch` og `get_hot_watch_engine` når de faktisk er eksponeret. Manglende svar betyder `UNKNOWN`, ikke `STOPPET`.
2. **Discovery:** Radar må optage en dokumenteret interessant kandidat til HOT WATCH **uden** at have købspris, exitplan eller fulde tekniske indikatorer. Pluto `search_assets → get_asset` og entydigt instrumentmatch er dog obligatorisk før aktivering. `AFVENT` er en gyldig HOT WATCH-beslutning, ikke et køb.
3. **Persistér og aktivér:** Kandidaten gemmes først i fuld, valideret ESCAPE-rapport. Derefter oprettes/genbruges en **faktisk** motorsession via autoriseret motorhandling. `record_hot_watch` alene er en observation og må aldrig udlægges som aktivering. Læs motorsessionen tilbage og verificér `watch_id`, `candidate_id`, aktiv-ID, status, deadline og formål. Ved fejl: `HANDOFF BLOCKED` med præcis årsag, aldrig falsk `AKTIV`.
4. **Ingen dubletter:** Samme rapportkandidat og samme handelsidé/instrumentklasse skal genbruge en åben eller pauseret session. En ny rapport forlænger/opdaterer eksisterende session, når den har en ny dokumenteret vurdering. Flere sessioner på samme aktie tillades kun med **forskelligt eksplicit formål**, eksempelvis kandidat-watch versus beholdnings-exit-watch. Respektér brugerens manuelle pause/stop; ingen automatisk genstart.
5. **Status og signaler:** Vis faktisk `RUNNING`, `WARMUP`, `PAUSED`, `NO_DATA`, `REVIEW_DUE`, `EXPIRED` eller tilsvarende **faktisk understøttede** statusser; oversæt til eksisterende schema uden at opfinde API-felter. Vis datakildens tid, pris, dagens ændring og siden sidst kun ved sammenlignelige tidsstempler. Feedfejl, lukket børs og manglende heartbeat må ikke forveksles med negativt handelssignal.
6. **Revurdering:** Hver kandidat får en eksplicit revurderingsfrist. Mangler den, er standard **24 timer efter seneste gyldige vurdering**. Når fristen udløber, markeres kandidaten **REVURDERING FORFALDET** og prioriteres i næste radar-kørsel; **ingen automatisk lukning alene på grund af fristoverskridelse**. En session må ikke køre ubegrænset uden ny vurdering: efter yderligere 24 timer uden gyldig revurdering afsluttes **kun den rapportbaserede kandidatsession** som `EXPIRED`, med journalført årsag og tid. Hvis Codex ikke kan implementere en uafhængig sikker udløbsproces, må den ikke foregive, at automatisk lukning virker.
7. **FRAVÆLG:** En eksplicit ny `FRAVÆLG`-vurdering afslutter kandidatens rapportbaserede session med det samme og bevarer historikken. Genaktivering kræver ny katalysator, ny vurdering og nyt timestamp; manuel stop må ikke omgås.
8. **Beholdningsbeskyttelse:** Exit-watch på en **faktisk Pluto-position** er særskilt, koblet til depot + aktiv og eget `watch_id`. Den må **aldrig** lukkes, fordi en kandidat bliver kold, en rapport mangler, eller et nyt køb fravælges. Lukning ved solgt position kræver frisk, komplet Pluto-afstemning og bekræftet fill/ingen beholdning; ved usikkerhed behold overvågningen og markér dataproblem.
9. **Feedback til Radar:** ESCAPE skal gøre statusændringer, nye triggers, udløb, fejl og signaler tilgængelige med stabile ID'er og tidsstempler. **Første live-løsning er pull:** radaren læser ændringer ved hver planlagt kørsel. Hvis der allerede findes en faktisk understøttet event-/notifikationskanal, kan Codex koble væsentlige triggers til en tidligere autoriseret gennemgang; ingen påstand om push til ChatGPT uden verificeret leveringsmekanisme.
10. **Sikkerhed:** HOT WATCH handler aldrig. Hoveddepot kræver brugerens udtrykkelige godkendelse. AI Trader følger kun Plutos reelle mandat og godkendelsesflow. Intet automatisk stop-loss eller ordreændring introduceres her.

## Gå live — færdig implementering, ikke flere dokumentationsrunder

Efter ovenstående gennemgang skal Codex **færdiggøre og installere** hele kæden i den eksisterende ESCAPE-arkitektur, migrere eksisterende sessioner uden tab af historik og genstarte relevante services sikkert. Brug eksisterende skemaer, værktøjer, permissions og API'er; udvid dem kun hvor nødvendigt for faktisk aktivering, revurdering, deduplikering, timeout og readback.

**Definition af færdig:**
- En ny Pluto-gated `AFVENT`-kandidat i radarrapporten skaber/genbruger én faktisk HOT WATCH-session, som kan læses tilbage som aktiv.
- Næste rapport for samme kandidat opdaterer sessionen, men skaber ikke dublet.
- En kandidat med udløbet 24-timers revurderingsfrist bliver `REVURDERING FORFALDET`; efter yderligere 24 timer uden ny vurdering lukkes kun kandidat-sessionen, også hvis markedet er lukket eller feedet fejler.
- Ny vurdering inden lukning fornyer fristen; eksplicit `FRAVÆLG` afslutter kandidat-sessionen straks. Manuelt stoppet session genstarter ikke af sig selv.
- En eksisterende Pluto-beholdnings exit-watch fortsætter uanset kandidatens status.
- Motorens observationer og status kan hentes ved næste radar-kørsel, med korrekt kilde-/hændelsestid; ingen falske fills eller handler.
- Alle ovenstående flows er prøvet i drift/test med faktiske readbacks, og den installerede serverversion er verificeret. Hvis et kritisk punkt fejler, må det **ikke** kaldes live eller PASS.

**Leverance til brugeren:** Kort besked med `LIVE PASS` eller `BLOCKED`, installeret commit/version, faktisk readback af én kandidat-session og én beholdningssession (hvis en sådan findes), samt højst tre konkrete resterende fejl. Ingen lange statusrapporter eller yderligere designforslag.

**Afgrænsning:** Ingen ændring af radarens eksisterende timeplan, Trading Lab, handelsmandater eller Pluto-ordrer.



## Rettelsesrunde — 9. november 2026

Ejeren har godkendt implementering og GitHub-installationsleverance af kapacitetsrevisionens konkrete fejl samt stabile historiske salgsadvarsler. Se [installationsnotat](INSTALL_SIGNAL_FIXES_20261109.md) og [fælles aftale, afsnit 16](ESCAPE_TRADING_AGREEMENT_V3_9.md#16-signaler-og-historiske-advarsler--9-november-2026). Forkerte fælles betingelser erstattes; ingen parallel signalmotor eller ny databasearkitektur. Ingen automatiske handler. Produktionens endelige accept står fortsat åben, indtil den installerede version og faktiske resultater er læst tilbage.


## Opfølgning på performancepakken — 9. november 2026
Eksisterende kode rettes samlet: selvstændig fremdrift pr. worker, genbrug af uændret gyldige observationer og beregning på EODHDs faktisk leverede sparsomme minutbars. Barbaserede perioder tæller observerede bars; minutbaseret momentum og acceleration beholder deres tidskrav. Tomme minutter udfyldes ikke. Pluto-kontekst, kildefriskhed, exitbeskyttelse, historiske advarsler og risikoregler bevares. Pakken inkluderer menurettelsen fra 287d4dc og kræver ingen nye moduler, miljøindstillinger eller databasearkitektur. Den installerede effekt kontrolleres efter ejerens installation; lokale testresultater er ikke LIVE PASS.

Brugerens UI-præcisering: Signaladvarsler vises som kompakte pulserende ikoner ved statussen. Forklaring, tidspunkt og kvittering åbnes ved klik. Kvittering standser kun opmærksomhedsmarkeringen; signalstatus og handel ændres ikke. Historikken er fortsat tilgængelig via et neutralt ikon.

## Signalberedskab og samlet beholdningsvisning — 9. november 2026
Faktiske observationer på begge sider af et tidshul bevares inden for samme instrument, kilde og handelssession. Hver indikator bruger sit eget datavindue; minutbaserede returns må ikke beregnes ved blot at tælle observationer. Ingen medianer, interpolation eller globale 34-punktsnulstillinger. Strategiens konkrete regelinputs og eksisterende risiko-/bekræftelseskrav bestemmer beslutningsberedskabet. En gyldig prisbaseret exit afhænger ikke af uvedkommende indgangsindikatorer eller bid/ask, mens køb fortsat kræver verificerede friske quotes.
Nye quotes og kalenderoplysninger til samme handel må opdatere beregningsgrundlaget med egne kildetider uden at forny handelens tidspunkt eller skabe ekstra købsbekræftelser. De eksisterende workers deler brugerafgrænset broker-cache med oprindelige kontroltider; ingen ændring af handelsmandat.
Totaloversigten grupperer faktiske beholdninger på Pluto asset-ID. Collection-sammendrag tælles ikke som ekstra beholdninger. Antal, markedsværdi og resultat summeres; gennemsnitskurs vægtes med faktiske antal. Beløb kræver fælles verificeret valuta; manglende data udfyldes ikke. Individuelle depoter, signaler, historik og handelsvalg bevares, og en samlet visningsrække får ikke sin egen handelsidentitet.
