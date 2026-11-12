# ESCAPE Invest v2.5 – releasekandidat

Status: under samlet test og uafhængigt review. Produktionsinstallation kræver særskilt ejergodkendelse af den præcise release-SHA. [Issue #57](https://github.com/hva73/invest/issues/57) er releasejournal.

## Indhold siden v2.4

- Mobil og signalflow: tydeligere overblik, entydigt depot ved handelsgennemgang, manuel depotvej for blokerede eller historiske salgssignaler og klarere kandidatfilter (#80, #84). Dagens udvikling vises med grundlaget siden første måling (#96); teksten er endnu ikke klikbar.
- Beholdninger og Collection: undgår at tælle Collection-referencer som direkte beholdninger og foretrækker opdateret positionsbevis (#59).
- HOT WATCH: genvurdering af kandidater, verificeret US-feedmatch og korrekt særskilt exit-status (#82, #83, #85).
- Sector Intelligence: ensartet valuta- og kostgrundlag, kontanter og manglende scope/positioner, tidsgrundlag og markering af delvise eller estimerede tal (#79, #86, #88, #89, #91, #93, #95).
- Effektivitet og samarbejde: færre databaseblokerende rapportopslag samt forbedret kø for Projects-status (#81, #90).

## Uden for kandidaten

Åbne ændringer #60, #87, #92 og #94 indgår ikke. Nye ændringer kan kun medtages, hvis de er nødvendige for releasen og kandidaten derefter testes og identificeres på ny.

## Afventer

- Samlet regression og browserkontrol på den endelige releasekode, samt uafhængigt review.
- Frisk serverkontrol af præcis baseline, kvote, database/WAL/journal, backup og recovery.
- Ejerens godkendelse af præcis SHA og efterfølgende faktisk installations- og driftskontrol.

Eksisterende produktionsdata, handelsmandat og brokerordrer ændres ikke af releaseforberedelsen. Et grønt CI-resultat er ikke liveaccept.
