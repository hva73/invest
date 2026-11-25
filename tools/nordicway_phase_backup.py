"""Private bridge phase-aware quota and lossless compressed snapshot.
Never write to the live database. All backup bytes are verified before code changes.
"""
import gzip, hashlib, json, os, re, sqlite3, stat, subprocess, sys
from pathlib import Path
from contextlib import contextmanager

CAP=20_000_000_000
HEADROOM=256*1024*1024
CHUNK=1024*1024

class SnapshotFailure(RuntimeError):
    """Raised only before the updater enters its mutation phase."""

def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)

def identity(path):
    st=Path(path).lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1:
        raise ValueError("unsafe_snapshot_source")
    return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)

def no_sidecars(path):
    if any(os.path.lexists(str(path)+suffix) for suffix in ("-wal","-journal","-shm")):
        raise ValueError("database_sidecars_present")

def budget(db_bytes, source_bytes, installed_bytes, free):
    # Keep a full DB-sized startup/rollback journal allowance, code staging and
    # code backup, plus 10% with a 256 MiB minimum. Compressed snapshot is extra,
    # but its writer is capped, and no second raw DB is ever created.
    if any(type(v) is not int or v<0 for v in (db_bytes,source_bytes,installed_bytes,free)) or db_bytes<=0:
        raise ValueError("invalid_phase_budget")
    base=db_bytes+2*source_bytes+installed_bytes
    reserve=base+max(HEADROOM,(base+9)//10)+HEADROOM
    cap=min(free-reserve,db_bytes+db_bytes//8+HEADROOM)
    if cap<HEADROOM: raise ValueError("insufficient_phase_space")
    return {"db_bytes":db_bytes,"restart_reserve":reserve,"archive_cap":cap,"required_bytes":reserve+cap}

def available(target,token):
    import nordicway_uapi_quota as q
    if token is None:
        import shutil
        executable=shutil.which("uapi") or "/usr/local/cpanel/bin/uapi"
        result=subprocess.run([executable,"--output=json","StatsBar","get_stats","display=diskusage"],capture_output=True,check=True,timeout=20)
        v=q.parse(json.loads(result.stdout))
    else:
        v=q.read(token)
    fs=os.statvfs(target)
    free=min(v["free_lower_bytes"],CAP-v["used_upper_bytes"],fs.f_bavail*fs.f_frsize)
    if free<=0: raise ValueError("insufficient_phase_space")
    return free

def restart_check(target,token=None,minimum=0):
    db=Path(target)/"var/escape.db"
    n=identity(db)[2]
    for ext in ("-wal","-journal"):
        path=Path(str(db)+ext)
        if os.path.lexists(path): n+=identity(path)[2]
    required=max(minimum,n+max(HEADROOM,(n+9)//10)+HEADROOM)
    if available(target,token)<required:
        raise ValueError("insufficient_restart_reserve")
    return required

def phase_budget(checkout,target,token,manifest):
    source=existing=0
    for name in manifest:
        p=Path(checkout)/name; d=Path(target)/name
        if p.is_symlink() or not p.is_file() or d.is_symlink():
            raise ValueError("unsafe_manifest_file")
        source+=p.stat().st_size
        if d.exists():
            if not d.is_file(): raise ValueError("unsafe_manifest_file")
            existing+=d.stat().st_size
    db=Path(target)/"var/escape.db"
    n=identity(db)[2]
    # Sidecars can appear before stop; account for them conservatively.
    for ext in ("-wal","-journal"):
        p=Path(str(db)+ext)
        if os.path.lexists(p): n+=identity(p)[2]
    return budget(n,source,existing,available(target,token))

class Bounded:
    def __init__(self,raw,limit):
        self.raw,self.limit,self.count=raw,limit,0
    def write(self,data):
        if len(data)>self.limit-self.count:
            raise ValueError("backup_output_cap_exceeded")
        n=self.raw.write(data)
        if n!=len(data): raise OSError("short_backup_write")
        self.count+=n
        return n

def gzip_digest(path,expected_bytes):
    if type(expected_bytes) is not int or expected_bytes<512: raise ValueError("invalid_backup_size")
    before=identity(path); digest=hashlib.sha256(); n=0; header=b""
    with gzip.open(path,"rb") as stream:
        while block:=stream.read(CHUNK):
            if not header: header=block[:20]
            n+=len(block)
            if n>expected_bytes: raise ValueError("backup_size_mismatch")
            digest.update(block)
    if n!=expected_bytes or header[:16]!=b"SQLite format 3\x00" or header[18:20]!=b"\x01\x01" or identity(path)!=before:
        raise ValueError("backup_size_or_header_mismatch")
    return digest.hexdigest()

def write_snapshot(source,destination,cap,expected_bytes):
    """Child only: copy locked bytes, never open a SQLite connection here."""
    before=identity(source)
    if before[2]!=expected_bytes: raise ValueError("source_size_changed")
    digest=hashlib.sha256(); count=0
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,"wb") as raw:
            out=Bounded(raw,cap)
            with gzip.GzipFile(fileobj=out,filename="",mtime=0,compresslevel=6,mode="wb") as zipped:
                with open(source,"rb") as inp:
                    while block:=inp.read(CHUNK):
                        count+=len(block)
                        if count>expected_bytes: raise ValueError("source_size_changed")
                        digest.update(block); zipped.write(block)
            raw.flush();os.fsync(raw.fileno())
        if count!=expected_bytes or identity(source)!=before or gzip_digest(destination,expected_bytes)!=digest.hexdigest():
            raise ValueError("backup_hash_mismatch")
        sync_dir(Path(destination).parent)
        return digest.hexdigest()
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise

@contextmanager
def snapshot(database,destination,cap,db_limit):
    """Source integrity check under EXCLUSIVE lock; compressed bytes read back.
    Child I/O avoids releasing the parent's POSIX SQLite lock.
    """
    connection=None
    database=Path(database); destination=Path(destination)
    if os.path.lexists(destination): raise SnapshotFailure("backup_destination_exists")
    try:
        try:
            if database.parent.is_symlink() or destination.parent.is_symlink():
                raise ValueError("unsafe_snapshot_path")
            no_sidecars(database); before=identity(database)
            if before[2]>db_limit: raise ValueError("database_grew_since_budget")
            connection=sqlite3.connect(str(database),timeout=3,isolation_level=None)
            connection.execute("BEGIN EXCLUSIVE")
            no_sidecars(database)
            if connection.execute("PRAGMA journal_mode").fetchone()!=("delete",):
                raise ValueError("unsupported_journal_mode")
            if connection.execute("PRAGMA integrity_check").fetchall()!=[("ok",)]:
                raise ValueError("database_integrity_failed")
            # The subprocess uses this installed module, not a shell command.
            result=subprocess.run([sys.executable,"-I","-S",str(Path(__file__).resolve()),
                                   "snapshot",str(database),str(destination),str(cap),str(before[2])],
                                  capture_output=True,text=True,timeout=900,check=False)
            if result.returncode or not re.fullmatch(r"[0-9a-f]{64}",result.stdout.strip()):
                raise ValueError("compressed_snapshot_failed")
            no_sidecars(database)
            if identity(database)!=before: raise ValueError("database_changed")
            digest=result.stdout.strip()
        except Exception as exc:
            # Only our own new backup is eligible for removal before mutation.
            # O_EXCL in the child guarantees it cannot overwrite an existing file.
            # Timeout may leave a partial file; this path is inside a fresh mkdtemp.
            if destination.is_file() and not destination.is_symlink():
                destination.unlink();sync_dir(destination.parent)
            raise SnapshotFailure(str(exc) if isinstance(exc,ValueError) else type(exc).__name__) from None
        yield {"database_sha256":digest,"database_bytes":before[2],"database_encoding":"gzip"}
    finally:
        if connection is not None:
            if connection.in_transaction: connection.rollback()
            connection.close()

def verify_compressed(backup):
    backup=Path(backup)
    raw=backup/"escape.db"; compressed=backup/"escape.db.gz"; m=backup/"manifest.json"
    if not os.path.lexists(compressed):
        return False
    if os.path.lexists(raw) or m.is_symlink() or not m.is_file() or m.stat().st_size>200000:
        raise ValueError("invalid_compressed_backup")
    data=json.loads(m.read_bytes())
    digest=data.get("database_sha256")
    if data.get("format")!=1 or data.get("database_encoding")!="gzip" or not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
        raise ValueError("invalid_compressed_backup")
    if gzip_digest(compressed,data.get("database_bytes"))!=digest:
        raise ValueError("backup_hash_mismatch")
    return True

if __name__=="__main__":
    if len(sys.argv)!=6 or sys.argv[1]!="snapshot": raise SystemExit(2)
    try: print(write_snapshot(Path(sys.argv[2]),Path(sys.argv[3]),int(sys.argv[4]),int(sys.argv[5])))
    except Exception: raise SystemExit(1) from None
