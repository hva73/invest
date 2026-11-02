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

## v0.6: beholdninger, værdier og kontanter

Brug frisk ZIP og apply_update.py fra en ny udpakket mappe under escape_app/opdatering. Scriptets faste fil-liste inkluderer nu portfolio_data.py. Stop appen først. Bevar database, tokennøgle, OAuth-klient og miljøvariabler. Ingen nye pakker eller scopes kræves. Efter returncode 0: start appen og genindlæs Safari.

På overblikket vælger ejeren Vis beholdninger og kontanter på én importeret portefølje og derefter Opdatér værdier og beholdninger. Test først en rodportefølje og derefter én Collection. Opslag kan tage tid, især med flere sider. Delvise fejl vises pr. sektion; ukendte data er ikke nuller. Ved en ukendt felttype kan den viste fejltekst med feltnavne/datatyper deles; tokens er ikke nødvendige. Der er ingen generisk handels- eller MCP-kommandoformular.

Kontrollér mod Pluto: valuta for hver konto, reservationer, senest registreret værdi, antal beholdninger og at en Collection ikke summeres oven i sin rodportefølje. get_positions totalCount kan være højere end returnerede rækker, når positioner er solgt under pagination; loopet stopper først, når nextToken er væk. Kvittering for et lykkedes API-opslag er ikke dokumentation for friske markedskurser. Sammenhold kildetid og indlæsningstid.

Hvis cron aktiveres, henter worker også Pluto-datasæt timevis for aktive, importerede porteføljer med gyldigt token. Data læses igen; intet handles. Nye porteføljer kræver fortsat opdatering af navnelisten. Genlogin er nødvendigt ved tokenudløb indtil automatisk refresh er implementeret. Automatisk drift er ikke aktiveret blot ved kodeopdatering.

## v0.6.2: samlet rettelse efter skærmbilleder

Frisk ZIP + apply_update.py opdaterer både equity-understøttelse, kontodiagnose og præcision i visningen. Ingen nye pakker, scopes eller nøgler. Efter genstart/genindlæsning skal der klikkes Opdatér værdier og beholdninger på en portefølje; genindlæsning alene genbruger gamle snapshots og kan stadig vise den tidligere equity-fejl. Kopiér den nye kontodiagnose med feltnavne/datatyper til videre tilpasning. Den indeholder ikke balancebeløb eller tokens. Unknown-kildetider må ikke erstattes med indlæsningstiden.

## v0.6.3: cash/withdrawalPower og Collections

Installer frisk ZIP gennem apply_update.py under en ny mappe, mens appen er stoppet. Genstart og genindlæs siden. Ingen nye pakker, scopes eller nøgler er nødvendige.

Kør først Opdatér værdier og beholdninger på rodporteføljen. Kontantbalance skal nu læses fra cash og hævbart beløb fra withdrawalPower. Købekraft må stadig vise —, når buyingPower ikke leveres; det er ikke en fejl og må ikke erstattes af withdrawalPower. Kør derefter samme opdatering på en Collection. Ukendte indre strukturfelter kan stadig kræve tilpasning; del kun den afgrænsede fejltekst. Succesfulde Collection-sektioner kan nu vises trods fejl i en anden sektion.

## v0.6.4: hierarki og Collection-beholdninger

Samme opdateringsprocedure med frisk ZIP og apply_update.py, appen stoppet, derefter start og genindlæsning. Ingen ny konfiguration kræves. Opdatér liste med porteføljer/Collections for at få aktuelle parent-ID'er; opdatér derefter Collection-værdier og beholdninger. Rodporteføljens total skal ikke ændres blot fordi en Collection bliver hentet. En Collection, som ligger i en anden valuta eller har et andet kildetidspunkt, trækkes heller ikke fra for at udlede direkte beholdningers værdi.

Hvis beholdningsformatet stadig er ukendt, del den nye begrænsede strukturtekst. Den indeholder typer og tilladte skemanøgler, ikke kontonøgler eller instrumentnavne. Den fulde rå kontooversigt eller tokens er ikke nødvendige til denne diagnose.

## v0.7: design og sidste observerede Collection-wrapper

Hent frisk ZIP og brug samme apply_update.py-procedure fra en ny mappe under escape_app/opdatering. Stop appen først, kør scriptet, kontroller returncode 0, og start appen. Ingen nye pakker, nøgler, scopes eller miljøvariabler. Genindlæs Safari med Cmd+Shift+R for at hente CSS og JavaScript.

Opdatér værdier og beholdninger på en Collection. Datastatus er nu en fold-ud-sektion under værdien, så tekniske fejl ikke fylder hele oversigten. Hvis fejl stadig forekommer, åbn Datastatus og del den afgrænsede fejltekst. Bekræft instrumenter, antal, valuta, værdi og fortegn mod Pluto. Positive/negative pile i beholdningstabellen angiver urealiseret resultat i instrumentets valuta; de er ikke udvikling over en tidsperiode. Ukendte resultater vises neutralt.

