# WIP checkpoint — 3. november 2026

**IKKE KLAR TIL INSTALLATION ELLER RELEASE.** Brugeren har godkendt lokal implementering på codex/design-review-wip, men ingen release/installation, handelsmandat-, polling-, strategi- eller produktionsændring. Brugeren varslede 10% resterende forbrug og mulig låsning indtil 6. november kl.16. Arbejdsbackup skal pushes nu.

## Godkendt grundlag

- DESIGN_STATUS_SPEC_V1_DA.md: original v1.0, gemt byte-for-byte.
- DESIGN_V1_IMPLEMENTATION_PLAN_DA.md og ACCEPTANCE_MATRIX_DA.md: godkendt plan. Baseline 254 Python +3 JS bestået før denne implementeringsrunde.
- END_TO_END_DATA_CONTRACT.md er ny samlet kontrakt. Beslægtede emner fandtes spredt i andre docs, men ingen ækvivalent samlet kontrakt fandtes. Bruger kræver felt-/statusansvar, afsender/modtager-konsekvensanalyse, schema/UI-skel, idempotens/historik/readback, versionering og obligatorisk impact assessment.
- HOTWATCH_ENGINE_DATA_CONTRACT.md er nyt motorafsnit, refereret fra end-to-end-kontrakten. Bruger kræver selvstændig matematisk motor, faktiske parametre/formler/frekvenser, uafhængige statuser og særskilte E2E-tests. Ingen af motorens Pythonfiler, gamle worker/jobs eller trade_service er ændret mod 1309e68 (byte-for-byte kontrol udført).

## Implementeret lokalt i dette checkpoint

- display_policy.py: visningspolitik, source-time-friskhed 60/300/86400s, eksplicit kalender/UNKNOWN, officielle/siden-sidst-referencer, urealiseret/cashflow-regnestykker, statusgrupper og 7-dages/uløst-kritisk journalfilter. Disse visningsregler ændrer ikke motorens eksisterende 120s-risikoloft eller 300s-providerpolling.
- dashboard_projection.py: actual broker holdings fra ejede snapshots, root-only totals, eksakt asset+depot→rapportanalyse, conflicts/unknowns, source-time freshness, append-only quoteobservationer og last-complete holdingscache. Init/save i portfolio_data.py bevarer cache ved ufuldstændige snapshots. Ingen ekstern trafik i build.
- report_v2.py: valgfri portfolios[].broker_reference={provider:pluto,external_id}, ikke autoritativt bevis. Skal eksporteres til eksempelschema og dokumenteres i fælles validering/tests.
- app.py /api/state: ny dashboard og provider_status; nyt cookie-auth /api/dashboard/journal. Nye JS-moduler bundles i app.js.
- static/dashboard-ui.js: neutralt kontoområde, kritiske handlinger/ordrer, alle faktiske positioner i 10-kolonne desktop/kompakt mobil, sortering, detaljer, signaler og datakvalitet. Overblik bruger dette i stedet for gentagne rapportkontokort/positionskort.
- journal_projection.py/static/journal-ui.js: samlet læsetidslinje med kilde/type/periode/pagination og gamle kritiske events. Kildelister for rapport/ordre er afgrænsede; coverage-note ærlig. Ikke produktionsafprøvet endnu.
- static/intel-ui.js: WAITING_TRIGGER separat collapsed gruppe, aktive kandidatforløb, ældre observationer collapsed. intel_workflows.watch returnerer ekstra waiting/active projections; gruppernes gamle format bevaret.
- static/engine-ui.js: egne grupper critical/warning/starting/active/paused/history. Sessionskontrol uændret. Filtrering må ikke ændre polling.
- static/report-ui.js: rapport-TOC og fuld rapport i collapsed details, originale payloads uændrede. Rapportordrer sekundært på Handelsmotor; testestimat collapsed.
- static/app.js: nyt overblik/journal og navigation, neutral resultTone for absolutte værdier, legacy freshness nu >5min snapshot /60s market og24h analyse. Det gamle test_freshness.js har endnu forventninger om10/30min og skal opdateres til det godkendte nye format.
- static/index.html: navigationsgrupper; static/style.css: kompakt dashboard, finansielle farver, mobilrækker, journal og grupper. **Intet nyt visuelt browsergennemsyn er endnu udført på redesign.**
- apply_update.py: alle nye runtimefiler føjet til allowlist. Ingen installation er kørt.

