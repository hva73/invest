# Opgave: HOT WATCH-datakildekontrol

Til senere udvikling: Gør nedenstående diagnostik tilgængelig som en sikker driftskontrol, så ejeren kan undersøge EODHD-kursadgang og entydige Pluto/EODHD-instrumentmatch uden at kopiere en terminalkommando. Vis kilde, kurstid og matchstatus; vis aldrig API-nøgler eller rå loginoplysninger. Kontrollen må ikke oprette ordrer eller ændre HOT WATCH-sessioner, og opslag skal respektere det eksisterende databudget.

Aktuelt fund: Den 6. november 2026 svarede EODHD på `NOVO-B.CO` og `TSM.US`, mens Pluto-cache manglede ISIN for både NOVOB og TSM. Manglende ISIN i cache beviser ikke, at et frisk Pluto-instrumentopslag mangler ISIN.

Referencekommando fra brugeren:

```bash
cd /home/nordicr4/escape_app

/home/nordicr4/virtualenv/escape_app/3.11/bin/python3.11 - <<'PY'
import json
import os
from pathlib import Path

workers = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        if proc.stat().st_uid != os.getuid():
            continue
        args = (proc / 'cmdline').read_bytes().split(b'\0')
        if any(a.endswith(b'/hotwatch_service.py') for a in args) and b'--once' not in args and b'--probe-eodhd' not in args:
            workers.append(proc)
    except OSError:
        continue

if len(workers) != 1:
    raise SystemExit('Forventede én kørende HOT WATCH-motor; fandt ' + str(len(workers)))

env = dict(x.split(b'=', 1) for x in
           (workers[0] / 'environ').read_bytes().split(b'\0') if b'=' in x)
for key in ('ESCAPE_EODHD_API_KEY', 'ESCAPE_HW_EODHD_REST_ENABLED',
            'ESCAPE_HW_REQUESTS_PER_MINUTE', 'ESCAPE_DB'):
    value = env.get(key.encode())
    if value is not None:
        os.environ[key] = value.decode()

if not os.environ.get('ESCAPE_EODHD_API_KEY', '').strip():
    raise SystemExit('Motoren har ingen EODHD-nøgle.')

import app
from eodhd_feeds import EODHDFeeds
from hotwatch_adapters import reserve, search_eodhd_symbols

if not Path(app.DB).is_file():
    raise SystemExit('Motorens database blev ikke fundet.')

feed = EODHDFeeds(os.environ['ESCAPE_EODHD_API_KEY'],
                  reserve=lambda: reserve(app.connect, 0, 'eodhd'))

print('EODHD KURSOPSLAG:')
for symbol in ('NOVO-B.CO', 'TSM.US'):
    result = feed.snapshot(symbol)
    print(symbol, 'status:', result.get('status'),
          'kurstid:', result.get('event_time') or 'mangler')

print('\nINSTRUMENTMATCH:')
for ticker in ('NOVOB', 'TSM'):
    with app.connect() as con:
        row = con.execute('''
            SELECT s.user_id, s.request, m.payload
            FROM hw_sessions s
            LEFT JOIN market_asset_cache m
              ON m.user_id = s.user_id
             AND m.asset_id = json_extract(s.request, '$.asset_id')
            WHERE s.is_test = 0 AND json_extract(s.request, '$.ticker') = ?
            ORDER BY s.id DESC LIMIT 1
        ''', (ticker,)).fetchone()

    if not row or not row['payload']:
        print(ticker, 'Pluto-instrumentoplysninger: ikke i cache')
        continue

    request = json.loads(row['request'])
    asset = json.loads(row['payload'])
    isin = asset.get('isin')
    currency = request.get('quote_currency')

    if not isin:
        print(ticker, 'Pluto-ISIN: mangler i cache')
        continue
    if (asset.get('asset_id') != request.get('asset_id')
            or str(asset.get('ticker', '')).casefold() != ticker.casefold()
            or asset.get('currency') != currency):
        print(ticker, 'Pluto-identitet eller valuta: kræver kontrol')
        continue

    try:
        result = search_eodhd_symbols(
            app.connect, row['user_id'], {'quote_currency': currency},
            candidate_override={'ticker': ticker, 'company_name': asset.get('name')}
        )
        matches = [x for x in result.get('choices', [])
                   if x.get('isin') == isin and x.get('currency') == currency]
        print(ticker, 'entydige ISIN- og valutamatch:', len(matches))
    except Exception as error:
        print(ticker, 'opslag:', getattr(error, 'code', type(error).__name__))
PY
```
