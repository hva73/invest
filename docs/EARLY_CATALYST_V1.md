# Early Catalyst v1.0 — forskningsversion

Strategien er registreret som en deklarativ, versionslåst skabelon med status `schema_validated`. Den og strukturelt identiske private kopier kan efter ejerens ønske vælges til en tydeligt mærket live-test; de er ikke historisk kvalificeret til almindelig drift. Kopier kan justeres i Strategy Center. Den gamle Momentum-strategi og eksisterende sessioner ændres ikke. EARLY WATCH er et selvstændigt observationskriterium; det opretter aldrig en ordre eller et købssignal.

## Regler

EARLY WATCH kræver bekræftet almindelig aktie og handelsbarhed hos Pluto. Dernæst kræves enten en bekræftet nyhed højst 120 minutter gammel eller bekræftet regnskab fra foregående handelssession, samt mindst én af kursreaktion 1 % og relativ volumen 1,5; alternativt dokumenteret fravær af verificeret nyhed, kursreaktion 1 % og relativ volumen 3. Nyhed med negativ alder afvises. Manglende oplysninger regnes ikke som opfyldt.

BUY READY kræver EARLY WATCH-grundlag, kursstigning mindst 0,5 % over et faktisk treminutters tidsvindue, relativ volumen mindst 1,8, positiv acceleration, spread højst 0,8 % og RSI højst 90. Mindst to nye observationer og 15 sekunders varighed kræves. Tre observationer med ukendt afstand er ikke tre minutter; uden en sammenlignelig observation inden for fem sekunder fra vinduets begyndelse er ændringen ukendt. MACD er valgfri og er som udgangspunkt slået fra; den kan vælges som ekstra positiv bekræftelse i en privat version. De fælles risiko-, datakvalitets-, eksponerings- og ordregrænser gælder fortsat. Strategien har ikke Momentum-baselinens warmupkrav på 34 observationer, men RSI og øvrige indikatorer kræver fortsat tilstrækkelige data.

Ved over 15 % fra referencekurs kræves konsolidering eller nyt breakout; ved over 30 % kræves ny selvstændig opsætning. Referencekursen er seneste verificerede ordinære lukkekurs før den aktuelle handelssession. For en katalysator efter børslukning anvendes den seneste ordinære lukkekurs før offentliggørelsen. Ved nyheder under en igangværende handelssession registreres derudover den verificerede kurs umiddelbart før nyheden: `reference_gain_pct` viser ændringen fra luk, mens `news_reaction_pct` viser reaktionen fra kursen før nyheden. Ved en nyhed efter luk kan reaktionen måles fra den verificerede ordinære lukkekurs før offentliggørelsen. Kurs, kilde og observationstid skal være tilgængelige på evalueringstidspunktet. I live-testen skal den rapporterede lukkekurs stemme med lokalt modtagne EODHD-data og en frisk børskalender. En rapporteret kurs før nyheden skal matche en tidligere lokal EODHD-observation. ChatGPTs kildeverifikation for nyheder er en afsenderoplysning og ikke selvstændigt verificeret af ESCAPE; det fremgår i detaljerne. Konsolidering og ny opsætning er endnu ikke defineret i et verificeret lokalt feed og forbliver ukendte, ikke positive bekræftelser. De anførte numeriske værdier kan ændres i en privat version i Strategy Center. Den nuværende featureberegning af relativ volumen bygger på tidligere sammenlignelige intervaller; datakilde, referenceperiode og eventuelle huller skal vurderes, før tallet kan anvendes i en historisk eller levende case.

## Historiske cases 6. november 2026

Brugerens medfølgende `tests/fixtures/early_catalyst_20261106.json` indeholder kildehenvisning og første/sidste femminutterspriser samt oplyste Pluto-søgeresultater. Den indeholder **ikke** de fulde candles, relative volumenserier, præcise nyhedstider, historisk Pluto-handelsbarhed eller historiske bid/ask. Søgeresultater fra 8. november er ikke bevis for handelsbarhed 6. november. Oplyst mulighed for brøkdele/Collections er særskilt fra almindelig handelsbarhed.

| Case | EARLY WATCH | BUY READY | Datastatus |
|---|---|---|---|
| GOGO.US | Kan ikke afgøres | Kan ikke afgøres | Fuld intradag-, nyheds-, volumen- og historisk Pluto-evidens mangler; intet historisk bid/ask. |
| STAK.US | Kan ikke afgøres | Kan ikke afgøres | Samme mangler; brugeren oplyser kun hele aktier, hvilket ikke i sig selv udelukker overvågning. |
| KRMN.US | Kan ikke afgøres | Kan ikke afgøres | Fuld intradag-, regnskabstids-, volumen- og historisk Pluto-evidens mangler; intet historisk bid/ask. |
| CIIT.US | Kan ikke afgøres | Kan ikke afgøres | Samme mangler; brugeren oplyser kun hele aktier, hvilket ikke i sig selv udelukker overvågning. |
| AF.PA | Kan ikke afgøres | Kan ikke afgøres | Pluto-identitet/handelsbarhed ikke verificeret, og fulde intradag- og quote-data mangler. |
| AELIS.PA | Kan ikke afgøres | Kan ikke afgøres | Pluto-identitet/handelsbarhed ikke verificeret, fulde intradag- og quote-data mangler; oplyste kurshuller. |

Selv med fulde femminutterscandles kan et ægte treminuttersafkast og femten sekunders bekræftelse normalt ikke genskabes. Der kræves tættere tidsstemplede data samt dokumentation for datatid, nyhedsadgang og quote-/spreadgrundlag. Ingen hypotetisk opfyldelse eller handelstidspunkt udledes af første/sidste pris. En kvalifikation kræver en separat dokumenteret sammenligning med rigtige historiske data og centrale risikogates.


## Status for live-test

Når brugeren eller en rapport udtrykkeligt vælger v1.0.0 eller en begrænset privat kopi, kan en kørende HOT WATCH-motor oprette en observation, efter Pluto-identitet og øvrige adgangskontroller er gennemført. Den viser EARLY WATCH separat fra et købssignal. Eksisterende automatiske sessioner har endnu ikke verificerede værdier for foreslået antal og stop, og Pluto-konteksten leverer ikke altid gebyr og valutaomregning. Derfor kan `RISK_INPUTS_UNKNOWN` forhindre et købssignal, også når analysekriterierne passer. Vi må ikke påstå, at denne situation er løst ved at gætte værdier. Status og input skal verificeres på den faktiske server og ved åbent marked. Ingen ordrer oprettes automatisk.
