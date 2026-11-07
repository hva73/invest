"""Inspect existing EODHD access without printing credentials or changing holdings."""
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
workers=[]
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        args=(proc/'cmdline').read_bytes().split(b'\0')
        if proc.stat().st_uid==os.getuid() and any(x.endswith(b'/hotwatch_service.py') for x in args) and b'--once' not in args and b'--probe-eodhd' not in args:
            workers.append(proc)
    except OSError:
        pass
if len(workers)!=1:
    raise SystemExit('Forventede én kørende motor; fandt '+str(len(workers)))
try:
    env=dict(x.split(b'=',1) for x in (workers[0]/'environ').read_bytes().split(b'\0') if b'=' in x)
    for key in ('ESCAPE_DB','ESCAPE_EODHD_API_KEY','ESCAPE_HW_EODHD_REST_ENABLED','ESCAPE_HW_REQUESTS_PER_MINUTE','ESCAPE_HW_EODHD_REQUESTS_PER_MINUTE'):
        if key.encode() in env:
            os.environ[key]=env[key.encode()].decode()
    del env
    import app
    from eodhd_feeds import EODHDFeeds, HTTP_BASE
    from hotwatch_adapters import reserve
    feed=EODHDFeeds(os.environ.get('ESCAPE_EODHD_API_KEY',''),reserve=lambda:reserve(app.connect,0,'eodhd',purpose='sector'))
    for field in ('ETF_Data::Holdings','ETF_Data::Top_10_Holdings'):
        response=feed._http(HTTP_BASE,'/fundamentals/XLU.US',{'fmt':'json','filter':field})
        payload=response.get('payload')
        count=len(payload) if isinstance(payload,(dict,list)) else 0
        print('XLU',field,'status:',response.get('status'),'HTTP:',response.get('http_status','-'),'antal:',count)
    for code in ('EXH6','EXH4','EXH1','EXV6'):
        response=feed._http(HTTP_BASE,'/search/'+code,{'fmt':'json','limit':'20'})
        rows=response.get('payload') if response.get('status')=='OK' else []
        print('EUROPA',code,'status:',response.get('status'))
        for row in rows if isinstance(rows,list) else []:
            if not isinstance(row,dict):continue
            if str(row.get('Code','')).upper()!=code:continue
            print(' ',{k:row.get(k) for k in ('Code','Exchange','Name','Currency','Type')})
except Exception:
    raise SystemExit('Diagnose kunne ikke gennemføres; ingen nøgle eller svartekst er vist.')
