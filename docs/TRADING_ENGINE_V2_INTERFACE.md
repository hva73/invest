# Trading Engine v2 · isoleret udkast til #273

`trading_engine_v2.evaluate(snapshot, strategy_key)` undersøger et uforanderligt
snapshot med tidsstemplede, kildehenviste syntetiske prædikater. Samme snapshot
kan evalueres af begge profiler. Inputdata og resultater er frosne dataklasser.
Beslutningens nøgle består af børs, asset-ID, eksakt strategiversion, UTC-tid,
snapshot-ID og formål. Afsenderen skal give ændret snapshotindhold eller
proveniens et nyt snapshot-ID inden for sin ejer- og testkontekst.

| Simuleret profil | Påkrævede input | Valgfri evidens |
| --- | --- | --- |
| Momentum `0.1.0-sim` | Simuleret risikogate, momentumbekræftelse, MACD-bekræftelse | Ingen |
| Early Catalyst `0.1.0-sim` | Simuleret risikogate, verificeret katalysator, bekræftet tidlig reaktion | MACD-bekræftelse |

`blocked` angiver bl.a. manglende eller fremtidsdateret obligatorisk evidens,
afvist simuleret risiko eller ukendt profilversion. `observation` angiver
tilgængelige data med uopfyldte strategibetingelser. `decision` kan alene
returnere `simulated_entry`. Valgfri evidens arkiveres i resultatet som
inputreference og bruges aldrig som betingelse. Profilerne illustrerer
grænsefladen med præberegnede booleans og har ingen kurstærskler eller
liveautoritet. Evalueringen bruger intet ur, lager, provider- eller brokerkald.

Proveniens for #114 følger med i alle udfald. Kandidat, watch, handelsforløb
og depot/position har særskilte referencer. Entry- og exit-oprindelse samt
intention, ordre og fill kopieres fra input. Manglende referencer forbliver
tomme. En ordrereference giver ingen fill-reference eller udførelsesstatus.
Exit-formål kan repræsenteres, men selve exit-evalueringen afvises eksplicit
i dette udkast.

Efter uafhængigt review kan en separat v2-gren mappe eksisterende
HOT WATCH-snapshots og katalogets versionslåste strategier til grænsefladen.
Den opfølgning skal genbruge de eksisterende kvalifikations-, friskheds- og
risikogates, bevare kildetider og bekræftede Pluto-referencer og afstemme
replay-resultater mod den nuværende motor før integration. Positions-exit
skal bruge sin egen evaluering og evidens. Journal, statistik, readback og
ordreflow er integrationsgrænser i denne leverance.
