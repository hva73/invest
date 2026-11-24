"""Owner-run bounded read-only SQLite storage census; no copies or mutations."""
import argparse
import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from contextlib import closing

LIVE=Path("/home/nordicr4/escape_app/var/escape.db")

# Fixed source-schema allowlist; never interpolate caller-supplied SQL or values.
TABLES = {
    "hw_samples": ("payload", "event_epoch", True),
    "hw_context_events": ("payload", "observed", False),
    "hw_calculations": ("payload", "calculated", False),
    "hw_events": ("payload", "created", False),
    "jobs": ("result", "created", True),
    "market_asset_cache": ("payload", "fetched", True),
    "market_asset_period_cache": ("payload", "fetched", True),
    "portfolio_snapshots": ("payload", "observed", False),
    "hw_reference_cache": ("raw", None, False),
}
AGE_BUCKETS = ("under_1d", "1_to_7d", "7_to_30d", "30d_or_older", "unknown_or_future")

def table_totals(db, table, now):
    payload, timestamp, numeric = TABLES[table]
    columns = {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")}
    if not columns or payload not in columns or (timestamp and timestamp not in columns):
        return {"status": "schema_unavailable"}
    # One scan, no GROUP BY / sort / JSON materialization. Length is stored
    # payload bytes (not disk allocation or guaranteed reclaimable bytes).
    size = "coalesce(length(CAST(" + payload + " AS BLOB)),0)"
    epoch = ("CASE WHEN typeof(" + timestamp + ") IN ('integer','real') THEN " + timestamp + " END"
             if numeric else "(julianday(" + timestamp + ")-2440587.5)*86400.0") if timestamp else "NULL"
    age = """CASE WHEN ts IS NULL OR ts > :now THEN 4
              WHEN ts > :now-86400 THEN 0 WHEN ts > :now-604800 THEN 1
              WHEN ts > :now-2592000 THEN 2 ELSE 3 END"""
    # Use the same UTC reference time for every bucket. No row values returned.
    fields = ["count(*)", "coalesce(sum(n),0)"]
    for i in range(5):
        fields.extend([f"coalesce(sum(CASE WHEN age={i} THEN 1 ELSE 0 END),0)",
                       f"coalesce(sum(CASE WHEN age={i} THEN n ELSE 0 END),0)"])
    sql = ("WITH raw AS (SELECT " + size + " AS n," + epoch + " AS ts FROM " + table
           + "), bucketed AS (SELECT n," + age + " AS age FROM raw) SELECT "
           + ",".join(fields) + " FROM bucketed")
    row = db.execute(sql, {"now":now}).fetchone()
    return {"status":"ok","rows":row[0],"payload_bytes":row[1],
            "age_buckets":{label:{"rows":row[2+2*i],"payload_bytes":row[3+2*i]}
                           for i,label in enumerate(AGE_BUCKETS)}}

def inspect(path=LIVE, seconds=8, table=None, now=None):
    path=Path(path)
    if table is not None and table not in TABLES:raise ValueError("unknown_table")
    now=time.time() if now is None else now
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
    report={"status":"partial","file_bytes":initial.st_size,"objects":None,"observed_epoch":now,"table":table}
    with closing(sqlite3.connect(path.absolute().as_uri()+"?mode=ro",uri=True,timeout=.15,isolation_level=None)) as db:
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: int(time.monotonic()>=deadline),1000)
        try:
            db.execute("BEGIN")
            report.update(page_size=db.execute("PRAGMA page_size").fetchone()[0],
                          page_count=db.execute("PRAGMA page_count").fetchone()[0],
                          freelist_count=db.execute("PRAGMA freelist_count").fetchone()[0])
            report["freelist_bytes"]=report["page_size"]*report["freelist_count"]
            if table is None:
                # dbstat aggregate mode emits one row per b-tree; avoid a
                # temporary GROUP BY over millions of page rows on a full host.
                rows=db.execute("SELECT name,pgsize,pageno FROM dbstat WHERE aggregate=TRUE").fetchall()
                rows.sort(key=lambda row:row[1],reverse=True)
                report["objects"]=[{"name":name,"bytes":size,"pages":pages} for name,size,pages in rows]
                report["status"]="ok"
            else:
                report["table_totals"]=table_totals(db,table,now)
                report["status"]=report["table_totals"]["status"]
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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table",choices=sorted(TABLES),help="one bounded payload/age scan instead of dbstat")
    args=parser.parse_args()
    try:
        result=inspect(table=args.table)
        print(json.dumps(result,sort_keys=True))
        if result["status"]!="ok":raise SystemExit(2)
    except (OSError,ValueError,sqlite3.Error) as e:
        print(json.dumps({"status":"unavailable","category":type(e).__name__}))
        raise SystemExit(1) from None
