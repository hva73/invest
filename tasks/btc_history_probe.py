"""Read-only test of actual EODHD BTC minute history and source timestamps."""
import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
workers=[]
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit(): continue
    try:
        args=(proc/'cmdline').read_bytes().split(b'\0')
        if proc.stat().st_uid==os.getuid() and any(x.endswith(b'/hotwatch_service.py') for x in args) and b'--once' not in args and b'--probe-eodhd' not in args: workers.append(proc)
    except OSError: pass
if len(workers)!=1: raise SystemExit('Forventede én kørende motor; fandt '+str(len(workers)))
env=dict(x.split(b'=',1) for x in (workers[0]/'environ').read_bytes().split(b'\0') if b'=' in x)
for key in ('ESCAPE_DB','ESCAPE_TOKEN_KEY_FILE','ESCAPE_EODHD_API_KEY','ESCAPE_HW_EODHD_REST_ENABLED','ESCAPE_HW_REQUESTS_PER_MINUTE','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE','PLUTO_CLIENT_ID'):
    if key.encode() in env: os.environ[key]=env[key.encode()].decode()

import app
from eodhd_feeds import EODHDFeeds
from hotwatch_adapters import reserve
from hotwatch_contract import stamp

try:
    with app.connect() as con:
        row=con.execute("SELECT user_id FROM hw_sessions WHERE is_test=0 AND purpose='automatic holding watch' AND status IN ('CREATED','VALIDATING','ACTIVE','DEGRADED') AND json_extract(request,'$.asset_id')='54368e0b-2d53-401e-bf68-1033a5b84b08' AND json_extract(request,'$.provider_symbol')='BTC-USD.CC' ORDER BY id DESC LIMIT 1").fetchone()
    if not row: raise SystemExit('Ingen aktiv BTC-USD.CC-session fundet')
    now=datetime.now(timezone.utc);end=int(now.timestamp());client=EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),reserve=lambda:reserve(app.connect,row['user_id'],'eodhd',purpose='holding_identity'))
    response=client.intraday('BTC-USD.CC',interval='1m',start=end-7200,end=end)
    bars=response.get('bars') or []; closed=[b for b in bars if 0<=(now-stamp(b['bar_open_at'])).total_seconds()-60]
    contiguous=0;last=None
    for bar in reversed(closed):
        current=stamp(bar['bar_open_at'])
        if last is not None and (last-current).total_seconds()!=60: break
        contiguous+=1;last=current
    last_at=closed[-1]['bar_open_at'] if closed else None
    print('RESULTAT:', json.dumps({'symbol':'BTC-USD.CC','status':response.get('status'),'antal_lukkede':len(closed),'sammenhængende_seneste':contiguous,'første':closed[0]['bar_open_at'] if closed else None,'seneste':last_at,'seneste_sluttid_alder_sek':round((now-stamp(last_at)).total_seconds()-60,1) if last_at else None,'undersøgt_utc':now.isoformat()},ensure_ascii=False))
except Exception as error:
    code=getattr(error,'code',None)
    if not isinstance(code,str) or not re.fullmatch('[A-Za-z0-9_]{1,80}',code): code=type(error).__name__
    print('OPSLAG FEJLEDE:',code)
