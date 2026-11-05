# ESCAPE × Trading Radar × HOT WATCH — driftsaftale (klar til implementering)

**Mål:** Få hele kæden i produktion nu: RADAR opdager → ESCAPE registrerer → HOT WATCH følger → RADAR revurderer → bruger beslutter eventuel handel. Dette er implementeringsordre til Codex, ikke en påstand om at funktionerne allerede er installeret.

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

Codex skal **færdiggøre og installere** hele kæden i den eksisterende ESCAPE-arkitektur, migrere eksisterende sessioner uden tab af historik og genstarte relevante services sikkert. Brug eksisterende skemaer, værktøjer, permissions og API'er; udvid dem kun hvor nødvendigt for faktisk aktivering, revurdering, deduplikering, timeout og readback.

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
