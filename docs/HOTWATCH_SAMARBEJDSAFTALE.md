# Udkast: fælles aftale om HOT WATCH mellem Trading Radar, ChatGPT og ESCAPE

**Status: Forslag til aftale, ikke en beskrivelse af funktioner, der alle er implementeret.** Formålet er at forhindre, at rapportkandidater og deres overvågning hænger ved uden en aktuel begrundelse. Aftalen gælder rapportbaserede muligheder og skelner dem fra overvågning af faktiske beholdninger.

## Ansvar

- **Trading Radar / ChatGPT** undersøger muligheder og leverer en dokumenteret vurdering med årsag, kilder, næste trigger og frist for revurdering. ChatGPT læser ESCAPEs aktuelle status, før der sendes en ny rapport eller anmodes om ændringer. En tidligere besked i en chat er ikke bevis for, at motoren stadig kører.
- **ESCAPE** validerer og gemmer rapporter, kandidatens historik, motorsessioner og deres seneste status. ESCAPE er autoritativ for, hvilke sessioner der faktisk er åbne, pauserede, udløbet eller afsluttet. ESCAPE viser datakvalitet og fejl og giver læseadgang til historikken.
- **HOT WATCH-motoren** læser marked og depot inden for sine rettigheder og datagrænser. Den beregner signaler og kontrollerer, om sessionens tidsgrænse er nået. Et signal er ikke en gennemført handel. Motoren opretter, ændrer eller annullerer ikke Pluto-ordrer.
- **Pluto** er kilden til verificerede beholdninger, ordrestatus og eventuelle udførelser. Manglende ordreoplysninger er ikke bevis for, at ingen ordre findes.
- **Brugeren** kan pause eller afslutte en session og styrer tilladelser, kilder og eventuelle handelsbeslutninger. En brugerstoppet session må ikke genstartes bag om brugeren.
- **Codex** gennemfører aftalte kodeændringer, dokumenterer og tester dem. Et forslag i dette dokument ændrer ikke automatisk strategi, risikoregler eller serverens drift.

## Foreslået forløb for en rapportkandidat

1. **Ny kandidat:** Rapporten indeholder et stabilt `candidate_id`, navn/ticker, verificerbart aktiv-ID hvor det findes, kilder og analysetid. Samme aktiv på forskellige børser må ikke sammenlægges ud fra ticker alene.
2. **Vurderet:** ChatGPT angiver `KØB`, `AFVENT` eller `FRAVÆLG`, en begrundelse og, ved `AFVENT`, en konkret trigger og deadline. `KØB` er en analyse, ikke en ordre eller en godkendelse af handel.
3. **HOT WATCH:** En autoriseret oprettelse knytter en selvstændig motorsession til kandidaten med stabilt `watch_id`, datakilde, aktivid, overvågningsformål og `end_at`. Ingen kandidat må vises som aktiv HOT WATCH, før ESCAPE har bekræftet, at sessionen findes. Åbne og pauserede sessioner udelades fra listen for ny oprettelse; pauserede sessioner kan i stedet genoptages.
4. **Opvarmning eller drift:** Markedsdata kan vises med det samme. Warmup viser faktiske sammenlignelige observationer og antal, der mangler til strategien. `NO_DATA`, gammel kurs, begrænset feed, lukket marked eller manglende heartbeat angiver en data-/driftstilstand og gør ikke i sig selv analysen kold.
5. **Kold / ikke længere aktuel:** Kandidaten bliver kold, når ChatGPT eksplicit fravælger den eller dens revurderingsfrist udløber uden en nyere gyldig vurdering. ESCAPE afslutter den tilhørende **rapportbaserede kandidatsession**, journalfører tidspunkt og årsag og viser den som afsluttet. Historikken bevares. Udløb af en session er ikke bevis for, at en aktie er solgt, eller at en ordre er annulleret.
6. **Genaktivering:** En kold/afsluttet kandidat kan kun blive aktuel igen med ny begrundelse og nyt tidsstempel; systemet skal undgå dubletter og respektere brugerens manuelle stop. En ny session skal være sporbar til den nye vurdering.

### Foreslået tidsregel til beslutning

ChatGPT skal levere en eksplicit `deadline` for alle kandidater, der skal overvåges som nye muligheder. Forslag: Hvis en gyldig deadline ikke er leveret, sættes en **standardfrist på 24 timer fra seneste vurdering**. Den tidligere af de to frister anvendes ikke automatisk: en eksplicit deadline erstatter standardfristen. Udløb mærkes tydeligt som “frist udløbet · revurdering mangler”, og rapportkandidatens session afsluttes. Fristen kan forlænges med en ny, tidsstemplet vurdering før udløb. Tidsgrænsen er et forslag og skal aftales, inden den bliver en automatisk regel.

Begrundelse: Kandidaten bør ikke blive ved for evigt, men 24 timer er ikke et bevis for, at en investering er dårlig. Stale data eller en forsinket rapport ændrer ikke den faktiske beholdning. En ekstern kildefejl betyder ikke i sig selv `FRAVÆLG`.

