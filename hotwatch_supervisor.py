"""Local HOT WATCH watchdog, started once when Passenger loads the app.

The host must permit detached processes; for host-wide persistence use its
native process supervisor as well. No credentials are written to disk or logs.
"""
import argparse
import fcntl
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
    for key, value in {'ESCAPE_HW_EODHD_WS_TRADES_ENABLED':'1', 'ESCAPE_HW_EODHD_FUSE_ENABLED':'1', 'ESCAPE_HW_EODHD_BARS_ENABLED':'1', 'ESCAPE_HW_EODHD_WS_EU_EXCHANGES':'CO'}.items():
        env.setdefault(key, value)
    if env.get('ESCAPE_EODHD_API_KEY'):
        env.setdefault('ESCAPE_HW_EODHD_REST_ENABLED', '1')
    return env


def report(status, reason, attempts):
    try:
        import app
        with app.connect() as c:
            c.execute('INSERT INTO hw_supervisor_status VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,status=excluded.status,reason=excluded.reason,attempts=excluded.attempts', (datetime.now(timezone.utc).isoformat(), status, reason, attempts))
    except Exception:
        pass


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
               'worker_sqlite_error', 'worker_database_busy'}
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
    diagnostic('supervisor_started')
    try:
        while not stop and enabled():
            now = time.monotonic()
            fresh = heartbeat()
            if child and child.poll() is not None:
                diagnostic('worker_exited', child.returncode)
                child = None
                fresh = False
            if fresh:
                unhealthy_since = None
                healthy_since = healthy_since or now
                if now - healthy_since >= 60:
                    failures_since = None
                    attempts = 0
                report('running', '', attempts)
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
                    except OSError as error:
                        diagnostic('worker_start_failed', error.errno if isinstance(error.errno, int) else None)
                        child = None
                    next_start = now + min(30, 2 ** min(attempts, 5))
                report('restarting', 'waiting_for_heartbeat', attempts)
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
