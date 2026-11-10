# Projects replay: live Actions-test, 10. november 2026

## Gennemført

Den afgrænsede test [escape-projects-replay-test.yml](../.github/workflows/escape-projects-replay-test.yml) reagerer kun på en kommentar med testformatet på issue #4 fra det tilladte GitHub-bruger-ID. Koden kontrollerer desuden den faktiske kommentar, App-ID, redigeringshistorik, projekt, item og forventet/ønsket status. Kodecheckout er fastlåst til commit `0c679bedbd5a1ccbf07f0da997107a43eb585d99`.

[projects_replay_actions_test.py](projects_replay_actions_test.py) genbruger den eksisterende dry-run og kalder den faktiske `claim()` med workflowets `GITHUB_TOKEN` på den eksisterende isolerede testgren `codex/projects-replay-isolated-test`. Efter claim genlæses kommentar og Project-kort; forskelligt resultat eller en fejl stopper testen. Project-token bruges kun til læsning. Jobbet har `contents: write` til testjournalen, som er en **repository-bred** tokenrettighed; dette er ikke teknisk begrænset til testgrenen af tokenet selv. Der foretages ingen Projects-mutation. Kørselens concurrency-gruppe er fælles for hele testen af #4 og annullerer ikke aktive jobs. Dette er ingen global lås mod mennesker, andre workflows eller scripts. GitHub kan erstatte ventende jobs, og rækkefølge/FIFO garanteres ikke.

- [Automatisk kørsel 42861393806](https://github.com/hva73/invest/actions/runs/42861393806), første forsøg: PASS. Kommentar 6773815668 udløste workflowet; Project-data blev læst, claim oprettet og data genlæst. Journalfilen blev læst tilbage.
- Samme run, forsøg 2: BLOCKED/failure ved genafspilning af den samme kommentar. Dette er forventet og er ikke en produktionsfejl.
- [42861588088](https://github.com/hva73/invest/actions/runs/42861588088) og [42861591074](https://github.com/hva73/invest/actions/runs/42861591074): to næsten samtidige anmodninger PASS. Valideringssteppene kørte hhv. 17:07:14–17:07:19 og 17:07:27–17:07:31 UTC, altså ikke samtidig i denne observation.
- [42861649520](https://github.com/hva73/invest/actions/runs/42861649520): forkert forventet status gav BLOCKED/failure, og ingen journalfil for dette ID fandtes bagefter.
- 15 lokale tests bestod, inklusive simuleret ændring mellem læsninger og fejl ved claim.

Den underliggende manuelle dry-run skriver stadig, at **dens egen** replaybeskyttelse ikke findes. Det er korrekt for den oprindelige manuelle vej; den afgrænsede Actions-test tilføjer journalregistrering. Fejlloggen er bevidst generisk; se run, request og journalreadback ved fejlsøgning.

## Sikkerhedsgrænse og åbne punkter

GitHubs branch-liste angiver testgrenen og default-grenen `codex/escape-development` som `protected: false`; repository-rulesets-listen var tom. Beskyttelsesdetaljer kan ikke læses gennem connectoren (HTTP 403). Det er ikke bevis for, at ingen andre begrænsninger findes, men testen kan ikke bruges som dokumentation for journalbeskyttelse mod sletning eller omskrivning.

**Ingen Projects-skrivefunktion er implementeret eller aktiveret.** Før en sådan funktion kan komme på tale skal journalens beskyttelse og genopretning dokumenteres, risikoen ved repo-bred `contents: write` og ubeskyttet default branch håndteres, og konkurrerende ændringer uden for workflowet vurderes. Den enkelte claim forhindrer ikke to forskellige ID'er i at påvirke samme kort og giver ikke atomisk compare-and-set. Menneskelige statusændringer kan ske efter sidste læsning. Automatisk Issues-behandling er kun en test af issue #4, og fælles GitHub-bruger/App-ID skelner ikke de to agenter. Selvstændig live-test fra ChatGPT mangler fortsat. Reel Projects-statusændring kræver særskilt ejer-godkendelse.

Ingen produktionssystemer eller handelsmandater blev tilgået eller ændret.