## Beholdninger og afgrænsning

Automatisk overvågning af en **faktisk Pluto-beholdning** er en separat exit-overvågning med sit eget `watch_id` og depot/aktiv-kobling. Den skal ikke standses alene, fordi en rapportkandidat bliver kold, dens frist udløber eller en nykøbside fravælges. Ændringer i positionen skal baseres på verificerede Pluto-data; udførelse må ikke udledes af et signal. Manuelt stoppede eller pauserede sessioner respekteres. En sikker regel for automatisk ophør, når en beholdning ikke længere findes, kræver en frisk, komplet depotobservation og skal implementeres og testes særskilt.

## Data og status, som parterne skal kunne udveksle

| Oplysning | Ansvarlig kilde | Forventet anvendelse |
| --- | --- | --- |
| `candidate_id`, rapport-ID, analysetid, kilder, vurdering, årsag og trigger | Trading Radar / ChatGPT | Kan knyttes til historik uden at gætte instrument eller genbruge en gammel vurdering. |
| Deadline, seneste vurdering og genaktiveringsgrund | Trading Radar / ChatGPT | Frist kan evalueres; en udløbet beslutning fornyes med ny dokumentation. |
| `watch_id`, formål, `end_at`, start/stop/pause, årsag og tidsstempler | ESCAPE / HOT WATCH | Sandheden om den enkelte motorsession og hvorfor den er aktiv eller ikke aktiv. |
| Status for marked, kurs, indikatorer, dataalder, warmup og seneste signal | Kildedata og HOT WATCH | Vises med kildetid og begrænsninger; `NO_DATA` er aldrig et køb/salg. |
| Faktisk position, ordresituation og bekræftet udførelse | Pluto | Adskilles fra ChatGPTs vurdering og motorens signaler. |
| Alle aktuelle sessioner og efterfølgende hændelser | ESCAPE | ChatGPT kan ved en autoriseret læsning afstemme sine kandidater og registrere ændringer i den næste vurdering. |

Drift og testdata skal holdes adskilt. Statusser skal kunne læses med stabile ID'er, tidsstempler og årsager. Listen over aktive sessioner må ikke forveksles med en liste over gennemførte handler. En manglende session i et begrænset eller pagineret svar er ikke i sig selv bevis for, at sessionen er afsluttet; læs alle relevante sider eller et eksplicit fuldstændigt svar.

## Besked tilbage til ChatGPT

**Anbefalet første løsning: ChatGPT henter status fra ESCAPE ved starten af hver autoriseret gennemgang.** Den henter den komplette liste over åbne/pauserede sessioner og relevante ændringer/årsager siden sidst. Derefter sender den kun nye eller opdaterede vurderinger. Fravær i en ny rapport sletter ikke en kandidat og beviser ikke, at noget er solgt. ChatGPT kvitterer ikke for noget, som ikke er læst; afbrudte kald kan gentages uden dubletter.

I den eksisterende kode kan en autoriseret klient læse motorsessioner, signaler og hændelser med MCP-værktøjet `get_hot_watch_engine` med `hotwatch:read`; kandidathistorik og rapportobservationer kan læses med `get_hot_watch` med `reports:read`. `control_hot_watch` kræver `hotwatch:manage`. Disse er pull-kald, som klienten selv skal udføre. Der er ikke konstateret en automatisk pushbesked fra ESCAPE til en hvilende ChatGPT-samtale. En planlagt gennemgang, webhook eller anden leveringsmekanisme kræver særskilt implementering og faktisk opsætning.

## Nuværende kode og nødvendigt arbejde

- Rapporternes kandidater samles i et register. `FRAVÆLG` samt `CLOSED`/`ARCHIVED` påvirker, om en kandidat vises som aktiv. Eksisterende positions- og ordrehistorik slettes ikke.
- Den aktuelle kandidatprojektion lukker **ikke automatisk** en kandidat alene, fordi en vurdering eller `decision.deadline` er gammel. En HOT WATCH-session kan udløbe på sit eget `end_at`, men kandidatens deadline overføres ikke automatisk til alle sessioner.
- Manuel pause/stop og kill switch findes. Udløb behandles af motoren; hvis den ikke kører, kan et planlagt stop ikke antages udført til tiden.
- Automatisk fristfastsættelse, kold-status, entydig kobling mellem kandidatens frist og rapportbaserede sessioner, planlagt udløb uafhængigt af tilgængeligt kursfeed, genaktiveringsregler og afstemning/meddelelseslevering skal implementeres og testes. Det skal ske uden at lukke beholdningsbaseret exit-overvågning eller ændre Pluto-ordrer.
- Der skal testes ejerskab og test/drift, tidszoner, deadlines og fornyelser, flere sessioner på samme aktiv, pause og manuelt stop, manglende data, genstart, ufuldstændige afstemninger og situationen, hvor leverandør eller ChatGPT er utilgængelig.
