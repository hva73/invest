# ESCAPE Development – GitHub Projects

Status 10. november 2026. Undersøgelsen omfatter Issues #3–#11 og påvirker hverken produktion, handler eller mandater.

## Konstateret adgang og begrænsning

- GitHub-connectoren kan læse og redigere repository-Issues og filer. De tilgængelige værktøjer omfatter ikke Projects V2 eller et generelt GraphQL-kald. ChatGPTs appindstilling tillader handlinger, men den indstilling er ikke dokumentation for GitHub OAuth-scopes, GitHub App-projektrettigheder eller et Projects-værktøj.
- `gh` 2.46.0 findes, men `gh auth status` melder ingen login. Både `gh project list --owner hva73 --format json` og `gh api graphql` afvises før kaldet: autentifikation mangler. Derfor kender vi ikke tokenets scopes, projektnummer, felter, eksisterende medlemskab eller faktisk adgang til tavlen. Intet scope eller samtykke er blevet ændret.
- Den anonyme repository-projektside viste ingen projekter tilknyttet repoet. Det udelukker ikke et personligt eller privat projekt. Listen kan ikke bruges til at fastslå, om #3–#11 er på ESCAPE Development.
- CLI-kontrollen `projects_audit.py` stopper korrekt uden credentials. Ingen live tilføjelse eller statusskift er udført. Et one-issue liveforsøg er **BLOKERET**, ikke bestået.

## Rettigheder og fælles adgang

For en klassisk OAuth-token angiver GitHub `read:project` til læsning og `project` til læsning og skrivning. `gh auth refresh -s project` ville ændre en eksisterende autorisation og skal ikke udføres uden ejerens aftale. GitHub Apps og fine-grained tokens bruger deres egne Projects-rettigheder og ejer-/ressourceadgang, ikke samme scope-model. At give Projects-adgang løser ikke i sig selv, at en agent mangler et eksponeret GraphQL-værktøj eller at `gh` mangler session. Ejeren skal vælge adgangsmetode og give kun nødvendige rettigheder; gem aldrig tokens i repo eller chat.

Codex kan anvende `gh` med en separat, passende autoriseret session. ChatGPT kan på nuværende dokumenterede forbindelse læse/skrive Issues, men ikke læse/skrive Projects V2. Fælles fuld adgang kræver en forbindelse/et værktøj for ChatGPT med konkrete Projects-V2-operationer og passende GitHub-rettigheder, eller en separat, godkendt integration med kontrolleret adgang. Det er ikke verificeret, at en sådan forbindelse er installeret; hævd ikke fuld agentadgang.

## Foreslået model

1. Eksisterende repository-Issue er den eneste opgaveidentitet. Beskrivelser, test, links og historik ligger i Issue; Project-item er en reference, ikke et nyt Issue.
2. Projects' indbyggede auto-add kan fremover tilføje matchende repository-Issues; eksisterende Issues backfilles særskilt efter fuld medlemskabskontrol. Auto-add kan også reagere, når et matchende Issue opdateres. Kontroller filter og eksisterende workflows før aktivering.
3. Projects' Status er autoritativ for arbejdsgang. Issue open/closed er særskilt; synkronisér kun entydige, udtrykkeligt besluttede overgange. At et Issue er åbent må aldrig nulstille I gang/Review/Driftstest til Backlog, og at en test er grøn må ikke automatisk betyde Færdig. Eksisterende close/Done-workflows skal gennemgås før aktivering for at undgå utilsigtet lukning.
4. Begge agenter bruger samme eksisterende Issue og statusfelt. Testresultater, blokeringer og liveaccept dokumenteres med dato, commit og evidens; intet produktionsresultat udledes af enhedstests.
5. Før automatisk statusændring skal et fremtidigt værktøj læse aktuel værdi og tilladte options, bruge entydig overgang, kontrollere samtidig ændring og læse tilbage. GitHubs feltmutation giver ikke i sig selv en dokumenteret atomisk compare-and-set; ved konkurrerende skribenter kræves derfor serialisering eller manuel afklaring. Ingen udrullet statusautomatik i denne leverance.

## Kontrol og én eksisterende Issue

Efter separat autorisation, i et miljø hvor `gh` er logget ind og har adgang:

```sh
gh auth status
gh project list --owner hva73 --format json
python development/projects_audit.py
```

Kontrollen vælger kun præcist ét åbent projekt ved navn `ESCAPE Development` hos `hva73`, læser alle sider, herunder arkiverede items, og viser Issues #3–#11 samt deres Status. Den fejler lukket ved manglende adgang, tvetydigt projekt eller ufuldstændig paginering. Hvis ejeren af projektet er en organisation frem for `hva73`, skal ejerskabet afklares før ændring af scriptets OWNER.

Som ikke-forstyrrende live-test: vælg ét Issue, der allerede er på tavlen, og kør eksempelvis `python development/projects_audit.py --add-one 3` **kun hvis #3 faktisk findes**. Scriptet genlæser medlemskab og skal afslutte uden mutation. Sammenlign status før/efter. Hvis opgaven ikke findes, er audit alene den sikre test; tilføjelse med `--add-one` er en eksplicit ændring og kan udløse et eksisterende GitHub auto-status-workflow. Kontrollér disse workflows inden tilføjelse. Scriptet opretter aldrig et nyt Issue og sætter aldrig selv Status. GitHub returnerer eksisterende item ved gentaget tilføjelse; scriptet genlæser også før mutation og efterfølgende.

## Test og driftsspor

- 297 HOT WATCH-tests bestod lokalt på Git-head `6a1cb27`, der indeholder kodeændringerne i `1deedcc`.
- En fuld lokal kørsel udførte 928 tests og sluttede med én miljøfejl: `test_web_push` mangler Python-pakken `requests`. Det er ikke en fuld PASS.
- Produktion rapporterede 10. november kl. 14.32 dansk tid installeret `1deedcc` via arkivmetadata; worker og supervisor var i gang. 60 sessioner var fordelt på 12 ACTIVE/WAIT, 1 ACTIVE/SELL, 6 ACTIVE/NO_DATA og 41 DEGRADED/NO_DATA. Det er et øjebliksbillede, ikke accept af #3–#10.
- AMZN havde kortvarigt `sample_id_conflict`, men de sammenlignede faktiske observationer og årsagen er endnu ikke dokumenteret. Ingen svækkelse af afvisningsregler er foreslået.

## Kilder

- https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects
- https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/adding-items-automatically
- https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations
- https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/automating-projects-using-actions