Kontroller både Mac og iPhone, at tabeller kan rulles vandret uden at siden selv løber ud over skærmen, og at Collections stadig står under deres portefølje uden ekstra bidrag til totalen.

## v0.8: design og ACTIVE_BUY samlet

Versionen omfatter designet fra v0.7 plus pending_orders.py. Et allerede downloadet v0.7-arkiv indeholder ikke ordretilpasningen og kan ikke få den ved blot at køre det gamle apply_update.py igen. Hent en frisk ZIP og udpak separat under escape_app/opdatering. Installer med det nye arkivs apply_update.py, mens appen er stoppet. Scriptet bevarer DB, nøgler og OAuth-opsætning og kopierer den nye modulefil. Ingen nye pakker eller scopes kræves.

Efter start/genindlæsning: opdatér porteføljeværdier og derefter Collection-data. Kontrollér Afventende handler. ACTIVE_BUY skal være adskilt fra gennemførte beholdninger. Sammenhold antal, instrument, status og eventuelt beløb med Pluto. Beløb vises kun, når eksplicit oplyst. Rækker uden sikker fælles ordrereference tælles ikke automatisk som entydige separate ordrer eller summeres til ekstra reserverede penge. Ukendt/ufuldstændig ordreadgang fremgår af Datastatus.

Kontantbalance og reservedForOrders skal være uændrede af selve tilføjelsen af pending-tabellen. Ingen nye fradrag foretages, og der vises ikke frit investerbare kontanter ud fra uafstemt kapital. Hvis de to aktuelle ACTIVE_BUY ikke kan identificeres, del den nye datastatus; del ikke tokens, nøgler eller private ordrebekræftelser.

## v0.9: prisopslag for Collection-instrumenter

Frisk ZIP + medfølgende apply_update.py som tidligere. asset_quotes.py er tilføjet scriptets faste liste; stop appen ved opdatering, genstart og genindlæs Safari. Ingen nye pakker, scopes eller nøgler. Opdatér selve Collection-værdier og beholdninger, ikke kun porteføljenavnelisten, så aktiv-ID'erne hentes igen.

Kontrollér Microsoft som første instrument: get_asset skal ramme aktiv-ID'et fra den aktuelle Collection og give en anvendelig pris i USD. Mangler valuta, pris eller korrekt ID, bevares — og Datastatus forklarer hvorfor. Ingen handel foretages. Prisopslaget kan tage tid; højst 20 unikke instrumenter behandles pr. opdatering.

En afledt markedsværdi skal være mærket Beregnet · antal × pris. Afledt urealiseret resultat skal være mærket Beregnet · værdi − kostpris. Det er en beregning ud fra senest kendte pris, ikke et garanteret realiserbart salgsbeløb eller brokerens officielle performanceberegning. Sammenhold valuta og tidspunkt før vurdering. Collectionens egen equity/profitLoss og rodporteføljens total bevares særskilt.


## Overblik, journal og invitationer (november 2026)

Denne opdatering giver strukturerede rapporttal og tre prioriterede næste handlinger på forsiden. Det fulde markedsresumé er foldet sammen. Journalen viser hændelser på tværs af op til 50 driftsrapporter, med kilde og adgang til originalrapporten. Der ændres ingen rapporter, handler, nøgler, plugin-kontrakter eller planlagte opgaver.

Registrering accepterer store bogstaver i brugernavnet (gemmes som små), fjerner utilsigtede mellemrum og linjeskift i invitationskoden og viser konkrete fejl ved oprettelsesknappen. Adgangskoden skal stadig have mindst 14 tegn. Engangsinvitationer udløber stadig efter 24 timer; opret en frisk invitation, hvis den gamle er udløbet eller brugt. Eksisterende brugere skal logge ind, ikke oprette sig igen.

Installer med en frisk ZIP og `apply_update.py` som beskrevet ovenfor. Opdateringen er ikke installeret på webhotellet alene ved at hente ZIP-filen. Efter installation: start appen, genindlæs siden og test invitationen i et privat vindue.


## Mobilopdatering, datatid og Pluto-fornyelse

