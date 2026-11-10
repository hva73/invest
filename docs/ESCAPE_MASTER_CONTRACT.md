# ESCAPE — fælles kontrakt og aktuel indgang

**Reviewgrundlag:** udviklingsgrenen `codex/escape-development`, kode ved `6f6460d7c54b704faa23cf7aabefce4959888774`, 10. november 2026. Dette er en samlet reference og et reviewudkast, ikke en ny ejerbeslutning, ændring af strategi eller bevis for installeret kode. Genlæs aktive Issues og senere commits. Historiske statusafsnit i de tilknyttede dokumenter kan beskrive andre versioner.

## Brug og forrang

Start i [AGENTS.md](../AGENTS.md), det aktuelle Issue og nyeste kommentarer. Ejers udtrykkelige, aktuelle mandat gælder; en ny prosatekst ændrer ikke automatisk strategi eller rettigheder. Ved forskel mellem krav og faktisk wireformat beskriver [rapportskemaet](../report_v2.py), [motorens skema](../hotwatch_contract.py), validator og runtime det faktiske tekniske interface. Aftalekrav, der endnu ikke understøttes, er krav eller konflikter, ikke implementeringsbevis. Ret ikke kode, skema, aftale eller prompt ensidigt ved en reel mandatkonflikt.

Kilder: [v3.9 + tillæg](ESCAPE_TRADING_AGREEMENT_V3_9.md), [samarbejdet](HOTWATCH_SAMARBEJDSAFTALE.md), [end-to-end-kontrakt](END_TO_END_DATA_CONTRACT.md), [motorens kontrakt](HOTWATCH_ENGINE_DATA_CONTRACT.md), [rapportformat](REPORT_V2.md), [statusmodel](CANDIDATE_STATUS_MODEL.md), [Early Catalyst](EARLY_CATALYST_V1.md), [drift](STATUS.md) og [Projects-bro](../development/GITHUB_PROJECTS_GENERAL_BRIDGE.md). [Issue #1](https://github.com/hva73/invest/issues/1) ejer den samlede afstemning.

## Arbejdsflow og ejerskab

Global discovery → tidlig WATCH/AFVENT → dokumenteret instrument-/Pluto-kontrol → valideret rapport og kandidatjournal → faktisk HOT WATCH-session → datakvalitet, beregning og risiko → handling inden for det pågældende depots gældende mandat → verificeret Pluto-ordre/fill → separat exit-overvågning. En tidlig observation er ikke et købssignal. Vurderinger, motorsignaler, ordreintentioner, brokerstatus og fill er separate tilstande. Kun brokerdata dokumenterer fill; nul fyldt er ikke et salg. Rapportens `verified` er afsenderens oplysning, ikke en uafhængig Pluto-kontrol.

Radarens aftalte scanning omfatter åbne globale markeder, markedsfaser, nyheder med kilde/tid og Night Intelligence; 22-rapporten omfatter Asien. Ekstern radarprompt og faktisk fuld regiondækning er ikke verificeret ved kodelæsning. Trading Lab er separat og fiktivt.

## Sporbar teknisk status

| Emne | Kode/kontrakt og status | Konsekvens / kontrol |
|---|---|---|
| Rapportidentitet | [report_v2.py](../report_v2.py) og [report_ingest.py](../report_ingest.py): v2, højst 80 kandidater og 150 kilder; ID unikt pr. ejer på tværs af test/drift; canonical digest og konflikt ved andet indhold. **Implementeret i kode.** | Nyt indhold/kategori kræver nyt ID. Skemagrænser er ikke Radarens aftalte kandidatloft. |
| Rapport-readback | [report_ingest.py](../report_ingest.py) `item` og [app.py](../app.py) `/api/reports/item` læser eksakt ID + kategori; [mcp_reports.py](../mcp_reports.py) tilbyder `get_latest_report`, ikke et dokumenteret eksakt-ID MCP-rapportværktøj. **Delvist:** brugerens aktuelle adgang til HTTP-item er ikke testet her. | Kontrollér eksakt ID via tilgængeligt autoriseret interface; seneste rapport kan være en anden ved samtidige leveringer. Kontrollér separat kandidatjournal med `get_hot_watch`, faktiske sessioner med `sync_hot_watch`. |
| Lifecycle og identitet | [report_v2.py](../report_v2.py), [statusmodel](CANDIDATE_STATUS_MODEL.md). **Implementeret i kode; produktionsversion skal aflæses.** | Stabilt `candidate_id` er ikke ticker; `trade_cycle_id` identificerer handelsforløb, `watch_id` motorsession og depot/asset brokerkontekst. Se mapping nedenfor. Udeladelse i ny rapport sletter ikke journalhistorik. |
| Automatisk opstart | [hotwatch_service.py](../hotwatch_service.py) `auto_activate_candidate` og beholdningsflow samt [mcp_reports.py](../mcp_reports.py). **Implementeret i kode**, styret af faktiske gates og indstillinger. | Lifecycle HOT_WATCH eller åben side starter ikke i sig selv en session; en kørende service kan særskilt oprette kvalificeret kandidat-/beholdningswatch. `CREATED` og rapportkvittering er ikke frisk feed eller aktivt signal. |
| Batch og kapacitet | [hotwatch_contract.py](../hotwatch_contract.py) og [hotwatch_engine.py](../hotwatch_engine.py): batchschema/motor op til 40, mens [mcp_reports.py](../mcp_reports.py) `activate_hot_watch_batch` håndhæver 1–20. `capacity()` bruger 60 ved manglende indstilling og 40 ved ugyldig heltalsværdi; positiv værdi har her intet øvre clamp. **Konkret interfaceforskel**, ikke en ændringsordre. | 20 oprettede sessioner beviser ikke 20 samtidige pollingkald; serverens faktiske konfiguration er ukendt her. Afstem schema og MCP i en særskilt kodeændring, før 21–40 loves fra MCP. |
| Friskhed og feed | [designspec](DESIGN_STATUS_SPEC_V1_DA.md) T19: UI-grænse 60 s; [hotwatch_contract.py](../hotwatch_contract.py) / [hotwatch_strategy.py](../hotwatch_strategy.py): global risikogrænse `max_quote_age_s=120`; kilde-/adaptergulve og profil er særskilte. Pluto standard 300 s; EODHD standard 300 s, med kodeveje for konfigureret hurtigere feed/WebSocket, inkl. særlige undtagelser. | 60 s UI er ikke 120 s risikogate eller 300 s pollinggaranti. Kildetid, rettigheder, indstillinger, belastning og installeret version skal måles; WebSocket-kode er ikke bevis på live-adgang. |
| Risiko og strategi | [hotwatch_contract.py](../hotwatch_contract.py) `GLOBAL_RISK`, [hotwatch_strategy.py](../hotwatch_strategy.py), [Early Catalyst](EARLY_CATALYST_V1.md). **Kodebaseline**, ikke fuld livegodkendelse. | `escape_momentum 1.0.0` bevares; Early Catalyst live-pilot og fase-3-begrænsninger holdes adskilt. Manglende data må ikke blive falsk BUY. |
| Mobil og push | [Issue #13](https://github.com/hva73/invest/issues/13), [grafer](MARKET_CHARTS.md), [notifikationer](NOTIFICATIONS_STRATEGY_DA.md). **Krav og eksisterende komponenter; samlet ny løsning ikke verificeret live.** | P0: samme reelle SELL-hændelse må ikke spamme, men ny kritisk exit skal frem. Signalvisning skal kombinere faktisk graf Dag/Uge/Måned/År, kilde/tid, store ærlige KPI'er, korte grunde og permanent synlige mobilhandlinger; ingen ordre ved åbning. |
| Projekttavle | [Issue #11](https://github.com/hva73/invest/issues/11) og [brovejledning](../development/GITHUB_PROJECTS_GENERAL_BRIDGE.md). **Aktiveret** for eksisterende #1 og #3–#16; #3 har særlige begrænsninger. | Statusbroen bruger journal, serialisering og readback. Codex’ reelle #11-skrivning og ChatGPTs #1-skrivning bestod med Actions-audit/readback. Identisk GitHub-bruger/App kan ikke skelne agenter sikkert. |
| Release | [Issue #16](https://github.com/hva73/invest/issues/16), [UPDATE.md](UPDATE.md). **Plan**, ikke demonstreret automatisk deployment. | Nordicway `cp14.nordicway.dk:33`; servercheckout er ikke produktion. Hostnøgle og ekstern login var ikke uafhængigt bekræftet ved sidste fund. Godkendt pinnet version, backup/migration, restart og live-readback er nødvendige før LIVE PASS. |

### Lifecycle: dansk visning → wireværdi

| Visning | Wire |
|---|---|
| OPDAGET | `DISCOVERED` |
| ANALYSERES | `ANALYZING` |
| HOT WATCH | `HOT_WATCH` |
| AFVENTER TRIGGER | `WAITING_TRIGGER` |
| KØBSSIGNAL | `BUY_SIGNAL` |
| ORDRE AFVENTER | `ORDER_PENDING` |
| POSITION ÅBEN | `POSITION_OPEN` |
| EXIT WATCH | `EXIT_WATCH` |
| LUKKET | `CLOSED` |
| ARKIVERET | `ARCHIVED` |

Det er ikke en tvungen lineær sekvens. Den rapporterede tilstand er en påstand/journalbegivenhed, ikke i sig selv en aktuel session eller Pluto-fill.

## Verifikation og ansvar

| Krav | Ansvar | Kontrol / reference |
|---|---|---|
| Global scanning inkl. Asien kl. 22, Night Intelligence og nye katalysatorer | Radar | Aktuelle Radar-kørselsdata og kildetider; ikke bevist af backend-tests. |
| Rapport, ejer/test-isolation, idempotens og journal | Radar sender; ESCAPE validerer/lagrer | `tests/test_report_validation.py`, `tests/test_report_v2.py`, `tests/test_report_ingest.py`, `tests/test_mcp_reports.py`; eksakt klientreadback særskilt. |
| Identitet, lifecycle, risiko og motor | ESCAPE/HOT WATCH | `tests/test_hotwatch_engine.py`, `tests/test_hotwatch_e2e_contract.py`, `tests/test_hotwatch_agreement.py`; uafhængig Pluto-evidens for fill. |
| Mobil og ny kritisk SELL uden gentagelser | Codex, Issue #13 | Push/event-regression og faktisk mobilflow; liveaccept efter godkendt installation. |
| Projektstatus | Agent via GitHub Actions | [Codex live-run](https://github.com/hva73/invest/actions/runs/42889702635) og [readback](https://github.com/hva73/invest/actions/runs/42889798135); [ChatGPTs live-run](https://github.com/hva73/invest/actions/runs/42891046911) og audit er dokumenteret i #11. |
| Installation og drift | Ejer godkender; Issue #16 implementerer | Verificeret hostnøgle, pin, backup, migration, genstart og faktisk health/version/session-readback. Ikke udført i dokumentreview. |

## Åbne ejer-/kontraktvalg og verificering

1. **REEL KONFLIKT:** v3.9 §2 nævner højst fem nye HOT WATCH-kandidater og §5 et bestemt rapport-ID-format; det senere dokumenterede v5.1-forløb afviser et kunstigt kandidatloft på 3/5 og bruger andet ID. Se [v3.9 §13](ESCAPE_TRADING_AGREEMENT_V3_9.md#13-verifikationsstatus-før-samlet-live-test--8-november-2026). Hvilken regel der gælder, skal afgøres af ejeren; ikke ved at vælge kodeskemagrænsen 80. Grænsen for handlingsrettede forslag er separat.
2. **MANDAT IKKE FASTSLÅET HER:** Ældre generelle formuleringer om manuel godkendelse kan ikke alene fastslå aktuelle, eventuelt forskellige porteføljemandater. Læs den seneste konkrete ejerbeslutning og relevante brokerrettigheder for hvert depot, før handelsautomatik ændres. Denne dokumentopdatering giver ingen handler eller nye rettigheder.
3. **MANGLER LIVE-VERIFIKATION:** fuld ekstern Radar-automatisering/Asien, faktisk feed-entitlement, kode/config på serveren, eksakt rapportreadback for den anvendte klient, install/restart/rollback og ny mobil/push-funktion. Historiske tests og observationer bevares med dato/versionsgrundlag.
4. **OPTIMERING:** Afstem MCP-batchskema 40 mod håndhævet 20 i samme kode/schema/testændring. Dokumentér den faktiske SSH-hostnøgle via uafhængig kilde og test eksisterende releaseflow under #16 uden at antage, at en clone er installation. For #13, undersøg unikke event-/enheds-ID'er før ændring; antal sendte jobs er ikke antal bekræftede telefonleveringer.

**Ændringslog 2026-11-10:** Etableret fælles indgang og adskilt aktuel kode, observeret drift, historik og åbne aftalevalg efter Issue #1. Ingen maskinschemaer eller handelsregler ændret.
