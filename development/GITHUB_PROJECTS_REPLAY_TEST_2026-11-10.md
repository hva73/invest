# Projects replay: isoleret GitHub-test, 10. november 2026

## Resultat

Syntetiske anmodninger blev dannet med `prepare_claim` fra den eksisterende prototype. To uafhængige, parallelle GitHub Contents API-oprettelser med samme request-ID og forskellige bindingsdata blev sendt til den særskilte testgren `codex/projects-replay-isolated-test`. Én lykkedes (commit `3fd95c4180a65eaf1cd5a06ab1b6c393415b8eed`), én fik HTTP 422. Den oprettede fil blev læst tilbage og matchede den første anmodning. En efterfølgende genafspilning fik også 422.

Fire samtidige oprettelser af et andet syntetisk request-ID gav én succes (commit `2b557d53992c3d10b38c9635461cc99bcd9a2455`) og tre HTTP 422-afvisninger. Den gemte fil blev læst tilbage og matchede den forventede binding. Tretten lokale tests for dry-run og replay bestod.

Testen brugte GitHub-connectorens create-file-operation, som anvender Contents API uden blob-SHA, samt prototypens egen payloadgenerator. Den eksekverede **ikke** prototypens `claim()` direkte mod GitHub og brugte ikke Actions-token eller workflow. Den demonstrerer observeret oprettelseskonflikt i disse forsøg, men ikke en komplet eller formelt garanteret replaybeskyttelse under alle samtidige forhold.

## Fortsat blokeret

- Journalgrenen, dens beskyttelse mod sletning og historikændring, sikker genopretning samt den præcise Actions-skriverettighed er endnu ikke demonstreret. Forsøg på at kontrollere branch protection via den aktuelle connector gav HTTP 403; beskyttelse er derfor ikke bekræftet.
- Selve `claim()` skal live-testes med den planlagte Actions-identitet og journalgren; ukendt resultat skal forblive fail-closed.
- En claim for samme ID er ikke en lås for forskellige requests mod samme item og beskytter ikke mod manuelle Projects-ændringer.
- Issue-kommentarer fra begge agenter har samme verificerede GitHub-bruger/App-identitet; disse metadata skelner ikke mellem agenterne.
- Automatisk udløsning fra begge agenter, adgangskontrol før secret-brug, og readback er endnu ikke testet. En reel Projects-ændring kræver særskilt ejer-godkendelse.

Ingen workflow er ændret eller aktiveret, ingen projekttavle/status ændret, ingen credentials tilføjet, og ingen produktions- eller handelsændring er foretaget. Issue #11 forbliver åben.
