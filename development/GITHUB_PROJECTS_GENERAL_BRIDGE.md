# ESCAPE Projects: fælles statusbro

Broen behandler statusanmodninger på eksisterende Issues #1 og #3–#999 i `hva73/invest` for Project `hva73/1`. Den opretter ikke Issues eller Project-items og lukker ikke Issues. Inventaret viser alle repository-Issues på tavlen, herunder nyere kort; statusbroen accepterer kun entydige eksisterende, aktive kort.

## Brug

En godkendt agent skriver en ny kommentar på det pågældende Issue:

```text
ESCAPE_PROJECTS_WRITE_V1 {"request_id":"32-lowercase-hex-characters","expected_status":"Backlog","desired_status":"In progress"}
```

Eksemplet viser formen; `request_id` skal erstattes med 32 faktiske, entydige små hextegn, og statusnavnene skal præcist matche eksisterende Project-optioner. Brug altid den aktuelt aflæste status som `expected_status`. En ny handling kræver et nyt ID. Dry-run bruger et separat præfiks.

GitHub Actions verificerer den godkendte GitHub-bruger og App, at kommentaren ikke er redigeret, projekt, eksisterende entydigt aktivt item og aktuel status. Den registrerer en engangsclaim i den beskyttede journal, kontrollerer igen, skriver højst én status og læser resultatet tilbage. Audit eller fejl rapporteres på samme Issue. #3 kan kun flyttes mellem Backlog, In progress og In review, indtil ejerens krav til færdiggørelse er opfyldt og reglerne ændres særskilt.

## Fejl og samtidighed

Ved konflikt, manglende data eller uautoriseret afsender stoppes handlingen. Hvis skrivning eller readback har usikkert udfald, må samme ID ikke automatisk genafspilles, og der foretages ingen automatisk rollback; afstem kort, journal og Actions-log som beskrevet i [recoveryvejledningen](GITHUB_PROJECTS_WRITE_RECOVERY.md).

De koordinerede workflows deler én kø. `queue: max` tillader op til 100 ventende runs; yderligere runs kan blive annulleret og skal følges op i Actions. Køen garanterer ikke rækkefølgen af afsendelser. Undgå manuelle kortflytninger, mens køen arbejder: GitHub har ingen atomisk expected-status-kontrol, og en samtidig manuel/ekstern ændring kan blive overskrevet. Ejeren har accepteret denne restrisiko for reversible opgavestatusser.

De to agenters forbindelser optræder med samme GitHub-bruger/App-identitet. Adgangskontrollen verificerer forbindelsen, men kan ikke sikkert bevise, om en kommentar kom fra Codex eller ChatGPT. Reglen om PR til default-branchen kræver aktuelt 0 uafhængige godkendelser; en aktør med tilstrækkelig repository-skriveret kan oprette og merge sin egen PR.

## Afgrænsning og test

Udviklingsgrenen og journalgrenen er beskyttet af separate GitHub-regler. Projects-tokenet ligger i det eksisterende Actions-secret; workflowets `GITHUB_TOKEN` har repository-bred `contents: write` og `issues: write` i writer-jobbet. Broen må ikke bruges til handel, deployment-godkendelser, handelsmandater eller automatisk issue-lukning.

Issue #4 er efter ejerens særskilte godkendelse flyttet tilbage fra Backlog til In progress og derefter læst igen i en separat Actions-kørsel. Den generelle kode er testet med simulerede svar for alle tilladte Issue-numre, audit, forkert status og usikkert udfald. Både Codex og ChatGPT har efterfølgende dokumenteret en faktisk anmodning gennem den generelle writer; se testresultaterne nedenfor og Issue #11.

## Verificeret status 10. november 2026

[PR #21](https://github.com/hva73/invest/pull/21) aktiverede den generelle bro. Codex flyttede #11 Backlog → In progress via [Actions 42889702635](https://github.com/hva73/invest/actions/runs/42889702635); [separat inventar/readback 42889798135](https://github.com/hva73/invest/actions/runs/42889798135) bekræftede både #4 og #11 som In progress og ét aktivt kort for #1 og #3–#16. Dette snapshot kan ændre sig. ChatGPT sendte derefter en selvstændigt dokumenteret reel anmodning på #1, Backlog → In progress, som bestod i [Actions 42891046911](https://github.com/hva73/invest/actions/runs/42891046911), med [audit](https://github.com/hva73/invest/issues/1#issuecomment-6777866383). GitHub-identiteten skelner ikke de to sessioner kryptografisk.
