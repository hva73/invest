"""Compare the latest NOVOB observation with one read-only provider scan."""
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
keys = ('ESCAPE_DB','ESCAPE_TOKEN_KEY_FILE','ESCAPE_EODHD_API_KEY','ESCAPE_HW_EODHD_REST_ENABLED','ESCAPE_HW_REQUESTS_PER_MINUTE','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE','ESCAPE_HW_EODHD_WS_TRADES_ENABLED','ESCAPE_HW_EODHD_FUSE_ENABLED','ESCAPE_HW_EODHD_BARS_ENABLED','ESCAPE_HW_EODHD_FAST_POLL_ENABLED','ESCAPE_HW_EODHD_MIN_POLL_S','PLUTO_CLIENT_ID')
for key in keys:
    if key.encode() in env:
        os.environ[key] = env[key.encode()].decode()

import app
from hotwatch_adapters import EODHDAdapter
import hotwatch_engine as engine

try:
    with app.connect() as con:
        btc = con.execute("SELECT * FROM hw_sessions WHERE is_test=0 AND purpose='automatic holding watch' AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND json_extract(request,'$.ticker')='BTC' ORDER BY id").fetchall()
        print('NU UTC:', engine.utc().isoformat())
        for item in btc:
            view = engine.view(con, item)
            print('BTC:', json.dumps({'session':item['id'], 'kilde':view['request']['provider'], 'kurstid':view['last_data_at'], 'kurstilstand':view['data_status']['quote_freshness'], 'status':view['display_status'], 'interval_sek':view['effective_min_interval_s'], 'næste_scan':view['next_due_at'], 'fejl':view['last_error']}, ensure_ascii=False))
        row = con.execute("SELECT * FROM hw_sessions WHERE is_test=0 AND purpose='automatic holding watch' AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND json_extract(request,'$.ticker')='NOVOB' ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit('Ingen aktiv NOVOB-session fundet')
    session = dict(row)
    session['request_data'] = json.loads(session['request'])
    current = EODHDAdapter(app.connect, row['user_id']).poll(session)
    with app.connect() as con:
        saved = con.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? AND source=? AND sample_id=?', (row['id'],current['source'],current['sample_id'])).fetchone()
        if not saved and row['last_data'] == current['event_time']:
            saved = con.execute('SELECT payload FROM hw_samples WHERE watch_row_id=? AND source=? ORDER BY event_epoch DESC,id DESC LIMIT 1', (row['id'],current['source'])).fetchone()
    if not saved:
        print('INGEN TIDLIGERE OBSERVATION MED SAMME ID ELLER KURSTID')
        print('KURSTID:', current['event_time'], 'KURS:', current['price'])
    else:
        previous = json.loads(saved['payload'])
        before = {k:v for k,v in previous.items() if k not in ('context','sample_id')}
        after = {k:v for k,v in current.items() if k not in ('context','sample_id')}
        print('GEMT KURSTID:', previous.get('event_time'), 'KURS:', previous.get('price'))
        print('NY KURSTID:', current.get('event_time'), 'KURS:', current.get('price'))
        print('FORSKELLIGE FELTER:', ', '.join(sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))) or 'ingen')
except Exception as error:
    code = getattr(error, 'code', None)
    if not isinstance(code, str) or not re.fullmatch('[A-Za-z0-9_]{1,80}', code):
        code = type(error).__name__
    print('OPSLAG FEJLEDE:', code)
