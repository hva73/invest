"""Owner-run lossless DB maintenance. No deploy, no retention/deletes of rows.
Only replace the live DB after independent logical equality, verified fresh
compressed recovery copy, and a conservative 20 GB release-space calculation.
The installed private bridge supplies lock, stop, drain and health checks.
"""
import argparse
import ast
import gzip
import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
from contextlib import closing

HOME = pathlib.Path("/home/nordicr4")
APP = HOME / "escape_app"
BRIDGE = HOME / ".escape_deploy_bridge"
REPO = HOME / "escape_deploy/invest"
RELEASE = "3cc0c7bec83c529b2c3bb1011e5fcd7011f6ee65"
INSTALLED = "3349c36641b2b8c0edafbe445ba68cba7c7b1bcf"
ADAPTER_HASH = "65d1d5d5178d3afe5092f7e61ae39cc5aabb29948ed34def395ef8d883161ad3"
CAP = 20_000_000_000
MARGIN = 256 * 1024 * 1024

def emit(**value):
    print(json.dumps(value, sort_keys=True), flush=True)

def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def identity(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise ValueError("unsafe_database_file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

def no_sidecars(path):
    if any(os.path.lexists(str(path) + suffix) for suffix in ("-journal", "-wal", "-shm")):
        raise ValueError("database_sidecars_present")

def ro(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)

def ident(name):
    return '"' + name.replace('"', '""') + '"'

def add_hash(h, value):
    if value is None:
        raw, kind = b"", b"n"
    elif isinstance(value, bytes):
        raw, kind = value, b"b"
    elif isinstance(value, str):
        raw, kind = value.encode("utf8"), b"s"
    elif isinstance(value, int):
        raw, kind = str(value).encode("ascii"), b"i"
    elif isinstance(value, float):
        raw, kind = struct.pack(">d", value), b"f"
    else:
        raise ValueError("unexpected_sqlite_type")
    h.update(kind + struct.pack(">Q", len(raw)))
    h.update(raw)

def logical_digest(path):
    """Compare ordered rows, including implicit rowids, without logging data."""
    h = hashlib.sha256()
    with closing(ro(path)) as db:
        db.execute("PRAGMA query_only=ON")
        for name in ("user_version", "application_id", "encoding", "auto_vacuum"):
            add_hash(h, db.execute("PRAGMA " + name).fetchone()[0])
        for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"):
            for value in row:
                add_hash(h, value)
        tables = list(db.execute("PRAGMA table_list"))
        if not tables:
            raise ValueError("table_list_unavailable")
        for schema, name, kind, ncol, without_rowid, strict in sorted(tables):
            if schema != "main" or name in ("sqlite_schema", "sqlite_temp_schema"):
                continue
            if kind == "view":
                continue
            if kind != "table":
                raise ValueError("unsupported_virtual_or_shadow_table")
            columns = list(db.execute("PRAGMA table_xinfo(" + ident(name) + ")"))
            if not columns:
                raise ValueError("table_columns_unavailable")
            names = {row[1].lower() for row in columns}
            if without_rowid:
                keys = sorted((row[5], row[1]) for row in columns if row[5])
                if not keys:
                    raise ValueError("primary_key_unavailable")
                select = "*"
                order = ",".join(ident(key) for _, key in keys)
            else:
                alias = next((v for v in ("rowid","_rowid_","oid") if v not in names), None)
                if alias is None:
                    raise ValueError("rowid_unavailable")
                select, order = alias + ",*", alias
            add_hash(h, name)
            count = 0
            for row in db.execute("SELECT " + select + " FROM " + ident(name) + " ORDER BY " + order):
                h.update(b"r")
                for value in row:
                    add_hash(h, value)
                count += 1
            add_hash(h, count)
    return h.hexdigest()

def verify_compact(source, candidate):
    with closing(ro(candidate)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("candidate_integrity_failed")
    if logical_digest(source) != logical_digest(candidate):
        raise ValueError("logical_content_changed")

def compact(source, candidate):
    no_sidecars(source)
    before = identity(source)
    with closing(ro(source)) as db:
        db.execute("VACUUM INTO ?", (str(candidate),))
    no_sidecars(source)
    if identity(source) != before:
        raise ValueError("source_changed")
    verify_compact(source, candidate)
    if identity(source) != before:
        raise ValueError("source_changed")
    with candidate.open("rb") as f:
        os.fsync(f.fileno())
    return before

def compress_recovery(source, destination, ceiling):
    """Output cap enforced before every physical write; read back all bytes."""
    class Bounded:
        def __init__(self, stream):
            self.stream, self.count = stream, 0
        def write(self, data):
            if len(data) > ceiling - self.count:
                raise ValueError("backup_output_cap_exceeded")
            n = self.stream.write(data)
            if n != len(data):
                raise OSError("short_write")
            self.count += n
            return n
    h = hashlib.sha256()
    with destination.open("xb") as raw:
        os.fchmod(raw.fileno(), 0o600)
        bounded = Bounded(raw)
        with gzip.GzipFile(filename="", fileobj=bounded, mode="wb", mtime=0, compresslevel=3) as out:
            with source.open("rb") as inp:
                while block := inp.read(1024 * 1024):
                    h.update(block)
                    out.write(block)
        raw.flush()
        os.fsync(raw.fileno())
    check = hashlib.sha256()
    size = 0
    with gzip.open(destination, "rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            check.update(block)
    if check.digest() != h.digest() or size != source.stat().st_size:
        raise ValueError("backup_hash_mismatch")
    return h.hexdigest()

def quota():
    import nordicway_uapi_quota as q
    executable = shutil.which("uapi") or "/usr/local/cpanel/bin/uapi"
    p = subprocess.run([executable, "--output=json", "StatsBar", "get_stats", "display=diskusage"],
                       capture_output=True, text=True, check=True, timeout=20)
    v = q.parse(json.loads(p.stdout))
    free = min(v["free_lower_bytes"], CAP - v["used_upper_bytes"], shutil.disk_usage(APP).free)
    if free <= 0:
        raise ValueError("quota_unavailable")
    return free

def release_required(new_size):
    p = subprocess.run(["git", "-C", str(REPO), "show", RELEASE + ":apply_update.py"],
                       capture_output=True, check=True, timeout=20)
    tree = ast.parse(p.stdout.decode("utf8"))
    matches = [n.value for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
               and isinstance(n.targets[0],ast.Name) and n.targets[0].id=="FILES"]
    if len(matches) != 1:
        raise ValueError("candidate_manifest_unavailable")
    names = ast.literal_eval(matches[0])
    if not isinstance(names,tuple) or len(names)!=81:
        raise ValueError("candidate_manifest_changed")
    p = subprocess.run(["git","-C",str(REPO),"ls-tree","-r","-l",RELEASE,"--",*names],
                       capture_output=True,check=True,timeout=20,text=True)
    sizes = {}
    for line in p.stdout.splitlines():
        metadata, name = line.split("\t",1)
        mode, kind, sha, size = metadata.split()
        if kind != "blob" or not size.isdigit() or mode not in ("100644","100755"):
            raise ValueError("unsafe_release_file")
        sizes[name] = int(size)
    if set(sizes)!=set(names):
        raise ValueError("candidate_files_missing")
    existing = 0
    for name in names:
        path = APP / name
        if path.is_symlink():
            raise ValueError("unsafe_installed_file")
        if path.exists():
            if not path.is_file():
                raise ValueError("unsafe_installed_file")
            existing += path.stat().st_size
    base = 2 * new_size + 2 * sum(sizes.values()) + existing
    return base + max(MARGIN, (base+9)//10)

def main():
    if sys.platform != "linux":
        raise ValueError("server_linux_required")
    bridge_info = BRIDGE.lstat()
    if not stat.S_ISDIR(bridge_info.st_mode) or bridge_info.st_uid != os.getuid() or bridge_info.st_mode & 0o077:
        raise ValueError("unsafe_bridge")
    module = BRIDGE / "nordicway_deploy_adapter.py"
    if module.is_symlink() or hashlib.sha256(module.read_bytes()).hexdigest() != ADAPTER_HASH:
        raise ValueError("private_adapter_changed")
    sys.path.insert(0,str(BRIDGE))
    import nordicway_deploy_adapter as bridge
    adapter = bridge.Adapter(REPO, APP, RELEASE, 1, None, None)
    source = APP / "var/escape.db"
    gate = BRIDGE / "deploy-enabled"
    held = BRIDGE / "deploy-enabled.maintenance-held"
    marker = BRIDGE / "deployment-incomplete.json"
    backup_dir = HOME / ".escape_backups"
    backup_info = backup_dir.lstat()
    if not stat.S_ISDIR(backup_info.st_mode) or backup_info.st_uid != os.getuid() or backup_info.st_mode & 0o077:
        raise ValueError("unsafe_backup_directory")
    if source.parent.is_symlink():
        raise ValueError("unsafe_database_directory")
    def check():
        if os.path.lexists(held) or os.path.lexists(marker) or gate.is_symlink() or gate.read_bytes()!=b"1\n":
            raise ValueError("deployment_gate_unavailable")
        if (APP/"BUILD_COMMIT").read_text().strip()!=INSTALLED or (BRIDGE/"approved-sha").read_text().strip()!=RELEASE:
            raise ValueError("version_changed")
    check()
    with adapter.lock():
        check()
        before = identity(source)
        no_sidecars(source)
        free = quota()
        old_size = before[2]
        if free < old_size + 2*MARGIN:
            raise ValueError("insufficient_compaction_workspace")
        release_required(old_size) # validate exact candidate before service stop
        if adapter.service_status()!="started":
            raise ValueError("service_not_started")
        os.replace(gate, held)
        sync_dir(BRIDGE)
        stopped, swapped, healthy = False, False, False
        try:
            if os.path.lexists(marker):
                raise ValueError("concurrent_deploy")
            stopped = True
            adapter.stop_service()
            with adapter.quiescence():
                no_sidecars(source)
                before = identity(source)
                old_size = before[2]
                if quota() < old_size + 2*MARGIN:
                    raise ValueError("insufficient_compaction_workspace")
                with tempfile.TemporaryDirectory(prefix=".escape-compact-", dir=source.parent) as td:
                    work = pathlib.Path(td)
                    candidate = work / "candidate.sqlite"
                    emit(status="compacting", old_bytes=old_size)
                    before = compact(source,candidate)
                    new_size = candidate.stat().st_size
                    required = release_required(new_size) + MARGIN
                    reclaim = min(source.stat().st_blocks*512, old_size)
                    free_now = quota()
                    # Free space after the atomic replacement is the current
                    # quota plus removed original, less the recovery archive.
                    ceiling = min(free_now-MARGIN, free_now+reclaim-required)
                    emit(status="verified_candidate", old_bytes=old_size, compact_bytes=new_size,
                         release_required_bytes=required, recovery_archive_cap_bytes=max(0,ceiling))
                    if ceiling<=0 or new_size>=old_size:
                        raise ValueError("compaction_insufficient_for_release")
                    archive = work / "recovery.sqlite.gz"
                    original_sha = compress_recovery(source,archive,ceiling)
                    if identity(source)!=before:
                        raise ValueError("source_changed")
                    no_sidecars(source)
                    if quota()+reclaim < required:
                        raise ValueError("insufficient_release_reserve")
                    if os.path.lexists(marker) or os.path.lexists(gate):
                        raise ValueError("concurrent_deploy")
                    # Publish durable recovery file and manifest before the
                    # single atomic DB replacement; old retained backup stays.
                    dest = backup_dir / ("maintenance-" + work.name.lstrip(".") + ".sqlite.gz")
                    manifest = dest.with_suffix(".json")
                    os.link(archive,dest)
                    with manifest.open("x") as f:
                        os.fchmod(f.fileno(),0o600)
                        json.dump({"original_sha256":original_sha,"original_bytes":old_size,
                                   "archive_bytes":dest.stat().st_size,"installed_sha":INSTALLED},f)
                        f.flush(); os.fsync(f.fileno())
                    sync_dir(backup_dir)
                    os.chmod(candidate,stat.S_IMODE(source.stat().st_mode))
                    if identity(source)!=before:
                        raise ValueError("source_changed")
                    os.replace(candidate,source)
                    swapped=True
                    sync_dir(source.parent)
                    emit(status="compacted", old_bytes=old_size, compact_bytes=new_size,
                         recovery_archive=dest.name)
            adapter.start_service()
            stopped=False
            adapter.verify_health(INSTALLED)
            healthy=True
            final_free=quota()
            final_required=release_required(source.stat().st_size)
            emit(status="ready_for_release" if final_free>=final_required else "compacted_but_quota_blocked",
                 free_bytes=final_free, required_bytes=final_required, release=RELEASE)
        finally:
            if stopped:
                # On pre-swap failure the original database is intact. On a
                # post-swap failure the verified recovery archive is retained.
                adapter.start_service()
                adapter.verify_health(INSTALLED)
                healthy=True
            if healthy and not os.path.lexists(marker) and not os.path.lexists(gate):
                os.replace(held,gate);sync_dir(BRIDGE)
            else:
                emit(status="manual_recovery_required", gate="held", database_replaced=swapped)

def self_test():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        original=root/"old.db"; candidate=root/"new.db"
        with closing(sqlite3.connect(original)) as c:
            c.execute("create table evidence(id integer primary key,payload blob)")
            c.executemany("insert into evidence values(?,?)",((i,b"x"*8192) for i in range(1,1001)))
            c.execute("delete from evidence where id between 101 and 900")
            c.commit()
        before=identity(original)
        compact(original,candidate)
        assert candidate.stat().st_size<original.stat().st_size
        assert identity(original)==before
        backup=root/"recovery.gz"
        digest=compress_recovery(original,backup,original.stat().st_size)
        assert digest==hashlib.sha256(original.read_bytes()).hexdigest()
        try:
            compress_recovery(original,root/"cap.gz",10)
        except ValueError as e:
            assert str(e)=="backup_output_cap_exceeded"
        else:
            raise AssertionError("cap not enforced")
        with closing(sqlite3.connect(candidate)) as c:
            c.execute("update evidence set payload=? where id=1",(b"wrong",));c.commit()
        try:
            verify_compact(original,candidate)
        except ValueError as e:
            assert str(e)=="logical_content_changed"
        else:
            raise AssertionError("content difference not detected")
        assert identity(original)==before
        emit(status="self_test_pass", checks=4)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test",action="store_true")
    mode.add_argument("--apply-maintenance",action="store_true")
    args=p.parse_args()
    try:
        self_test() if args.self_test else main()
    except Exception as exc:
        reason=str(exc)
        emit(status="blocked",reason=reason if re.fullmatch(r"[a-z_]{1,100}",reason) else type(exc).__name__)
        sys.exit(1)
