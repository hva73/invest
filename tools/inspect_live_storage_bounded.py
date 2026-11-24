"""Owner-run bounded read-only SQLite storage census; no copies or mutations."""
import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from contextlib import closing

LIVE=Path("/home/nordicr4/escape_app/var/escape.db")

def inspect(path=LIVE, seconds=8):
    path=Path(path)
    if not 0<seconds<=15:raise ValueError("invalid_deadline")
    if path.parent.is_symlink() or path.is_symlink():raise ValueError("unsafe_path")
    initial=path.stat()
    if not stat.S_ISREG(initial.st_mode) or initial.st_uid!=os.getuid():raise ValueError("unsafe_database")
    for suffix in ("-wal","-journal","-shm"):
        if os.path.lexists(str(path)+suffix):raise ValueError("sidecar_present")
    with path.open("rb") as f:header=f.read(20)
    if header[:16]!=b"SQLite format 3\0" or header[18:20]!=b"\x01\x01":
        raise ValueError("unsupported_journal_mode")
    deadline=time.monotonic()+seconds
    report={"status":"partial","file_bytes":initial.st_size,"objects":None}
    with closing(sqlite3.connect(path.absolute().as_uri()+"?mode=ro",uri=True,timeout=.15,isolation_level=None)) as db:
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: int(time.monotonic()>=deadline),1000)
        try:
            db.execute("BEGIN")
            report.update(page_size=db.execute("PRAGMA page_size").fetchone()[0],
                          page_count=db.execute("PRAGMA page_count").fetchone()[0],
                          freelist_count=db.execute("PRAGMA freelist_count").fetchone()[0])
            report["freelist_bytes"]=report["page_size"]*report["freelist_count"]
            rows=db.execute("SELECT name,sum(pgsize),count(*) FROM dbstat GROUP BY name ORDER BY sum(pgsize) DESC").fetchall()
            report["objects"]=[{"name":name,"bytes":size,"pages":pages} for name,size,pages in rows]
            report["status"]="ok"
        except sqlite3.OperationalError as e:
            report["reason"]="deadline" if time.monotonic()>=deadline else "busy_or_dbstat_unavailable"
        finally:
            if db.in_transaction:db.rollback()
    current=path.stat()
    if (initial.st_dev,initial.st_ino)!=(current.st_dev,current.st_ino):raise ValueError("database_replaced")
    report["scope"]="live_read_only_aggregate"
    report["elapsed_seconds"]=round(seconds-max(0,deadline-time.monotonic()),3)
    return report

if __name__=="__main__":
    try:print(json.dumps(inspect(),sort_keys=True))
    except (OSError,ValueError,sqlite3.Error) as e:
        print(json.dumps({"status":"unavailable","category":type(e).__name__}))
        raise SystemExit(1) from None
