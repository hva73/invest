# Projects journal protection – 10. november 2026

GitHub API bekræfter ruleset [26966131](https://github.com/hva73/invest/rules/26966131), aktivt for præcis `refs/heads/codex/projects-replay-isolated-test`, med `deletion` og `non_fast_forward`, ingen bypass-aktører og `current_user_can_bypass: never`. Det er en konfigurationskontrol, ikke en praktisk test af afvisning.

Efter aktivering udløste kommentar 6774957556 [Actions-run 42869841134](https://github.com/hva73/invest/actions/runs/42869841134): PASS, claim blev oprettet i journalen og læst tilbage, og kortet genlæst. Ingen Projects-mutation.

Journalreglerne beskytter grenen mod sletning og historien mod non-fast-forward. De forbyder ikke i sig selv, at en journalfil ændres eller slettes i et nyt, almindeligt commit. Replayprototypen kontrollerer nu filens commit-historik på journalgrenen før create-only-oprettelse; eksisterende historik, ugyldigt svar eller fejl blokerer. 16 lokale tests bestod. [Actions-run 42870110984](https://github.com/hva73/invest/actions/runs/42870110984), forsøg 1: ny claim og genlæsning PASS med den opdaterede kode; forsøg 2 med samme kommentar: BLOCKED som forventet. På den særskilte, ubeskyttede engangsgren `codex/replay-history-disposable` blev en syntetisk fil oprettet og slettet; GitHubs commits API returnerede fortsat filens historik. Det var ikke en end-to-end-test af prototypen mod en slettet journalpost og beviser ikke racefri sikkerhed.

To agenters automatiske test er nu dokumenteret: Codex [42861393806](https://github.com/hva73/invest/actions/runs/42861393806) og ChatGPT [42867716421](https://github.com/hva73/invest/actions/runs/42867716421), begge før det nye ruleset; GitHub identificerer forbindelserne med samme bruger og App.

## Åbne sikkerhedspunkter

- Ingen forsøg på at slette eller force-pushe den eksisterende journalgren er foretaget. Rulesettet matcher kun den gren, og connectoren har ingen administration til at beskytte en anden gren. Den særskilte gren `codex/replay-protection-disposable` er oprettet med ufarlig markør og afventer tilsvarende beskyttelse, før afvisningerne testes.
- Historikopslag og filoprettelse er separate operationer. Et historiktjek og grenregler alene garanterer ikke mod alle samtidige ændringer, sletning/genoprettelse eller kompromitterede aktører. GITHUB_TOKEN har repo-bred contents-skriveret. Default-branchens workflowkode og Projects-secret skal også beskyttes.
- Concurrency-gruppen serialiserer kun testworkflowet for #4. Den er ikke en fælles lås mod mennesker eller andre workflows, og FIFO er ikke garanteret. GitHub Projects atomisk compare-and-set er ikke dokumenteret. En ændring efter sidste læsning kan stadig give konflikt.
- Projects-write er ikke implementeret eller aktiveret. En reel statusændring kræver ejerens særskilte godkendelse. Issue #11 forbliver åben.

Ingen tavlestatus eller produktionssystem blev ændret.


## Live-test af reglernes håndhævelse

Ejeren tilføjede `refs/heads/codex/replay-protection-disposable` til ruleset 26966131 uden at fjerne journalgrenen. GitHub API bekræftede begge targets, aktiv enforcement, deletion/non_fast_forward og tom bypass-liste ved connectorens læsning. Actions-identitetens eget opslag bekræftede `current_user_can_bypass: never`; denne identitet får ikke returneret bypass-listen, så listen er separat kontrolleret gennem connectoren.

[Actions-run 42872131340](https://github.com/hva73/invest/actions/runs/42872131340) gennemførte på engangsgrenen begge forespørgsler: sletning og non-fast-forward blev afvist med en genkendt regelafvisning. Scriptet kontrollerede efter hvert forsøg, at grenens commit var uændret. Et separat connectoropslag viste fortsat commit `382fca6f8760d2b9449588157a5f5a75b2e12389` og intakt testmarkør. Den eksisterende journalgren blev ikke udsat for disse forsøg, og ingen Projects-secret blev brugt.

Første teststarter blev sprunget over eller stoppede sikkert: Actions-tokenets ruleset-svar udelader bypass-aktørlisten, selv om connectoren kan se den. Dette blev diagnosticeret uden rå credential- eller API-logging, og testen blev justeret til at kræve, at den konkrete Actions-identitet ikke kan bypass'e. Disse fejlslagne teststarter kan have sendt GitHub-fejlmail. Efter den beståede test blev workflowet begrænset til manuel start.

**Fortsat begrænsning:** Resultatet verificerer de to specifikke grenregler for denne Actions-identitet og engangsgren. Det beviser ikke, at eksisterende journalfiler ikke kan ændres i fast-forward commits, at journalen eller default-branch er sikret mod alle aktører, eller at status kan opdateres atomisk mod mennesker og andre workflows. Projects-write forbliver deaktiveret; første reelle ændring kræver særskilt ejer-godkendelse.
