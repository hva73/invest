# Codex – opfølgning på HOT WATCH-review

10. november 2026. Baseret på [reviewet](CHATGPT_review_56_sessioner_2026-11-10.md) og [arbejdsmodellen](ESCAPE_arkitektur_og_arbejdsmodel_2026-11-10.md). Produktionsversion ved kontrollen: d889aff. Ingen handler eller handelsforslag.

## Pluto parent og collection

Plutos read-only get_positions beskriver og returnerer direkte positioner separat fra collectionreferencer; get_collection returnerer collectionens egne positioner. Kontrol af de faktiske svar viste CABA i direkte depot og en særskilt collection, samt BTC i både direkte depot og collection som særskilte beholdninger. Den tidligere generelle overlap-afvisning gjorde derfor automatisk depotkontekst ukendt, selv når omfanget kunne dokumenteres.

Rettelsen kræver komplette, strengt kontrollerede snapshots med eksplicit DIRECT- og COLLECTION-scope, verificerede collection-identiteter og præcis overensstemmelse mellem parentens collectionreferencer og de aktive tilknyttede collections. Manglende eller modstridende bevis giver fortsat UNKNOWN. Eksisterende snapshots uden scope genhentes gennem den eksisterende Pluto-adapter; ingen ny tabel. Der tilskrives ikke ordre/fill til et andet depot. Summen repræsenterer særskilte direkte og collection-beholdninger, ikke parentens værdi plus collectionens værdi.

## Samtidig kildekontrol

Ved en read-only kontrol 11:56 UTC stemte AMZN-motorens sidste handel (11:54:59.054 UTC) med den samtidig tilgængelige EODHD-handel. WIX havde seneste EODHD-handel 11:28:32.993 UTC, som også var den sidst registrerede i motoren. Der er dermed ikke dokumenteret bortfald for disse to i dette kontrolvindue. ASML og ORCL viste på samme tidspunkt WAIT uden barblokering; tidligere BAR_EVIDENCE_STALE kræver sit eget tidsstemplede bevis og er ikke fjernet.

## Kontrol og næste skridt

342 relevante tests bestået, inklusive særskilt direkte/collection, begge samtidigt, manglende collection og ufuldstændige snapshots. Produktion kører fortsat d889aff; den nye scope-rettelse er ikke installeret eller live-verificeret. Efter installation skal CABA og øvrige berørte sessioner læses tilbage med frisk Pluto-kontekst, uden at forvente et signal ved gamle markedsdata. MSFT/MANE-konfliktpar, budgetdiagnose og øvrige sessioner kræver fortsat konkrete readbacks.
