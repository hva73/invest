# Opdatering: separate brugere (v0.3)

Denne opdatering er ikke automatisk installeret på Nordicway. Den er testet lokalt via HTTP og WSGI; browser-, iPhone- og rigtig cPanel-test mangler.

1. Stop appen i Setup Python App. I Fil Manager: kopiér hele mappen escape_app/var til en dateret backupmappe i hjemmemappen uden for begge offentlige domænemapper. Den indeholder private data og skal bevares privat. Stop ved backupfejl. Ændr ikke backupens indhold.
2. Hent frisk ZIP fra GitHub-grenen codex/escape-development. Udpak den i en separat mappe.
3. Bevar en kopi af de gamle kodefiler, og erstat kun:
   - escape_app/app.py
   - escape_app/pluto.py (ny fil)
   - escape_app/passenger_wsgi.py
   - escape_app/static/app.js
   - escape_app/static/index.html
   - escape_app/static/style.css
4. Bevar var/escape.db, cPanel-konfiguration, public, tmp og miljøindstillinger. Upload aldrig en lokal udviklingsdatabase. Den gamle setup_user.py skal ikke køres igen. Fjern filen, når kontoopsætningen er afsluttet. ESCAPE_SETUP_PASSWORD skal forblive fjernet.
5. Start appen. Den migrerer databasen transaktionelt og bevarer den gamle konto, password-hash og gamle data. Ved tvetydigt ejerskab stopper migrationen med fejl frem for at gætte. Gentagen opstart er testet.
6. Genindlæs Safari. Log ind med brugernavn owner og din eksisterende adgangskode. Gå til Forbindelser: kontoen skal være Administrator.
7. Opret en engangsinvitation og test i en separat privat browsersession med en ny konto. Den nye bruger må ikke kunne se owners forslag eller journal. Kontrollér oprettelse og genindlæsning af en observation. Login-sessions udløber efter otte timer og overlever worker-genstart.
8. Registrér eventuelt et Pluto-tilslutningsønske. Teksten skal tydeligt sige, at det kun gemmes lokalt, og at OAuth endnu ikke er aktiveret. Klik Opret forbindelse til Pluto for at teste standard OAuth-resource-metadata fra Nordicway. Kopiér resultatteksten; testen gemmer ingen tokens og gennemfører ikke login.

Ved opgraderingsfejl: stop appen, bevar en kopi af den fejlede database og log til diagnose, gendan de gamle kodefiler og den tilhørende backupdatabase samlet, og start igen. Ældre kode filtrerer ikke på bruger; rul aldrig tilbage til den efter at have inviteret andre brugere uden også at gendanne den gamle enkeltbrugerdatabase. Bed om hjælp før en sådan rollback.
