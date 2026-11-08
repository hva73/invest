# Early Catalyst — installationspakke 8. november 2026

**Status:** Klar til installation og efterfølgende kontrol på webhotellet. Ikke LIVE PASS; ingen produktionsinstallation, rigtige ordrer eller Pluto-forslag er udført under udviklingen.

## Ændringer

- En eksisterende kandidat-overvågning kan få en brugervalgt købsplan før et købssignal: hoveddepot, maksimalt budget i DKK inklusive købsgebyr, limitpris og analytisk stop i aktivets valuta. Planen opretter ingen brokerordre eller handelsforslag.
- Pluto læses for instrument, handelsmuligheder, valuta og gebyr. Antal beregnes som en nedrundet budgetgrænse ved den valgte limitpris og kontrolleres med et nyt eksplicit antalestimat. Et null-antal fra et beløbsestimat gøres ikke til en påstået markedsordrestørrelse. Hele aktier understøttes særskilt. Ukendte felter blokerer.
- `filledAccountNotional` med verificeret DKK-valuta anvendes som estimeret afregningsbeløb; `accountNotional` kan være nul ved et antalestimat. Købsgebyret budgetteres desuden konservativt. De globale størrelse-, tabs-, spread-, datatids- og eksponeringsgrænser bevares. Tabs- og størrelseskontrol bruger mindst limitprisen som indgangsgrundlag.
- Planens størrelse, depot, valuta og limit bindes til det konkrete HOT WATCH-forslag. Nyt brugerbeløb kræver en ny plan og nye signalbekræftelser. Før afsendelse hentes et nyt read-only estimat; ændrede/ukendte omkostninger eller valuta kræver ny kontrol. Ændrede omkostninger giver ikke automatisk tilladelse til at handle.
- Planens valuta/gebyr-estimat gælder højst 120 sekunder. Motoren kan forny estimatet ved en scanning inden for sine eksisterende opslaggrænser; fejl forlænger ikke gyldigheden. En gammel BUY-visning tilbageholdes, når planen er ændret eller estimatet udløbet. Ingen hurtigere polling eller nye datatilladelser introduceres.
- Svagt signal, manglende data og risikoblokering kan ses særskilt, også når flere forhold gælder samtidig. Early Catalysts regler og parametre er uændrede; strategiens checksum er `6208a1e06b239e0be0b4806252c5997a56c46bbdcf5f1fe2dad8280a71cb3872`. Den fælles risikoberegning mærkes `risk_version=1.1.0`.
- Exit-overvågning forbliver særskilt og bundet til verificeret depot + aktiv. Accepterede forslag tilskrives ikke automatisk en eksisterende beholdnings oprindelse; den verificerede forbindelse fra ordreintention til faktisk fill mangler endnu. Tidligere accepteret-baserede oprindelsesfelter bruges derfor ikke som bevis i den aktuelle visning eller til at opdatere den oprindelige kandidats handelsforløb. Det hindrer ikke exit-watch på den verificerede beholdning.

## Verifikation

- Fuld Python-testpakke: 663/663 PASS.
- Brugerens 15 syntetiske Early Catalyst-scenarier: 15/15 PASS i arbejdsudgaven. Baseline `69d1279`: 13/15 på samlet forventning, 15/15 på handelssignal; afvigelserne var alene risikodiagnostik ved for stort/manglende spread.
- Ekstra tidskontrol: ny bekræftende observation efter 14 sekunder giver WAIT; efter 15 sekunder kan BUY henholdsvis trailing-SELL frigives. Kritisk stopbrud giver straks SELL-signal på gyldigt grundlag.
- JavaScript-regressioner: alle 9 testfiler PASS; to forældede teststubs er opdateret til den eksisterende UI-eksport og komponentafhængighed.
- DOM-test: én købsplanformular, tomt initialt budget, read-only brokerforberedelse, fast plan i LIMIT-forslag og eksplicit brugerafsendelse. Alle API-svar er simulerede; ingen eksterne handler.
- Relevante integrations- og updater-tests dækker planbinding, ændrede gebyrer, udløb, tabt workerlease, globale risikogrænser, pause, kilde-/depotbinding, uafhængig exit og installation af det nye modul.
- Native Chromium-browsertest er **NOT RUN**: procesopstart afvises af miljøets socket-begrænsning. Den separate browser kunne ikke nå den lokale testserver; alternativ headless-browser kunne ikke downloades korrekt. DOM-testen erstatter ikke visuel Chromium/Safari/iPhone-kontrol.
- Direkte Pluto-read-only estimater for GOGO er undersøgt (marked lukket). Det rettede serverscript er **ikke** kørt på webhotellets forbindelse. Ingen påstand om frisk søndagskurs eller produktionsreadback.

## Installation — samme fremgangsmåde som tidligere

1. Hent en frisk ZIP fra `codex/escape-development`, og udpak i en ny mappe under `escape_app/opdatering/`, fx `early-catalyst-koebsplan/`.
2. Stop appen, og kør **den nye pakkes** `apply_update.py`. Den medtager nu `hotwatch_buy_plan.py`, tager privat backup og bevarer eksisterende database, rapporter, nøgler og OAuth-opsætning. En igangværende motor skal være standset, før kode udskiftes.
3. Installer `requirements.txt` og kør `setup_runtime.py` efter den normale procedure; der er ingen nye runtime-afhængigheder eller OAuth-scopes i denne ændring. Start/genstart appen. Den nye tabel `hw_buy_plans` oprettes additivt ved opstart.
4. Genindlæs Safari med Cmd+Shift+R. Åbn en entry-kandidats HOT WATCH-detalje, fold købsplanen ud, og kontrollér budget, limit og stop. At gemme planen sender intet forslag. Test ikke installationen med rigtige handler.
5. Kør derefter `tasks/pluto_readonly_risk_probe.py --user owner --ticker PEPE` på serveren, hvis PEPE stadig findes entydigt i hoveddepotets komplette snapshot; ellers vælg en faktisk entydig, understøttet beholdning. Scriptet opretter ingen ordre eller forslag og viser kun tilladte feltnavne, typer og valutakoder. Det faste kontrolbeløb på 20 DKK er ikke et handelsmandat; afvisning ved ukendt format eller utilstrækkelig købekraft er en gyldig blokering.

## Efter installation — før samlet live-test

Kontrollér faktisk installeret commit, motor/heartbeat, en kandidat-session og en separat verificeret beholdningssession. Kontrollér siden i rigtig browser/mobil. Ved åbent relevant marked verificeres derefter nyheds-/kursgrundlag, spread, volumen, signaler, gyldigt risikogrundlag, udløb og readback. Manglende markedsdata eller serveradgang må ikke rapporteres som PASS. Brugeren gennemgår resultatet før den samlede live-test; installation er ikke en tilladelse til testhandler.

Night Intelligence-tillægget ligger i den fælles samarbejdsaftales afsnit 2a. Denne pakke ændrer ikke automatisk ChatGPT-radarens opgaveprompt eller timeplan; dokumentopdateringen alene beviser ikke, at natrapporteringen er aktiveret.
