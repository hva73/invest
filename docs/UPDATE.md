# Opdatering v0.4 på Nordicway

Opdateringen ligger på GitHub-grenen codex/escape-development og er ikke automatisk installeret. Bevar den eksisterende database og konto. Ingen betalt tjeneste er nødvendig for jobkø eller ECB-kilder.

## Filer og automatisk backup

1. Stop appen via Setup Python App → STOP APP.
2. Hent en frisk ZIP fra GitHub-grenen. Upload og udpak under `escape_app/opdatering`, i en ny mappe. Brug ikke den gamle ZIP. Arkivet må ikke placeres i domænets offentlige dokumentrod.
3. Find `apply_update.py` i den nye udpakkede mappe. I Setup Python App → Execute python script angiver du den fulde sti til den fil og klikker Run Script. Eksempel (mappenavnet kan være anderledes): `/home/nordicr4/escape_app/opdatering/invest-codex-escape-development/apply_update.py`.
4. Scriptet tager en konsistent SQLite-backup og validerer den, sikkerhedskopierer de eksisterende kodefiler og kopierer kun sin faste liste af nye kodefiler. `var/escape.db` overskrives ikke. Backup placeres privat i `/home/nordicr4/.escape_backups/` uden for domænerne. Ved kopieringsfejl rulles kodeændringer tilbage. Ved backupfejl kopieres ingen kode. Scriptet starter ikke appen eller udfører databasemigrationer.
5. Tilføj `requirements.txt` under Configuration files, og vælg Run Pip Install. TLS- og pakkeverifikation skal forblive aktiveret. Stop ved installationsfejl, og vis kun fejlteksten uden hemmeligheder.
6. Kør `/home/nordicr4/escape_app/setup_runtime.py` via Execute python script. Det opretter én privat AES-GCM-nøgle i `var/keys/token.key` med rettigheder 0600; eksisterende nøgle erstattes aldrig. Nøglen må ikke vises eller kopieres i chat/Git. Token-nøglen skal beskyttes og indgå i en særskilt sikker backupstrategi; databasebackup alene kan ikke genskabe krypterede forbindelser.
7. Start appen og genindlæs Safari. Log ind som owner med eksisterende adgangskode. Tjek Rapporter & alarmer og Forbindelser. Scriptets backup er for opdateringen; automatisk driftsbackup er ikke aktiveret.

## Pluto-login

Konfigurér kun de følgende ikke-hemmelige værdier i Python-appens Environment variables:

- `ESCAPE_PUBLIC_URL=https://escape.nordic-response.dk`
- `PLUTO_READ_SCOPES`: den præcise dokumenterede læseadgang fra Pluto. Ingen gættede navne. Hvis metadata ikke annoncerer scopes, kræves afklaring hos Pluto før login.
- `PLUTO_CLIENT_ID`: kun hvis Pluto kræver en manuelt registreret klient. Feltet er ikke nødvendigt, hvis verificerede metadata annoncerer dynamisk registrering og offentlig PKCE-klient.

Gem og genstart. Kontrollér Pluto-opsætning viser nu også offentlige autorisationsmetadata, herunder scopes, endpoints, PKCE og registreringsmulighed. Det indeholder ikke tokens. Del disse oplysninger til afklaring af scopes, hvis nødvendigt. Log ind hos Pluto vises først, når lokal konfiguration og kryptering er klar. Flowet åbner Plutos officielle browserlogin og kommer tilbage til callback. Ingen indlejret loginformular eller iframe. Registreret callback: `https://escape.nordic-response.dk/api/pluto/callback`.

Implementeret klienttype: offentlig OAuth authorization-code-klient med PKCE S256 og token_endpoint_auth_method=none. Hvis Pluto kræver en fortrolig klient, eksterne auth-hosts, andre endpoints eller særskilt godkendelse, stopper flowet med en forklaring. Koden skal tilpasses den verificerede kontrakt; man må ikke bare omgå kontrollen. Refresh-tokens opbevares krypteret, men automatisk refresh er ikke implementeret endnu. Når access-token udløber, vises Login udløbet. Tilbagekaldelse bruger et annonceret revocation-endpoint; hvis det mangler/fejler, slettes tokens ikke med en falsk succesbesked.

Et godkendt login er ikke en verificeret porteføljeintegration. MCP-værktøjskontrakter og scope-semantik skal stadig afklares, før beholdninger og kontanter hentes. Appen opretter ingen handler.

## Aktivering af job på Nordicway

