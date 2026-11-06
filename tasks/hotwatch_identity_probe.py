import json, os, re, sys, time
from pathlib import Path

# This diagnostic may be downloaded to /tmp; app modules live in the cwd.
sys.path.insert(0, str(Path.cwd()))

workers = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        if proc.stat().st_uid != os.getuid():
            continue
        args = (proc / 'cmdline').read_bytes().split(b'\0')
        if any(x.endswith(b'/hotwatch_service.py') for x in args) and b'--once' not in args and b'--probe-eodhd' not in args:
            workers.append(proc)
    except OSError:
        continue
if len(workers) != 1:
    raise SystemExit('Forventede én HOT WATCH-motor; fandt ' + str(len(workers)))
env = dict(x.split(b'=', 1) for x in (workers[0] / 'environ').read_bytes().split(b'\0') if b'=' in x)
for key in ('ESCAPE_DB', 'ESCAPE_TOKEN_KEY_FILE', 'ESCAPE_HW_REQUESTS_PER_MINUTE',
            'ESCAPE_EODHD_API_KEY', 'ESCAPE_HW_EODHD_REST_ENABLED', 'PLUTO_CLIENT_ID'):
    if key.encode() in env:
        os.environ[key] = env[key.encode()].decode()

import app, market_data, trade_service, oauth
from hotwatch_adapters import PlutoAdapter, search_eodhd_symbols
if not Path(app.DB).is_file():
    raise SystemExit('Motorens database blev ikke fundet.')

for ticker in ('NOVOB', 'TSM'):
    try:
        with app.connect() as con:
            row = con.execute("SELECT user_id,request FROM hw_sessions WHERE is_test=0 AND json_extract(request,'$.ticker')=? ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
        if not row:
            print(ticker, 'ingen session fundet'); continue
        req = json.loads(row['request']); uid = row['user_id']; aid = req['asset_id']
        with app.connect() as con:
            auth = con.execute('SELECT payload,expires FROM oauth_tokens WHERE user_id=?', (uid,)).fetchone()
        if not auth or auth['expires'] <= time.time() + 60:
            print(ticker, 'Pluto-adgang mangler eller udløber snart; intet opslag udført'); continue
        token = oauth.unseal(uid, auth['payload'])['token']['access_token']
        adapter = PlutoAdapter(app.connect, uid)
        client = adapter.factory(token)
        tools = {item['name']: item for item in client.tools()}
        raw = trade_service.call(client, tools, 'get_asset', {'assetId': aid})
        found = trade_service.call(client, tools, 'search_assets', {'query': ticker, 'limit': 10, 'assetType': 'ALL'})
        choices = market_data.choices(found)
        exact = [x for x in choices if x.get('asset_id') == aid]
        node = raw.get('asset', raw) if isinstance(raw, dict) else {}
        if not isinstance(node, dict):
            node = {}
        raw_isin = node.get('isin') or (raw.get('isin') if isinstance(raw, dict) else None)
        search_isin = exact[0].get('isin') if len(exact) == 1 else None
        valid = lambda x: isinstance(x, str) and bool(re.fullmatch('[A-Z]{2}[A-Z0-9]{9}[0-9]', x))
        ids = [x for x in (node.get('id'), node.get('assetId'), raw.get('assetId') if isinstance(raw, dict) else None) if x is not None]
        confirmed = bool(ids) and all(x == aid for x in ids)
        print(ticker, 'get_asset-ID:', 'matcher' if confirmed else 'ikke bekræftet',
              'ISIN i get_asset:', 'ja' if valid(raw_isin) else 'nej',
              'præcise søgeresultater:', len(exact),
              'ISIN i søgning:', 'ja' if valid(search_isin) else 'nej')
        if valid(raw_isin) and valid(search_isin) and raw_isin != search_isin:
            print(ticker, 'Plutos ISIN-felter er modstridende'); continue
        isin = raw_isin if valid(raw_isin) else search_isin if valid(search_isin) else None
        name = node.get('name') or (exact[0].get('name') if len(exact) == 1 else None)
        result = search_eodhd_symbols(app.connect, uid, {'quote_currency': req['quote_currency']},
                                      candidate_override={'ticker': ticker, 'company_name': name})
        choices = result.get('choices', [])
        count = sum(x.get('isin') == isin and x.get('currency') == req['quote_currency'] for x in choices) if isin else None
        print(ticker, 'EODHD-kandidater:', len(choices),
              'med ISIN:', sum(valid(x.get('isin')) for x in choices),
              'entydige ISIN/valuta-match:', count if count is not None else 'kan ikke afgøres uden Pluto-ISIN')
    except Exception as error:
        code = getattr(error, 'code', type(error).__name__)
        print(ticker, 'opslag:', code if isinstance(code, str) and re.fullmatch('[A-Za-z0-9_]{1,80}', code) else type(error).__name__)
