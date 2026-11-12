"""Local HOT WATCH watchdog, started once when Passenger loads the app.

The host must permit detached processes; for host-wide persistence use its
native process supervisor as well. No credentials are written to disk or logs.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
VAR = ROOT / 'var'
ENABLED = VAR / 'hotwatch-autostart.enabled'
DISABLED = VAR / 'hotwatch-autostart.disabled'


def lock(name):
    import app
    path = Path(app.DB).resolve().parent / ('hotwatch-' + name + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def marker(path):
    VAR.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    os.close(fd)


def enabled():
    return ENABLED.is_file() and not ENABLED.is_symlink() and not DISABLED.exists() and os.environ.get('ESCAPE_HW_AUTOSUPERVISE', '1') != '0'


def start_if_enabled():
    if not enabled():
        return False
    subprocess.Popen([sys.executable, str(ROOT / 'hotwatch_supervisor.py'), '--run'], cwd=str(ROOT), env=os.environ.copy(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    return True


def environment():
    env = os.environ.copy()
    for key, value in {'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1', 'ESCAPE_HW_EODHD_FUSE_ENABLED':'1', 'ESCAPE_HW_EODHD_BARS_ENABLED':'1', 'ESCAPE_HW_EODHD_WS_EU_EXCHANGES':'CO,XETRA,AS,ST,OL'}.items():
        env.setdefault(key, value)
    if env.get('ESCAPE_EODHD_API_KEY'):
        env.setdefault('ESCAPE_HW_EODHD_REST_ENABLED', '1')
    return env


def report(status, reason, attempts):
    try:
        import app
        with app.connect() as c:
            c.execute('INSERT INTO hw_supervisor_status VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status,reason=excluded.reason,attempts=excluded.attempts', (datetime.now(timezone.utc).isoformat(), status, reason, attempts))
        return True
    except Exception:
        return False


def heartbeat():
    try:
        import app
        with app.connect() as c:
            row = c.execute('SELECT updated,status FROM hw_heartbeat WHERE id=1').fetchone()
        if row and row['status'] == 'running':
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(row['updated'])).total_seconds()
            return 0 <= age < 20
    except (Exception,):
        pass
    return False


def diagnostic(event, code=None):
    """Persist bounded, non-sensitive lifecycle codes; never log exception text."""
    allowed = {'supervisor_started', 'supervisor_signal', 'supervisor_stopped',
               'worker_started', 'worker_exited', 'worker_start_failed',
               'heartbeat_timeout', 'restart_timeout', 'worker_killed',
               'worker_exception', 'worker_frame_service', 'worker_frame_engine',
               'worker_frame_app', 'worker_frame_adapters', 'worker_frame_other',
               'worker_sqlite_error', 'worker_database_busy',
               'db_lock_worker', 'db_lock_supervisor', 'db_lock_passenger',
               'db_lock_other', 'db_lock_unknown', 'db_lock_unavailable', 'db_lock_none', 'db_lock_probe'}
    if event not in allowed or (code is not None and not isinstance(code, int)):
        raise ValueError('invalid diagnostic event')
    try:
        import app
        with app.connect() as c:
            c.execute('INSERT INTO hw_supervisor_events(created,event,code) VALUES(?,?,?)',
                      (datetime.now(timezone.utc).isoformat(), event, code))
            c.execute('DELETE FROM hw_supervisor_events WHERE id NOT IN (SELECT id FROM hw_supervisor_events ORDER BY id DESC LIMIT 200)')
    except Exception:
        pass


APPLICATION_AREAS = {'site_hotwatch', 'site_state', 'site_portfolio', 'site_portfolio_list', 'mcp_hotwatch'}
APPLICATION_MODULES = {'app', 'intel_workflows', 'hotwatch_engine', 'hotwatch_adapters',
                       'hotwatch_service', 'portfolio_data', 'mcp_client', 'mcp_reports',
                       'oauth', 'report_ingest', 'dashboard_projection', 'sector_intelligence'}
APPLICATION_EVENTS = APPLICATION_AREAS | {'site_sqlite_error', 'site_http_error'} | {
    'site_frame_' + name for name in APPLICATION_MODULES}


def application_error_fallback(entries=None):
    """Bounded private fallback, independent of SQLite; never wait for its lock.

    Reads expose only known event names, integer codes and timestamps. No
    exception messages, account identifiers, URLs or credentials are stored.
    """
    import app
    path = Path(app.DB).resolve().with_name('hotwatch-application-errors.json')
    try:
        flags = os.O_RDWR | os.O_CREAT if entries is not None else os.O_RDONLY
        fd = os.open(path, flags | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'r+b' if entries is not None else 'rb') as target:
            fcntl.flock(target, (fcntl.LOCK_EX if entries is not None else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            raw = target.read(65537)
            if len(raw) > 65536:raise ValueError('oversized diagnostic log')
            rows = json.loads(raw) if raw else []
            if not isinstance(rows, list) or len(rows) > 200:raise ValueError('invalid diagnostic log')
            if entries is not None:rows = (rows + entries)[-200:]
            clean = []
            for row in rows:
                if not isinstance(row, dict) or row.get('event') not in APPLICATION_EVENTS:raise ValueError('invalid event')
                code = row.get('code')
                if code is not None and (type(code) is not int or not 0 <= code < 100000):raise ValueError('invalid code')
                created = row.get('created')
                if not isinstance(created, str) or len(created) > 40 or datetime.fromisoformat(created).tzinfo is None:raise ValueError('invalid timestamp')
                clean.append({'created':created, 'event':row['event'], 'code':code})
            if entries is not None:
                os.fchmod(target.fileno(), 0o600)
                target.seek(0);target.write(json.dumps(clean, separators=(',', ':')).encode());target.truncate()
            return {'status':'AVAILABLE', 'events':list(reversed(clean[-30:]))}
    except FileNotFoundError:
        return {'status':'MISSING' if entries is None else 'UNAVAILABLE', 'events':[]}
    except (OSError, ValueError, TypeError):
        return {'status':'UNAVAILABLE', 'events':[]}


def application_error(connect, area, error):
    """Best-effort, bounded error location only; never persist exception text."""
    if area not in APPLICATION_AREAS:return False
    import sqlite3
    from urllib.error import HTTPError
    if isinstance(error,sqlite3.Error):kind=1
    elif isinstance(error,(ValueError,TypeError,KeyError,IndexError)):kind=2
    elif isinstance(error,TimeoutError):kind=3
    elif isinstance(error,OSError):kind=4
    else:kind=0
    frames=[];tb=error.__traceback__
    while tb:
        name=Path(tb.tb_frame.f_code.co_filename).stem
        wrapper=name=='app' and tb.tb_frame.f_code.co_name in ('execute','executemany','executescript','cursor','__exit__','close')
        wrapper=wrapper or name=='hotwatch_service' and tb.tb_frame.f_code.co_name=='scoped'
        if name in APPLICATION_MODULES and not wrapper:frames.append((name,tb.tb_lineno))
        tb=tb.tb_next
    entries=[(area,kind)]
    if isinstance(error,sqlite3.Error):
        code=getattr(error,'sqlite_errorcode',None)
        entries.append(('site_sqlite_error',code if type(code) is int and 0<=code<=65535 else None))
    if isinstance(error, HTTPError):
        entries.append(('site_http_error',error.code if type(error.code) is int and 100<=error.code<=599 else None))
    if frames:
        name,line=frames[-1];entries.append(('site_frame_'+name,line if 0<line<100000 else None))
    created=datetime.now(timezone.utc).isoformat()
    try:
        with connect() as c:
            c.execute('PRAGMA busy_timeout=100')
            c.executemany('INSERT INTO hw_supervisor_events(created,event,code) VALUES(?,?,?)',[(created,event,code) for event,code in entries])
            c.execute('DELETE FROM hw_supervisor_events WHERE id NOT IN (SELECT id FROM hw_supervisor_events ORDER BY id DESC LIMIT 200)')
        return True
    except Exception:
        rows=[{'created':created,'event':event,'code':code} for event,code in entries]
        return application_error_fallback(rows)['status']=='AVAILABLE'


def lock_category(pid):
    try:
        with open('/proc/%d/cmdline' % pid, 'rb') as source:
            args = source.read(8192).split(b'\0')
        names = {os.path.basename(arg).decode('ascii', 'ignore') for arg in args if arg}
        if 'hotwatch_service.py' in names:return 'worker'
        if 'hotwatch_supervisor.py' in names:return 'supervisor'
        if any('passenger' in name.lower() for name in names):return 'passenger'
        return 'other'
    except OSError:
        return 'unknown'


def fallback_database_locks(path, unavailable_code):
    """Ask the kernel for conflicting SQLite byte locks in an isolated process.

    A separate process is essential: closing any DB fd in the worker could
    release that process's SQLite POSIX locks. The query acquires no lock.
    """
    code = '''import fcntl,json,os,struct,sys
path=sys.stdin.read(8192)
fd=os.open(path,os.O_RDONLY)
try:
 found=[]
 for offset,length in ((1073741824,1),(1073741825,1),(1073741826,510)):
  query=struct.pack('hhqqi4x',fcntl.F_WRLCK,os.SEEK_SET,offset,length,0)
  mode,_,_,_,pid=struct.unpack('hhqqi4x',fcntl.fcntl(fd,fcntl.F_GETLK,query))
  if mode in (fcntl.F_RDLCK,fcntl.F_WRLCK) and pid>0:found.append([pid,mode==fcntl.F_WRLCK])
 print(json.dumps(found))
finally:os.close(fd)
'''
    try:
        import json
        result = subprocess.run([sys.executable, '-c', code], input=str(path),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=2, check=True)
        rows=json.loads(result.stdout)
        if not isinstance(rows,list) or len(rows)>3:raise ValueError('invalid probe')
        counts={}
        for item in rows:
            if not isinstance(item,list) or len(item)!=2 or type(item[0]) is not int or item[0]<=0 or type(item[1]) is not bool:raise ValueError('invalid probe')
            key=('db_lock_'+lock_category(item[0]),1 if item[1] else -1)
            counts[key]=counts.get(key,0)+1
        return [('db_lock_probe',None)]+([(event,sign*count) for (event,sign),count in sorted(counts.items())] if counts else [('db_lock_none',None)])
    except (OSError, ValueError, subprocess.SubprocessError):
        return [('db_lock_unavailable',unavailable_code)]


def database_locks():
    """Sample kernel locks for this DB after BUSY; never expose paths or command lines.

    Counts are only a point-in-time observation, not proof of the blocker.
    Hosts can restrict /proc or use lock types not visible here.
    """
    try:
        import app
        db = os.stat(app.DB)
        identity = (os.major(db.st_dev), os.minor(db.st_dev), db.st_ino)
    except (OSError, ValueError):
        return [('db_lock_unavailable', -1)]
    try:
        with open('/proc/locks', encoding='ascii') as source:
            # Shared hosts can have large lock tables. Retain a bounded read;
            # an incomplete snapshot is explicitly unavailable, never empty.
            lines = source.read(8_000_001)
        if len(lines) > 8_000_000:
            return fallback_database_locks(app.DB, -2)
    except OSError as error:
        return fallback_database_locks(app.DB, error.errno if isinstance(error.errno,int) and 0 < error.errno < 256 else -3)
    except ValueError:
        return fallback_database_locks(app.DB, -3)
    counts = {}
    for line in lines.splitlines():
        fields = line.split()
        if len(fields) < 8 or fields[1] != 'POSIX' or fields[3] not in ('READ', 'WRITE'):
            continue
        try:
            device = fields[5].split(':')
            if len(device) != 3 or (int(device[0], 16), int(device[1], 16), int(device[2])) != identity:
                continue
            pid = int(fields[4])
            if pid <= 0:continue
        except (ValueError, IndexError):
            continue
        category = lock_category(pid)
        # Positive = observed write locks, negative = observed read locks.
        key = ('db_lock_' + category, 1 if fields[3] == 'WRITE' else -1)
        counts[key] = counts.get(key, 0) + 1
    if not counts:return [('db_lock_none', None)]
    # At most one aggregated entry per category and lock type, bounded output.
    return [(event, sign * count) for (event, sign), count in sorted(counts.items())]


def record_database_locks(observations):
    allowed = {'db_lock_worker', 'db_lock_supervisor', 'db_lock_passenger',
               'db_lock_other', 'db_lock_unknown', 'db_lock_unavailable', 'db_lock_none', 'db_lock_probe'}
    rows = [(datetime.now(timezone.utc).isoformat(), event, code)
            for event, code in observations[:10]
            if event in allowed and (code is None or type(code) is int and -10000 <= code <= 10000)]
    if not rows:return
    try:
        import app
        with app.connect() as c:
            c.execute('PRAGMA busy_timeout=100')
            c.executemany('INSERT INTO hw_supervisor_events(created,event,code) VALUES(?,?,?)', rows)
            c.execute('DELETE FROM hw_supervisor_events WHERE id NOT IN (SELECT id FROM hw_supervisor_events ORDER BY id DESC LIMIT 200)')
    except Exception:
        # Diagnosis must not interrupt the trading safety path or wait for a lock.
        pass


def run(timeout=300):
    fd = lock('supervisor')
    if fd is None:
        return
    stop = False
    stop_signal = None
    def shutdown(signum, _frame):
        nonlocal stop, stop_signal
        stop_signal = signum
        stop = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    child = None
    attempts = 0
    failures_since = None
    healthy_since = None
    unhealthy_since = None
    next_start = 0
    child_started_at = None
    child_had_heartbeat = False
    last_report = None
    last_report_at = None
    def report_periodic(status, reason, count, now):
        nonlocal last_report, last_report_at
        value = (status, reason, count)
        if value != last_report or last_report_at is None or now - last_report_at >= 10:
            if report(status, reason, count) is not False:
                last_report, last_report_at = value, now
    diagnostic('supervisor_started')
    try:
        while not stop and enabled():
            now = time.monotonic()
            fresh = heartbeat()
            if child and child.poll() is not None:
                diagnostic('worker_exited', child.returncode)
                # A worker that ran for at least a minute with a heartbeat is
                # not a failed startup. Give its later crash a fresh bounded
                # restart window; rapid startup failures remain bounded.
                if child_had_heartbeat and child_started_at is not None and now - child_started_at >= 60:
                    failures_since = None
                    attempts = 0
                child = None
                fresh = False
            if fresh:
                if child is not None:child_had_heartbeat = True
                unhealthy_since = None
                healthy_since = healthy_since or now
                if now - healthy_since >= 60:
                    failures_since = None
                    attempts = 0
                report_periodic('running', '', attempts, now)
            else:
                healthy_since = None
                if unhealthy_since is None:
                    unhealthy_since = now
                if child and now - unhealthy_since > 45:
                    diagnostic('heartbeat_timeout')
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        diagnostic('worker_killed')
                        child.kill()
                        child.wait()
                    if child_had_heartbeat and child_started_at is not None and now - child_started_at >= 60:
                        failures_since = None
                        attempts = 0
                    child = None
                    unhealthy_since = None
                if child is None and now >= next_start:
                    failures_since = failures_since or now
                    if now - failures_since >= timeout:
                        diagnostic('restart_timeout')
                        report('timeout', 'restart_timeout', attempts)
                        return
                    attempts += 1
                    try:
                        child = subprocess.Popen([sys.executable, str(ROOT / 'hotwatch_service.py'), '--interval', '2'], cwd=str(ROOT), env=environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
                        diagnostic('worker_started')
                        unhealthy_since = now
                        child_started_at = now
                        child_had_heartbeat = False
                    except OSError as error:
                        diagnostic('worker_start_failed', error.errno if isinstance(error.errno, int) else None)
                        child = None
                    next_start = now + min(30, 2 ** min(attempts, 5))
                report_periodic('restarting', 'waiting_for_heartbeat', attempts, now)
            time.sleep(2)
    finally:
        if stop_signal is not None:
            diagnostic('supervisor_signal', stop_signal)
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if stop or not enabled():
            report('stopped', 'signal' if stop else 'disabled', attempts)
        diagnostic('supervisor_stopped')
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--disable', action='store_true')
    args = parser.parse_args()
    if args.enable:
        DISABLED.unlink(missing_ok=True)
        marker(ENABLED)
        start_if_enabled()
        print('Automatisk motorstart aktiveret.')
    elif args.disable:
        marker(DISABLED)
        ENABLED.unlink(missing_ok=True)
        print('Automatisk motorstart deaktiveret; overvågeren stopper sin motor.')
    elif args.run:
        run()
    else:
        parser.error('Vælg --enable eller --disable')

if __name__ == '__main__':
    main()