## Tests indtil checkpoint

- /tmp/escape-design-build-tests.log: 254 Python-tests bestået efter første backend/dashboardarbejde, men før de seneste journal-/grupperings-/friskhedsændringer.
- tests/test_design_v1_acceptance.py: **28 tests bestået** (/tmp/escape-design-t01-t28.log), kausal/økonomisk/status/projektion. T17/T23/T24 kræver stadig rigtig browserkontrol for farver/tæthed/bredder; komponenttests er ikke fuld UI-PASS. T22 bruger syntetisk kalender, ikke live venuekalender.
- tests/test_hotwatch_e2e_contract.py: første kørsel bestod de syv første H-scenarier, H08 fejlede fordi HTTP-auths mcp_limits-tæller ændres. Rettet testen til at sammenligne forretningspersistens uden mcp_limits. Import af McpReports ændret til modulimport, så suite kun har8 H-tests. Ny kørsel /tmp/escape-hotwatch-e2e-contract-final.log: **8 H-tests bestået**, 6,532 sekunder.
- Ingen algoritmemock i H01: rigtig lokal MCP/HTTP,40 syntheticbars, BUY, revurdering,stop,historik. H04 dokumenterer at candidate ARCHIVED ikke stopper sessionens polling i eksisterende motor.

## Næste nødvendige arbejde

1. Verificér H-testresultat. Kør fuld Python-suite igen efter sidste ændringer; der kan være schema-/API-/journalkanter. Opdatér ikke evidens til PASS uden reel kørsel.
2. Implementér tests/browser_design_v1.py med 12+ faktiske syntetiske brokerpositioner (mindre/mere end rapport), positive/negative day og P/L, exaktbrokerrefs, ukendtFX, konflikter, staleanalyse, 9bredder, tastatur/fokus, faktiskcomputedstyle/hover, gem390/1440screenshots. Brug test_design_v1_acceptance.setup som fixture via module-import, undgå unittest Case import der fordobler discovery.
3. Nuværende gamle browser_positions/overview/latest_desk/layout_preview antager det gamle overblik og nogle åbne rapportafsnit. Opdatér tests til ny godkendt semantik, bevar historisk rapport-/trade-/datasikkerhed. Kør browser_hotwatch_engine, browser_intel, browser_trade_proposals, reportarkiv+pull-refresh m.fl. Kritiske sikkerhedstests må ikke svækkes for at få grønt.
4. Freshness-clienttests har endnu10/30-minutforventninger. Opdatér til60/300/86400 med grænser, future/unknown/sourcefail. Sikr ens centralpolitik og source-time, ikke receive-time.
5. MarketUI viser endnu provider-oplyst dailyChange farvet uden dokumenteret official-close-reference. Ny dashboard accepterer kun verificeret reference. Det skal afstemmes med B3: neutrale — når reference ikke kan verificeres, forklar rå providerdata i detaljer. Ingen opdigtet officialclose/marketphase og ingen ændring af motorregler.
6. Dagens depotresultat er bevidst — (pengestrømme/reference mangler). Siden-sidst — når metadata mangler. Live kalender, FX/feedrettigheder og servicehosting ikke verificeret; dokumentér reelle begrænsninger. Overdriv ikke live/EODHD eller profitable strategier.
7. Review dashboard_projection matching, partialsnapshotcache, root/Collection-scope, pnlfees og currency. Ukendtdata giver ikke falsk DKK/ejerskab. Missingfx/assessment skal være ærligt, ikke rapportsignal som erstatning.
8. Journal SQL/kildevinduer/criticalresolution: ingen automatisk afklaring; endpoints kræver owner/session, parser invalidcursor/limit sikkert. Additive schemas er endnu ikke regenereret; tilføj tests old sender/newoptionalrefs og eksportér report-v2.schema.json.
9. Dokumentér faktiske T01–T28 OG H01–H08-resultater individuelt med kommandoer/fixtures/limitations; skillsynthetic vs faktiskRadar/liveprovider. Brugeren kræver begge før release.
10. Samlet code/docreview, diff-check, protectedhashes, installer allowlist og rollbackplan. Commit/push kun WIP. Stop før release/installation/normalbranch, medmindre senere bruger eksplicit godkender det. Ingen prompt-/scheduler-/strategi-/pollingændring.

