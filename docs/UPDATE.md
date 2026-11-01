# Opdatering på Nordicway

Tag først en kopi af escape_app/var/escape.db med Fil Manager, mens appen er stoppet. Opbevar kopien privat uden for domænets dokumentrod.

Hent ZIP fra grenen codex/escape-development på GitHub. Udpak på Mac. Erstat kun disse tre filer i den eksisterende installation:

- escape_app/app.py
- escape_app/static/app.js
- escape_app/static/style.css

Bevar var/escape.db, cPanel-filer, login, passenger_wsgi.py og miljøindstillinger. Genstart appen via Setup Python App. Den nye databasetabel oprettes automatisk uden at slette eksisterende data. Genindlæs Safari-siden.

Kontrollér: Log ind, åbn Opportunity Radar, gem en kildebelagt observation, genindlæs og kontrollér persistens. Prøv markedsfilter og vis analysegrundlag. Kontrollér at handelsforslaget kun får overført symbolet og kræver egne prisantagelser. Faktiske markedsdata og AI er stadig ikke tilsluttet.
