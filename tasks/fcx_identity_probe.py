"""Read-only FCX provider identity diagnosis; only the existing request budget changes."""
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
workers = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        args = (proc / 'cmdline').read_bytes().split(b'\0')
        if proc.stat().st_uid == os.getuid() and any(x.endswith(b'/hotwatch_service.py') for x in args) and b'--once' not in args and b'--probe-eodhd' not in args:
            workers.append(proc)
    except OSError:
        pass
if len(workers) != 1:
    raise SystemExit('Forventede én kørende motor; fandt ' + str(len(workers)))
env = dict(x.split(b'=', 1) for x in (workers[0] / 'environ').read_bytes().split(b'\0') if b'=' in x)
for key in ('ESCAPE_DB', 'ESCAPE_TOKEN_KEY_FILE', 'ESCAPE_EODHD_API_KEY', 'ESCAPE_HW_EODHD_REST_ENABLED', 'ESCAPE_HW_REQUESTS_PER_MINUTE', 'ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE', 'PLUTO_CLIENT_ID'):
    if key.encode() in env:
        os.environ[key] = env[key.encode()].decode()

import app
from hotwatch_service import holding_instrument
from hotwatch_adapters import search_eodhd_symbols
from instrument_resolver import resolve_us
from eodhd_us_reference import get_reference

try:
    with app.connect() as con:
        row = con.execute("SELECT user_id,request FROM hw_sessions WHERE is_test=0 AND purpose='automatic holding watch' AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND json_extract(request,'$.ticker')='FCX' ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit('Ingen aktiv FCX-beholdningssession fundet')
    req = json.loads(row['request'])
    holding = {'asset_id':req['asset_id'], 'ticker':req['ticker'], 'currency':req['quote_currency']}
    pluto = holding_instrument(app.connect, row['user_id'], holding)
    if not pluto:
        raise SystemExit('Pluto-identiteten kunne ikke læses')
    print('PLUTO:', json.dumps(pluto, ensure_ascii=False))
    if pluto.get('isin'):
        print('KONTROL: Pluto leverer ISIN; US-noteringskontrollen er ikke den anvendte vej.')
    choices = search_eodhd_symbols(app.connect, row['user_id'], {'quote_currency':holding['currency']}, candidate_override={'ticker':holding['ticker'], 'company_name':pluto.get('name'), 'asset_type':pluto.get('type')}, purpose='holding_identity')['choices']
    print('EODHD SØGNING:', json.dumps(choices, ensure_ascii=False))
    reference = get_reference(app.connect, row['user_id'])
    listing = [x for x in reference['rows'] if x.get('Code') == 'FCX']
    print('EODHD US-LISTE (filtrerede aktier):', json.dumps(listing, ensure_ascii=False))
    print('MATCH:', json.dumps(resolve_us(pluto, choices, listing), ensure_ascii=False))
except Exception as error:
    code = getattr(error, 'code', None)
    if not isinstance(code, str) or not re.fullmatch('[A-Za-z0-9_]{1,80}', code):
        code = type(error).__name__
    print('OPSLAG FEJLEDE:', code)