Kør først `/home/nordicr4/escape_app/worker.py` manuelt via Execute python script. Det kan tage ca. 16 sekunder ved to netværksopslag. I appen → Rapporter & alarmer kontrolleres jobstatus og kildeindhold. Fejl vises i historikken og skjules ikke som tomme succeser. AI er ikke tilsluttet; offentlige ECB-data bliver aldrig præsenteret som handelsanbefalinger.

Hvis cPanel tilbyder Cron Jobs, vælg kørsel én gang pr. minut og brug Python fra appens virtuelle miljø:

```
/home/nordicr4/virtualenv/escape_app/3.11/bin/python /home/nordicr4/escape_app/worker.py
```

Dette er den sti, der tidligere blev vist på ejerens cPanel-skærmbillede; kontrollér den aktuelle sti. Sæt cronfelterne til `* * * * *`. Worker bruger absolut databaseplacering ud fra app.py og behøver ingen cd. En worker-proces behandler højst 20 job pr. start. Leases og unikke jobnøgler beskytter mod overlappende cronjobs. Kontroller hostingens cron-grænser; vælg et tilladt interval, og juster heartbeat-vurderingen ved intervaller over tre minutter. Ingen konstant serverproces forudsættes.

Rapportjob oprettes kun, når worker kører i timen kl. 08, 14 eller 22 dansk tid; manglende timer efterfyldes ikke automatisk. Det er faktuelle datastatusrapporter, ikke AI-markedsanalyser. 15.00-rapport, notifikationer, globale markedsdata og børs-kalendere er ikke implementeret. Job- og snapshotdata har endnu ingen automatisk retention; overvåg diskforbrug før længere drift.

## Verifikation og rollback

Kontrollér login, gamle forslag, invitation i en separat browsersession, nye kilder med korrekte tidsstempler, jobfejl ved utilgængelig kilde og et reelt Pluto-login når konfigurationen er verificeret. Test fysisk iPhone og PWA separat.

Ved fejl: stop appen og gem fejltekst uden nøgler/tokens. Gendan kode og tilhørende backupdatabase samlet efter vurdering. Rul aldrig tilbage til den gamle enkeltbrugerversion med en nyere flerbrugerdatabase, da den gamle kode ikke isolerer brugere. Bevar både database og den matchende krypteringsnøgle. Bed om hjælp før rollback med rigtige tilsluttede konti.

## Opdatering v0.5: dynamiske porteføljer

Samme proces med en frisk ZIP og den medfølgende apply_update.py under escape_app/opdatering. Scriptet installerer nu også portfolios.py og mcp_client.py. Stop appen og kør scriptet fra den nye udpakkede mappe. Bevar database, krypteringsnøgle, miljøvariabler og OAuth-klientregistrering. Eksisterende dependency og tokennøgle kræver ikke genoprettelse. Start/genstart derefter appen og genindlæs Safari.

Kontrollér Mine porteføljer: tom liste for en ny konto uden forslag og historiske lokale poster for eksisterende forslag. På overblikket: Opdatér porteføljer fra Pluto. Hvis der vises en kontraktfejl, gå til Forbindelser → Undersøg Plutos porteføljeværktøjer. Del værktøjsbeskrivelserne/inputSchema/outputSchema til adaptertilpasning; del aldrig tokens eller krypteringsnøgle. Værktøjsopslag udfører ingen handelsværktøjer. Porteføljer fra Pluto må ikke oprettes ud fra manuelle gæt om deres ID eller svarets betydning.

Synkronisering med et understøttet, komplet svar skal testes for nye, omdøbte og fjernede Collections samt en anden brugers konto. Aktuel implementering er manuel opdatering, ikke automatisk baggrundssync. Alle værdier for beholdninger, kontanter og afkast forbliver ukendte, indtil de er verificeret separat.

## v0.5.1: rettelse af kontraktfejl

Installer med en frisk ZIP og det medfølgende apply_update.py som tidligere. Pakker og eksisterende nøgle skal ikke genoprettes; database-, OAuth- og miljøkonfiguration bevares. Ved genstart tilføjes metadatafelter for porteføljetype, forældreportefølje og visnings-/handelsadgang transaktionelt.

Tryk Opdatér porteføljer fra Pluto. Vent på resultatet; UI viser nu en hentebesked under kørslen. Ved en formatfejl kan den viste tekst med feltnavne og datatyper deles til yderligere adaptertilpasning; der er ikke brug for tokens eller rå kontodata. Forvent ikke beholdningsværdier eller kontanter i denne version.
