# Pushnotifikationer og strategivalg

Første udgave giver web-push ved aktuelle køb-/salgssignaler fra HOT WATCH og et Strategy Center til valg af allerede kvalificerede strategiversioner for nye overvågninger. Rapporternes selvstændige statussignaler er ikke omfattet af push i denne fase. Momentum er automatisk standard; der er ikke aktiveret en ny strategi, Strategy Builder eller backtest.

## Installation

Brug hele opdateringspakken og dens `apply_update.py` med appen stoppet. Installér `requirements.txt` i appens eksisterende virtuelle miljø. Kør `setup_runtime.py` efter installation: Det opretter om nødvendigt den private VAPID-nøgle `var/keys/push_vapid.pem` med rettigheder 0600; den eksisterende nøgle og tokennøglen bevares. `ESCAPE_PUBLIC_URL` skal være den eksisterende præcise HTTPS-oprindelse. Opdateringsscriptet kopierer standardnøglen til sin private backup, hvis den findes. En eventuelt særskilt konfigureret `ESCAPE_PUSH_KEY_FILE` kræver separat sikker backup. Tab af VAPID-nøglen kræver ny tilmelding af enheder.

HOT WATCH-motoren skal køre, og serveren skal kunne nå browsernes push-tjenester. Efter installation åbnes ESCAPE på den pågældende enhed, og under Setup og forbindelser vælges Notifikationer, signalkategorier og Aktivér. Brug Send testbesked for at kontrollere leveringen; den opretter ingen ordre. På iPhone kræves en understøttet iOS-version, ESCAPE tilføjet til hjemmeskærmen, og tilladelse fra brugeren. Enhedens netforbindelse og notifikationsindstillinger påvirker levering.

De faktiske Apple-/Google-pushtjenester og levering på en fysisk telefon er ikke verificeret af de automatiske tests. Notifikationen kan blive forsinket eller afvist af enhed eller tjeneste. Når et signal ikke længere er aktuelt, forsøger serveren at erstatte den tidligere besked med en synlig opdatering; øjeblikkelig fjernelse kan ikke garanteres. Ved tryk åbnes den seneste tilgængelige HOT WATCH-status, ikke en ordre. Abonnementer krypteres i databasen, og endpoint-adresser og nøgler udskrives ikke.

## Strategy Center: næste etape

Early Catalyst v0.1.0 er en privat-sikker, inaktiv skabelon, som kan kopieres og justeres som en ny, versionslåst kladde. De tre justerbare tærskler er ikke godkendte handelsregler. Den indbyggede skabelon forudsætter bekræftet selskabsnyhed højst 30 minutter gammel samt kursreaktion, relativ volumen og spread. Motorens live-adaptere leverer endnu ikke valideret katalysatordata. Derfor kan hverken den eller brugerskabte kladder vælges til drifts-overvågning. Alle eksisterende sessioner bevarer deres tidligere strategiversion.

Funktionen «Afprøv med fiktive tal» kontrollerer kun strategi-reglerne på ét tænkt eksempel. Den udfører ingen central risikokontrol, historisk simulering, ordre eller markedshentning. Data og strategiresultater gemmes ikke som historisk performance. Historiske vinder-/taberdata, årsagssikker replay, sammenligning, aktiv kvalifikation og fuld grafisk regelbygger er ikke implementeret. Samarbejdsaftalens tillæg beskriver den strukturerede rapportoverdragelse og kvalifikationskravene.
