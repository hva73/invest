# ESCAPE Invest v2.5 – releasekandidat

Status: installeret 12. november 2026 ca. 15:36 UTC. Ejergodkendt og installeret SHA: `483a4b55ce4381e42ffb828125c9bcc0807cc8ba`. [Issue #57](https://github.com/hva73/invest/issues/57) er releasejournal. En senere dokumentationscommit er ikke den installerede SHA.

## Indhold siden v2.4

- Mobil og signalflow: tydeligere overblik, entydigt depot ved handelsgennemgang, manuel depotvej for blokerede eller historiske salgssignaler og klarere kandidatfilter (#80, #84). Dagens udvikling vises med grundlaget siden første måling (#96); teksten er endnu ikke klikbar.
- Beholdninger og Collection: undgår at tælle Collection-referencer som direkte beholdninger og foretrækker opdateret positionsbevis (#59).
- HOT WATCH: genvurdering af kandidater, verificeret US-feedmatch og korrekt særskilt exit-status (#82, #83, #85).
- Sector Intelligence: ensartet valuta- og kostgrundlag, kontanter og manglende scope/positioner, tidsgrundlag og markering af delvise eller estimerede tal (#79, #86, #88, #89, #91, #93, #95).
- Effektivitet og samarbejde: færre databaseblokerende rapportopslag samt forbedret kø for Projects-status (#81, #90).

## Uden for kandidaten

Åbne ændringer #60, #87, #92 og #94 indgår ikke. Nye ændringer kan kun medtages, hvis de er nødvendige for releasen og kandidaten derefter testes og identificeres på ny.

## Test og drift

- [Python 3.11 CI](https://github.com/hva73/invest/actions/runs/43244147126) bestod 411 + 15 tests; [mobil-/desktopbrowser-CI](https://github.com/hva73/invest/actions/runs/43244147736) bestod på identisk filtræ.
- Serverpreflight viste tilstrækkelig kvote og verificerede den seneste backup. [Deploy](https://github.com/hva73/invest/actions/runs/43249227731) meldte fuldført, service gendannet, backupoprydning OK og ingen recovery nødvendig.
- [Separat driftskontrol](https://github.com/hva73/invest/actions/runs/43249685514) viste installeret deklareret SHA, database OK, to Passenger-processer samt én worker og supervisor med friske heartbeats. Rapport- og kandidatopslag svarede efter installationen.
- Data er øjebliksbilleder. En faktisk brokerordre, fysisk mobilafprøvning og signalstyret salg af en enkelt aktie i Collection er ikke verificeret. Dagens udvikling er ikke klikbar.

Eksisterende produktionsdata, handelsmandat og brokerordrer ændres ikke af releaseforberedelsen. Et grønt CI-resultat er ikke liveaccept.
