# ESCAPE – ChatGPT opfølgning, 10. november 2026 kl. ca. 13:58 dansk tid

**Status:** Uafhængigt read-only review; ingen ændringer i handelsmandater, ingen ordre og intet deployment. Opgavestyring i **ESCAPE Development** / repo-Issues #3–#11. Projects-medlemskab kan ikke kontrolleres med nuværende GitHub-connector.

## Codex' commits siden 6243faf

1. [`c5f07b7`](https://github.com/hva73/invest/commit/c5f07b7a3a88440036ac4272203a54315f245437) (**#7**): én snæver Trade Desk aliasundtagelse i `instrument_resolver.py`, under bundet Pluto-asset-ID, klasse A, NASDAQ, USD og ISIN US88339J1051; tests for ugyldig klasse, kursvaluta, børs, type, ISIN og dubletter. Dette er instrumentidentitet, **ikke** løst budget/quote/handel. Hold senere fælles ISIN-mapping frem for mange permanente selskabsspecifikke særtilfælde.
2. [`1deedcc`](https://github.com/hva73/invest/commit/1deedccf9f0f521b6d4e5e61628ff39daeb0fa77) (**#5/#6**): additive felter i `hotwatch_engine.py`, `hotwatch_service.py` og `static/engine-ui.js`, der viser barblokeringens afslutning/kalendertid og konflikters felter, eventtider, kilde/feed og hash af sample-ID. Der er testændringer. **Diagnostik er ikke en dokumenteret rettelse af selve grundfejlen**; behold eksisterende afvisning af modstridende kildedata.
3. [`3bc3b21`](https://github.com/hva73/invest/commit/3bc3b218dc3a3ea85b5b1df2519d0360bea46be3): ChatGPTs tidligere feedback/Projects-arbejdsmodel, ikke Codex-kodeændring.

**Testevidens:** Den tidligere `6243faf`-opfølgning oplyser 342 lokale PASS. Nye commits har testkoder, men ingen selvstændig testkørsel/CI-resultat blev påvist via GitHub checks eller PR-workflows. Kræv reproducerbart testoutput for de nye commits før release.

## Faktisk produktions-readback (ESCAPE `sync_hot_watch`, `is_test=false`)

Readback `as_of=2026-11-10T12:58:07Z`: installation viser **`6243faf` fra archive metadata**, worker `running` med frisk heartbeat, supervisor `running`. Det dokumenterer, at den forrige Pluto-scope-ændring er markeret installeret, **ikke** at de nye `c5f07b7`/`1deedcc` er installeret, og ikke at enhver logisk fejl er løst.

59 åbne sessioner på seks fuldt paginerede session-sider: **3 ACTIVE/WAIT, 2 ACTIVE/NO_DATA, 54 DEGRADED/NO_DATA**. Forekommende displayårsager: `DATA_STALE` 35, `BAR_EVIDENCE_STALE` 2, `PROVIDER_RATE_BUDGET` 3, `WAITING_FOR_NEW_VERIFIED_QUOTE` 3, `PLUTO_QUOTE_TIME_UNKNOWN` 3. Disse årsager er *ikke nødvendigvis gensidigt udelukkende* eller udtømmende for alle 59.

Relevante reelle sessioner:
- **CABA**: både candidate og holding findes; begge DEGRADED/NO_DATA med DATA_STALE, *ikke* HOLDING_SCOPE_OVERLAP. Det er positivt, men beviser ikke korrekt brokerquantity/scope eller live-accept for #3.
- **BTC**: to særskilte holding-watches er DEGRADED/NO_DATA; ingen synlig scope-diagnose i den korte readback.
- **ASML**: ny `BAR_EVIDENCE_STALE` observeret; **#5 stadig åben**. Den nye bar-detalje fra `1deedcc` er ikke i den installerede commit.
- **TTD**: `PROVIDER_RATE_BUDGET` stadig blokering på kandidat; identitetsmapping fra WIP fjerner ikke denne eksterne/prioriteringsblokering.
- **MSFT** ACTIVE/WAIT; **MANE** DEGRADED/NO_DATA (DATA_STALE). Ingen friske konfliktpar kunne læses fra det aktuelle statusoverblik; #6 er ikke årsagslukket.
- **AMZN**: `BROKER_CONTEXT_UNAVAILABLE`; ORCL: markedsstatus-/DATA_STALE; WIX: DATA_STALE. Kræver præcis tidskæde i #4.

**Vigtig anbefaling til Codex:** Prioritér #4 datakæde-/stale-årsager og live readback af #3 før flere funktioner. Dokumentér de nødvendige adgangsdata, målepunkter, faktisk påvirkning og mindste rettelse. Bevar adskilt broker-fill, verificeret trade, quote og signal; ingen lempelse af safety-gates. Ingen 'Færdig', før ejer-godkendt installation, korrekt installeret commit og frisk produktionsevidens.

**Aftalecheck:** Underordnet [v3.9](../docs/ESCAPE_TRADING_AGREEMENT_V3_9.md) og [arbejdsmodellen](ESCAPE_arkitektur_og_arbejdsmodel_2026-11-10.md); ingen handel, strategieskift eller automatisk installation autoriseret ved dette review.
