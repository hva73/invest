# Projects-samarbejde: test og Issue-feedback – 10. november 2026

## Live-test af slettet testclaim

[Actions-run 42872907388](https://github.com/hva73/invest/actions/runs/42872907388) udførte den faktiske `claim()` på den separate engangsgren `codex/replay-history-disposable`, oprettede en ny tilfældig syntetisk testpost og slettede kun denne post. Det efterfølgende kald med samme ID blev blokeret, fordi GitHub returnerede postens commithistorik. Jobloggen rapporterede PASS. Ingen Projects-token blev anvendt, og journalgrenen blev ikke ændret.

Dette bekræfter den konkrete historiktest. Det garanterer ikke beskyttelse mod alle samtidige mutationer, historikoperationer eller angribere. Testworkflowets trigger er efterfølgende begrænset til manuelt dispatch.

## Automatisk tilbagemelding på Issue #4

Det eksisterende automatiske replay-dry-run-workflow har fået et separat `report-dry-run`-job. Jobbet har read-only code checkout, `issues: write` på workflowets GITHUB_TOKEN og intet Projects-secret. Det skriver en fast, klart mærket teststatus og link til Actions-kørslen på eksisterende Issue #4. Hvis status allerede er rapporteret af `github-actions[bot]` for samme run og attempt, oprettes der ikke en ny kommentar. Hvis GitHub ikke kan læse alle kommentarer eller resultatet er usikkert, fejler jobben uden at oplyse credential.

[Actions-run 42873293665](https://github.com/hva73/invest/actions/runs/42873293665) bestod; både dry-run-jobbet og feedback-jobbet sluttede success. Den efterfølgende [Issue-kommentar](https://github.com/hva73/invest/issues/4#issuecomment-6775444922) blev læst tilbage og var oprettet af `github-actions[bot]`. Positive, dublerede og ubetroede markører samt regressionskontroller: 22 lokale tests bestod. Fejlrapporteringen er lokalt testet; et bevidst fejlet live-job er ikke kørt i denne fase.

## Kvarstående begrænsninger

GitHubs dokumentation for `UpdateProjectV2ItemFieldValueInput` indeholder ikke et felt til forventet tidligere værdi eller versionskontrol. En læsning før skrivning kan derfor ikke garantere, at en manuel opdatering mellem læsning og mutation ikke overskrives. Den nuværende concurrency-gruppe serialiserer kun det specifikke workflow, og en enkelt journalclaim er ikke en global item-lås.

Default branchens workflowkode og repo-brede Actions-skriverettigheder skal beskyttes, og Projects-skriveadgang er endnu ikke verificeret. Agentspecifik identitet kan ikke udledes af den fælles GitHub bruger/App. Ingen Projects-statusskrivning er implementeret eller aktiveret; den første reelle ændring kræver fortsat særskilt ejer-godkendelse. Issue #11 forbliver åben.

GitHub-kilde: https://docs.github.com/en/graphql/reference/projects#updateprojectv2itemfieldvalueinput