- På mobilen kan man trække ned fra sidens top og slippe for at opdatere. Knappen **Opdatér** gør det samme på alle skærmstørrelser. Aktive felter og åbne dialoger beskyttes mod utilsigtet genindlæsning.
- Fra Overblik og Porteføljer hentes den aktuelle Pluto-liste og data for de aktive Pluto-enheder. På en porteføljes detaljeside opdateres kun den valgte enhed. Fra rapportsider genindlæses rapporterne; status siger udtrykkeligt, at Pluto-kontodata ikke blev hentet. Ingen handel eller ny AI-analyse bestilles.
- Aldersmærker bruger kildetid, når den er kendt, og bevarer særskilt hentetid. Under 10 minutter: normal visning. Fra 10 minutter: gul. Fra 30 minutter: rød advarsel og nedtonede tal. Manglende eller fremtidigt kildetidspunkt giver en ukendt-markering, aldrig frisk status. Gamle hentetider og fejlede opslag advares også. Mærker genberegnes hvert halve minut og ved tilbagevenden til fanen.
- ChatGPT-tal er rapportøjebliksbilleder. De vises med rapporttid og strukturerede porteføljers eget datatidspunkt; en ny rapport ændrer aldrig alderen på Pluto-kontodata.
- Pluto-adgang fornyes ved læseopslag, hvis den er ved at udløbe eller er udløbet, og en fornyelsesnøgle findes. Plutos udløb respekteres; der ændres ikke på ESCAPE-loginets otte timer. Uden gyldig fornyelsesmulighed skal brugeren logge ind hos Pluto igen. Der udvides ingen scopes.

Installér den friske ZIP med `apply_update.py`. Foreslået udpakningsmappe: `escape_app/opdatering/mobil-datatid/`. Der er ingen nye afhængigheder eller miljøvariabler. Database, eksisterende rapporter og planlagte opgaver bevares. Efter installation: start appen, genindlæs siden, træk ned på Overblik og kontrollér status samt kilde- og hentetider. Automatisk fornyelse er testet med simulerede providersvar; produktionsadgang skal bekræftes på webhotellet.


## Automatisk Pluto-opdatering i den åbne app

Efter denne opdatering kræver de første Pluto-tal ikke længere besøg i porteføljedetaljer. Ved åbning/login hentes Pluto-listen samt værdier, beholdninger, kontanter og understøttede ordreobservationer for alle aktive Pluto-enheder, hvis adgangen er gyldig eller kan forsøges fornyet. Der forsøges igen hvert femte minut efter afsluttet læsning, mens appen er synlig, samt ved tilbagevenden efter pausen. Dette gælder også, når man ser almindelige rapportsider. Rapportarkiv, testvisning, samtykkedialoger og igangværende formularer skånes.

Automatiske læseforsøg deles pr. konto og ressource i databasen, så flere faner ikke gentager de samme Pluto-opslag inden for fem minutter. Et cachetræf ændrer ingen kilde- eller hentetider og beskrives som genindlæsning af gemte data. Den manuelle knap og træk ned kan fortsat anmode om et nyt opslag. Et nyt officielt Pluto-login nulstiller læsepausen, så en tidligere loginfejl ikke forsinker den første læsning. Fejl bevarer tidligere snapshots og deres advarsler.

Appen henter ikke i lukkede eller skjulte faner; eksisterende cron og planlagte opgaver ændres ikke. Kildealder er stadig uafhængig af det automatiske hentetidspunkt. Ingen nye afhængigheder, miljøvariabler eller rettigheder kræves. Installér en frisk ZIP med `apply_update.py` under eksempelvis `escape_app/opdatering/auto-pluto/`. Start appen og genindlæs siden. Kontrollér, at status bliver til »Pluto opdateret automatisk« uden først at åbne en portefølje. Ældre afsnits krav om første manuelle opdatering gælder ikke længere.


## Rettelse af træk ned på mobilen

Træk ned fra sidens top opdaterer nu hele den aktive Pluto-liste og rapporterne, også fra rapport- og porteføljedetaljesider. Den globale **Opdatér**-knap gør det samme. Trækket kan begynde på navigationens knapper eller links, og almindeligt skrå bevægelser accepteres; korte træk og vandrette bevægelser starter ingen opdatering. En tydelig meddelelse øverst i skærmen viser, hvornår man kan slippe, fremdrift og resultat.

Hvis en fuld automatisk læsning allerede kører, vises dens fremdrift og resultat uden at gentage opslagene. Hvis der kun kører en afgrænset manuel læsning, udføres den fulde læsning bagefter. Formularindtastning og åbne dialoger beskyttes. Native browsergenindlæsning behandles ved åbning som en eksplicit fuld opdatering og springer den automatiske femminutters læsepause over. Kildetider, datamærker, scopes og planlagte opgaver ændres ikke.

Valideret med CDP-touch i Chromium med mobilvisning: træk fra knapper, skråt træk, kort træk, rapportside, Collection-detaljer, fuld læsning af to aktive enheder og tilslutning til igangværende automatisk læsning. Browsergenindlæsning og beskyttelse af kladder er også testet. Fysisk iPhone/Safari er ikke tilgængelig i testmiljøet. Installér frisk ZIP via `apply_update.py`, eksempelvis under `escape_app/opdatering/mobil-traek/`, og genindlæs siden efter start.
