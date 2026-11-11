# ESCAPE Invest – release og versionshistorik

Issue #57: Agent 1 er releaseansvarlig. Brug den eksisterende GitHub Actions- og Nordicway-vej fra #16; dette dokument indfører ikke en ny deploymekanisme. En ejerbestilling kan være: **“Klargør ESCAPE v2.3 med færdige, godkendte ændringer.”**

## Fra bestilling til godkendelse

1. Find den faktisk installerede SHA med den eksisterende læsende serverdiagnostik. Sammenlign den med den aktuelle udviklingsgren og dens release-manifest; kontrollér også ændringer, der allerede er installeret, men endnu ikke er integreret i udviklingsgrenen. Undersøg aktive PR'er og konflikter med deres ejere. Drafts, uafklarede PR'er og ændringer uden relevant review/test indgår ikke automatisk.
2. Saml de konkrete færdige ændringer på en releasecommit. Fastlås version og hele SHA'en, og kontrollér at manifest, filer, afhængigheder og de udførte tests svarer til netop denne commit. Den installerede bridge kræver uændret `requirements.txt` og kompatibelt manifest; ændringer her kræver en særskilt gennemgået installationsvej.
3. Bed udviklingsagent 2, 3 og 4 levere en kort PR-beskrivelse for deres færdige arbejde: ændring og brugerbetydning, rettede fejl, tests og begrænsninger. Agent 1 sammenfatter kun det, der faktisk indgår i releasecommitten.
4. Giv ejeren én oversigt: **Indhold / Tests / Risici / Diskplads / SHA / Klar til godkendelse**. Angiv kendte ukendte forhold og skeln mellem kodegodkendelse, deploy-PASS og live-funktions-PASS. ChatGPT gennemgår den samlede kandidat uafhængigt. Ejeren godkender hver konkret release-SHA før aktivering eller installation; en bestilling om klargøring er ikke produktionsgodkendelse.

## Før og under installation

- Kontrollér aktuel cPanel-kontoquota, filesystemets ledige plads og den forventede størrelse for staging, SQLite-snapshot, WAL/journal og kodebackup. Ukendt eller utilstrækkelig kapacitet stopper releasen. Se også efter vækst i backup, log og midlertidige filer; fjern ikke materiale ukontrolleret.
- Den eksisterende deployadapter beregner kapacitetsbehov og kontrollerer både kontoquota via UAPI og filesystem før servicestop. **Begrænsning:** beregningen reserverer to gange hoveddatabasens størrelse og et tillæg, men summerer ikke eksplicit faktisk størrelse af eksisterende `-wal` og `-journal`. Sammenhold disse filer og de samlede behov med aktuel ledig plads før godkendelse; behandl en utilstrækkelig eller ukendt beregning som stop. Den læsende UAPI-formatprobe alene er ikke en frisk kvoteaflæsning.
- Kontroller, at ingen recoverymarkør er aktiv. Ejeren skal godkende den eksakte SHA; serverens private `approved-sha` og `deploy-enabled` samt GitHub Actions' eksisterende miljø- og SSH-gates skal passe til godkendelsen. Den nuværende bridge har ingen generel ekstern kommando til at ændre godkendt SHA: den ændring kræver den eksisterende ejerstyrede serveradgang. Del aldrig nøgler, tokens eller miljøværdier.
- Start kun den eksisterende fastlåste deployforespørgsel efter godkendelsen. Deploysekvensen kontrollerer kvote og staging, tager deploylås, stopper service og HOT WATCH, kontrollerer cron, Passenger og øvrige DB-skrivere og tager og verificerer backup før filskift. Den kontrollerer installerede filer og genstarter. Ældre backups ryddes først efter verificeret installation og health; der foretages ikke automatisk database-restore.

## Efter installation

Kontrollér Actions-resultat, recoverymarkør og backupoprydning. Aflæs separat installeret SHA og antal matchende manifestfiler; sammenhold med HTTPS-health og runtime-SHA, database, worker/supervisor, processer og friske heartbeats. Kontrollér relevant brugerfunktion via eksisterende sikre læseoperationer. En tilgængelig health-URL eller rapportkvittering beviser ikke alle broker- eller UI-funktioner. Ved fejl: stop, bevar recoverysporet og brug den eksisterende recoveryprocedure; ingen blind genkørsel eller automatisk restore.

Agent 1 registrerer herefter de faktiske resultater i release note eller versionshistorik: version, SHA, inkluderede PR'er/Issues, brugerændringer, tests, kendte begrænsninger, tidspunkt og status (kandidat, godkendt, installeret, verificeret eller fejlet). Opdatér samme post efter installation; opfind ikke versionsnavn eller funktioner. Opret GitHub Release først når version og indhold er fastlagt; en kandidat er ikke installeret.

## Dokumenteret baseline 11. november 2026

Den godkendte produktionsinstallation `5ccc34aa26ba3a3e5ace89f3562e3fd0328f6cd9` blev gennemført [i Actions](https://github.com/hva73/invest/actions/runs/43089765128): status OK, service genoprettet, ingen aktiv recovery rapporteret og backupoprydning OK. [Separat readback](https://github.com/hva73/invest/actions/runs/43090064738) viste denne SHA, database OK og frisk worker/supervisor; [filkontrol](https://github.com/hva73/invest/actions/runs/43090180285) viste 71/71 matchende manifestfiler. Deployets HTTPS-health kontrollerede faktisk build-SHA efter start. Et senere processnapshot viste Passenger=0; det dokumenterer ikke et vedvarende procesantal. Dette er et tidsbestemt bevis, ikke aktuel drift eller et versionsnavn.

Serverens installerede bridge er `986ec9a6a7cdc8e931c6deb926b80ac97dfe68fa`; [PR #28](https://github.com/hva73/invest/pull/28) er merged til integrationsgrenen, mens [PR #25](https://github.com/hva73/invest/pull/25) fortsat skal afstemmes mod udviklingsgrenen. Produktions-`app.py` og `apply_update.py` skal bevares i den fælles kodebase, så en fremtidig release ikke mister den fungerende runtime-SHA eller updaterrettelserne. Automatiseret fremadrettet tjek af backup-/logvækst, live release notes og en generel ejerstyret SHA-godkendelse er endnu ikke dokumenteret; den eksisterende releaseansvarlige udfører de nødvendige kontroller manuelt.
