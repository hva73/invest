# ESCAPE Invest – mobil, dokumenteret designaccept (15.11.2026)

**Ejers beslutning:** Den senest konkret godkendte skærm er facit. Ingen egne designvalg. Grøn CI er nødvendig, men ikke i sig selv visuel accept. Denne kontrol gælder kun præcis SHA, ikke løbende branch-head. Ingen ordre/deploy her.

## Kilder (faktisk lokaliseret og visuelt læst)
- **Godkendt KØB/SALG-reference**: [Skærmbillede 2026-11-14 kl. 16.23.44.png](https://chatgpt.com/library?file_id=libfile_023eefa11d9c8191bd2ef3428e34f8b1&account_id=personal). To iPhone-skærme side om side; KØB og SALG. Grøn/rød signalfarve og bundknap, lille Ignorer, Hvorfor?, kompakt top, graf, Top, stiplet Gns. købskurs ved position, Dag/Uge/Måned/År. Tal i billedet er illustration, ikke aktuelle Pluto-tal.
- **Fejlobservationer, IKKE nye designs**: [IMG_8542](https://chatgpt.com/library?file_id=libfile_42c0b86939348191b8c547119f8863ee&account_id=personal) (for høje beholdningskort), [IMG_8543](https://chatgpt.com/library?file_id=libfile_fa83cbeb6b948191be95227d2d54f8f2&account_id=personal) (oversigt/overlap), [IMG_8544](https://chatgpt.com/library?file_id=libfile_f0339b3961dc81919a6c07e010685991&account_id=personal) (position/tomplads/disabled sælg).
- **CI-bevis på tidligere præcis commit**: [GitHub-run 43701197757](https://github.com/hva73/invest/actions/runs/43701197757), SHA `e9df5dddf726fc3d93af946ad03fb2048f77f65f`, PASS; screenshot-artifact `approved-mobile-repair`, artifact-id `14156781252`, SHA256 `8fb52f35faa7a97cbb216a3d5875afddba86fd30dbe4eb090952f715ae5d5bc0`.
- Denne gamle artifact indeholder `daily-parity-screens/oversigt-390.png`, `visual-review/position-390.png`, men **ikke** `signal-buy-390.png` / `signal-sell-390.png`. Derfor er den IKKE en fuld visuel godkendelse.

## Fem skærmes status (må ikke markeres godkendt uden billedpar fra samme endelige release-SHA)

| Skærm | Seneste reference | Faktisk render og kilde | Status |
|---|---|---|---|
| Oversigt | Godkendt ejerchat – seneste originale billede skal knyttes; IMG_8543 er kun fejl | CI `oversigt-390.png` på e9df5dd (syntetisk) | UAFKLARET: ikke sammenholdt med original godkendelse |
| Beholdningskort | Godkendt ejerchat, dagstal **beløb + %**, siden køb og siden sidst | CI `oversigt-390.png` på e9df5dd; IMG_8542 er tidligere driftsfejl | UAFKLARET: ikke referenceverificeret / reelle Pluto-data |
| Position | Godkendt ejerchat: kompakt, top, gns. købskurs, graf, ingen ekstra statuslinjer | CI `position-390.png` på e9df5dd; IMG_8544 er tidligere driftsfejl | UAFKLARET: ikke referenceverificeret; NOVOB-kurs/SELL stadig åben |
| KØB | Godkendt billede 16.23.44 (venstre) | Kræv `visual-review/signal-buy-390.png` på slut-SHA | **BLOKERET** indtil screenshot og direkte sammenligning |
| SALG | Godkendt billede 16.23.44 (højre) | Kræv `visual-review/signal-sell-390.png` på slut-SHA | **BLOKERET** indtil screenshot og direkte sammenligning |

## Hvad der skal kontrolleres ved hvert billedpar
Sammenlign skærmbillede direkte mod ejerens originale billede med samme viewport. Registrér både afvigelser og "ingen afvigelser" eksplicit for layout, labels, handlinger, farver, grafens placering, scroll, tooltip og manglende data. Køb/salg bruger isolerede syntetiske signaler – **ingen broker-write**. Reelt NOVOB-/Pluto-kurs- og salgsproblem håndteres særskilt af agent 3; ingen EODHD-historik som aktuel Pluto-kurs. Knapper og graf skal fungere på lange navne og manglende data.

## Automatisk dokumentation
Workflow `.github/workflows/approved-mobile-visual-repair.yml` kører allerede browserkontroller og er opdateret til at inkludere `tests/browser_signal_push_detail.py` og **kræve** fem screenshots for oversigt, position, KØB og SALG, før CI kan blive grøn. Artifact indeholder screenshots ved succes; slutcommit skal kontrolleres igen efter merge/integration med #153. Dette producerer bevismateriale, men erstatter ikke menneskelig/ejers visuel sammenligning.

**Acceptgrænse:** 0 ikke-afstemte designafvigelser, 0 manglende referencer til berørte skærme, grønt CI og faktisk browserreadback fra præcis release-SHA, derefter særskilt ejer-go og post-installation-readback. Indtil da **IKKE VISUELT GODKENDT / IKKE KLAR TIL RELEASE**.
