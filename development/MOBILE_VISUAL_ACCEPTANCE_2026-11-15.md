# ESCAPE Invest – mobil, dokumenteret designaccept (15.11.2026)

**Ejers beslutning:** Den senest konkret godkendte skærm er facit. Ingen egne designvalg. Grøn CI er nødvendig, men ikke i sig selv visuel accept. Denne kontrol gælder kun præcis SHA, ikke løbende branch-head. Ingen ordre/deploy her.

## Kilder (faktisk lokaliseret og visuelt læst)
- **Godkendt KØB/SALG-reference**: [Skærmbillede 2026-11-14 kl. 16.23.44.png](https://chatgpt.com/library?file_id=libfile_023eefa11d9c8191bd2ef3428e34f8b1&account_id=personal). To iPhone-skærme side om side; KØB og SALG. Grøn/rød signalfarve og bundknap, lille Ignorer, Hvorfor?, kompakt top, graf, Top, stiplet Gns. købskurs ved position, Dag/Uge/Måned/År. Tal i billedet er illustration, ikke aktuelle Pluto-tal.
- **Fejlobservationer, IKKE nye designs**: [IMG_8542](https://chatgpt.com/library?file_id=libfile_42c0b86939348191b8c547119f8863ee&account_id=personal) (for høje beholdningskort), [IMG_8543](https://chatgpt.com/library?file_id=libfile_fa83cbeb6b948191be95227d2d54f8f2&account_id=personal) (oversigt/overlap), [IMG_8544](https://chatgpt.com/library?file_id=libfile_f0339b3961dc81919a6c07e010685991&account_id=personal) (position/tomplads/disabled sælg).
- **CI-bevis på tidligere præcis commit**: [GitHub-run 43701197757](https://github.com/hva73/invest/actions/runs/43701197757), SHA `e9df5dddf726fc3d93af946ad03fb2048f77f65f`, PASS; screenshot-artifact `approved-mobile-repair`, artifact-id `14156781252`, SHA256 `8fb52f35faa7a97cbb216a3d5875afddba86fd30dbe4eb090952f715ae5d5bc0`.
- Denne gamle artifact indeholder `daily-parity-screens/oversigt-390.png`, `visual-review/position-390.png`, men **ikke** `signal-buy-390.png` / `signal-sell-390.png`. Derfor er den IKKE en fuld visuel godkendelse.

## Verificeret designkontrol på produktsnapshot 3dc7db43e89390279bf02f022fb192a49626a6d7

- **CI PASS på den præcise produktcommit**: [run 43703295117](https://github.com/hva73/invest/actions/runs/43703295117), screenshotartifact `approved-mobile-repair`, id `14157437266`, SHA256 `d37c2c2392a29e27d03f4d19165aede6194ab7961b61462abb08e0b94a776f8e`. [Desktopreview 43703295116](https://github.com/hva73/invest/actions/runs/43703295116) kørte på samme produkt-SHA (reviewets endelige status skal kontrolleres særskilt).
- **Direkte gennemset på 390 px**: `visual-review/signal-buy-390.png` og `signal-sell-390.png` mod originalen 16.23.44. Header/understregning, ticker og navn, kurs med beløb og procent, graf med Top og betinget gennemsnitlig købskurs, Dag/Uge/Måned/År, KØB: Eksisterende position/Dagsændring/Måned/År, SALG: Position/Gns. købskurs/Afkast, Ignorer og enkelt bundplaceret KØB/SALG svarer til referenceelementerne. Konkret tekstombrydningsfejl i `Dagsændring` og smalt lodret kursfelt er rettet og genkontrolleret i dette artifact. Long-name case TSM er med. Kun datatal, instrument og faktisk grafkurve afviger naturligt, da CI er syntetisk; kilden og farver følger datapåvirkningen.
- **Køb uden eksisterende position** dokumenteret separat i `signal-buy-no-position-390.png`; der gættes ikke beholdning eller købskurs. Brokerkald til handler er ikke udført.
- **Ikke samme som en personlig LIVE-accept**: Integreret release-SHA, faktisk iPhone og personlig NOVOB-position skal stadig kontrolleres efter samling/installation. Ingen falsk påstand om frisk Pluto-kurs eller aktiv salgsknap.

## Fem skærmes status (slutkandidaten skal gentestes efter integration)

| Skærm | Seneste reference | Faktisk render og kilde | Status |
|---|---|---|---|
| Oversigt | Godkendt ejerchat – seneste originale billede skal knyttes; IMG_8543 er kun fejl | CI `oversigt-390.png` på 3dc7db (syntetisk) | UAFKLARET: ikke sammenholdt med original godkendelse |
| Beholdningskort | Godkendt ejerchat, dagstal **beløb + %**, siden køb og siden sidst | CI `oversigt-390.png` + `position-390.png` på 3dc7db; IMG_8542 er tidligere driftsfejl | UAFKLARET: ikke referenceverificeret / reelle Pluto-data |
| Position | Godkendt ejerchat: kompakt, top, gns. købskurs, graf, ingen ekstra statuslinjer | CI `visual-review/position-390.png` på 3dc7db; IMG_8544 er tidligere driftsfejl | UAFKLARET: ikke referenceverificeret; NOVOB-kurs/SELL stadig åben |
| KØB | Godkendt billede 16.23.44 (venstre) | `signal-buy-390.png` på 3dc7db, visuelt sammenholdt med 16.23.44 | **AFSTEMT på syntetisk skærm**, men kræver samme render på endelig integrations-SHA |
| SALG | Godkendt billede 16.23.44 (højre) | `signal-sell-390.png` på 3dc7db, visuelt sammenholdt med 16.23.44 | **AFSTEMT på syntetisk skærm**, men kræver samme render på endelig integrations-SHA |

## Hvad der skal kontrolleres ved hvert billedpar
Sammenlign skærmbillede direkte mod ejerens originale billede med samme viewport. Registrér både afvigelser og "ingen afvigelser" eksplicit for layout, labels, handlinger, farver, grafens placering, scroll, tooltip og manglende data. Køb/salg bruger isolerede syntetiske signaler – **ingen broker-write**. Reelt NOVOB-/Pluto-kurs- og salgsproblem håndteres særskilt af agent 3; ingen EODHD-historik som aktuel Pluto-kurs. Knapper og graf skal fungere på lange navne og manglende data.

## Automatisk dokumentation
Workflow `.github/workflows/approved-mobile-visual-repair.yml` kører allerede browserkontroller og er opdateret til at inkludere `tests/browser_signal_push_detail.py` og **kræve** fem screenshots for oversigt, position, KØB og SALG, før CI kan blive grøn. Artifact indeholder screenshots ved succes; slutcommit skal kontrolleres igen efter merge/integration med #153. Dette producerer bevismateriale, men erstatter ikke menneskelig/ejers visuel sammenligning.

**Acceptgrænse:** 0 ikke-afstemte designafvigelser, 0 manglende referencer til berørte skærme, grønt CI og faktisk browserreadback fra præcis release-SHA, derefter særskilt ejer-go og post-installation-readback. Indtil da **IKKE VISUELT GODKENDT / IKKE KLAR TIL RELEASE**.

## Supplerende faktisk billedreview (15.11, Codex 2)
På **SHA 3dc7db43e89390279bf02f022fb192a49626a6d7** gennemførte [CI-run 43703295117](https://github.com/hva73/invest/actions/runs/43703295117) grønt, med screenshot-archive **14157437266** (23 PNG-filer inkl. `visual-review/signal-buy-390.png`, `signal-sell-390.png`, `position-390.png` og `daily-parity-screens/oversigt-390.png`). De faktiske KØB/SALG-billeder er visuelt gennemgået mod originalen fra 14.11 kl.16.23.44:
- **Bekræftet i faktisk render:** signaloverskrifterne KØB/SALG, "Hvorfor?", diskret "Ignorer", ticker/kurs, Dag/Uge/Måned/År, én tydelig bundknap, farvekodning og kort statslinje.
- **Fundet afvigelse:** KØB-graf med eksisterende beholdning viste stiplet "Gns. købskurs" (godkendt seneste regel: købsgraf uden købskurs). **Korrigeret** i `46d1d7df4f9f1f05c300c1a34ba59fc5bf9c8e1e`; regression tilføjet i `255abe7e46ce2b582a5d7599fc414804cd3d848a`. Kræver ny screenshot-CI før visuel accept. SALG beholder entry-linje.
- **Resterende visuel forskel på 3dc7db4:** appens graf er fladere/anderledes placeret end referencens kurve og teksten "Top" er placeret nedenfor linjen i syntetisk TSM-eksempel. Grundlæggende markeringer og 4 perioder er funktionelt testet, men designparitet er **ikke** erklæret. Markedsdata/kurveform må naturligvis variere med instrumentet.
- **Særskilt manglende designreference:** originalt godkendte skærmbilleder for *oversigt, beholdningskort og position* er ikke identificeret som konkrete tilgængelige filer. IMG_8542/43/44 er kendte fejlobservationsbilleder. Accepter aldrig disse tre ved at bruge fejlbillederne som facit.

Bemærk at dette afsnit dokumenterer et **ældre præcist head**, ikke bevis for den senere samlede integrations-SHA. Tests skal genkøres for seneste version og billedparrene sammenholdes efter ændringen.