## Arbejdsmiljø

Repo /workspace/invest, lokal branch work. WIP: git push origin HEAD:codex/design-review-wip. Normalbranch codex/escape-development har e63739d (MCP2.5.1), tidligere installeretversion er a065df6 (MCP2.5.0). Brugeren udsatte installation af MCPrettelse for at samle den meddesign. Ingen subagents tilladt.

Lokale HTTP/Chromiumtests kræver sandbox_permissions=require_escalated med passende begrundelse (ingen livebroker/handler). Python: unittestdiscover. Browser: /usr/bin/chromium, Playwright installeret. Ingen configuredsecrets i udviklingsmiljø. Forrige exec transportkortfejl blev løst ved normalt retry; workspace er intakt.

## Nyeste checkpoint efter genstart

Miljøet blev starting/ready under arbejdet; workspace og ændringer overlevede. Lokal kodecommit aedc6de indeholder videreudviklingen efter 9c1c539. Efterfølgende små ændringer gør finansielle tal klikbare med bevarede farver og tydeligere danske fejllabels. Disse gemmes i næste checkpoint.

Nyere faktisk evidens:
- /tmp/escape-design-review-complete-tests.log: **295 tests bestået**, 68,382s. Der er siden tilføjet én ekstra kontrakttest (nu forventet296); fuld endelig kørsel skal tælles faktisk, ikke antages.
- /tmp/escape-hotwatch-e2e-final-review.log: **8 H-tests bestået**,8,700s, nu med eksplicit samme trade_cycle_id fra Radar til revurdering. H08 omfatter også de nye current/history UI-læseprojektioner.
- /tmp/escape-design-contract-final-review.log: **6 kontrakt-/kompatibilitetstests bestået**, inkl. partial snapshot cache, ejerskab, optional brokerreference, future time, journalcursor og sessionshistorikpagination.
- /tmp/escape-design-v1-clickable-review.log: ny browser bestået med 12 brokerpositioner, klikbare farver/hover, alle 9 bredder og alle8 visninger. Screenshots /tmp/escape-design-v1-*-390.png og *-1440.png. Aktuel mobiloversigt ca.3400–4000px mod før ca.8169px; se faktiske screenshots.
- browser_hotwatch_engine, browser_trade_proposals, browser_report_v2, browser_pull_refresh og opdateret browser_positions er bestået. Logs /tmp/escape-design-*-browser*.log og /tmp/escape-design-historical-positions-browser.log.
- Alle3 JS-suiter er bestået; freshness-test er opdateret til60/300/86400-grænser. Generiske tidsmærker bruger nu backend-publicerede policy-limits når tilgængelige.

Kodeopdateringer siden gammel note: brokerbeholdninger genbruges også i porteføljedetaljer; sorteringsscope bevares. Finansielle tal åbner datagrundlag; absolutter er neutrale. MarketUI viser neutral manglende dagsreference i stedet for udokumenterede rå dailyChange-farver. Journalen bevarer godkendt-forslag≠fill og bruger provider status_time hvor kendt, ellers tydelig observeret-status. HOT WATCH current/history læses separat, historik har before-pagination, gamle sessioner skjuler ikke nye. ERROR/DEGRADED forbliver synlige under filtre. Radar-optællinger anvender filtrene ved første render. Ingen beskyttet motor-/strategi-/polling-/scheduler-/trade_service-fil er ændret.

**Resterer før reviewaflevering:** Frys kode; kør én endelig fuld regression og browser på seneste små ændringer. Skriv faktisk individuel T01–T28/H01–H08-resultatrapport med syntetisk kontra livebegrænsning, kopier screenshots til docs, opdatér impact record og denne handoff. Bekræft alle runtimefiler i installer, checksums og beskyttede filer. Push kun WIP. Ingen release/installation/normalbranch. END_TO_END_DATA_CONTRACT.md og HOTWATCH_ENGINE_DATA_CONTRACT.md findes allerede og skal med i reviewleverancen. Hele den selvstændige motor er stadig fase1–2; backtest/shadow/ny strategiaktivering er ikke implementeret. Live close/cashflows/FX/kalender/EODHD/hosting er ikke verificeret og må ikke markeres PASS ud fra syntetiske tests.
