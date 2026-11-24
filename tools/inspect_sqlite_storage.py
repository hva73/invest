"""Read aggregate storage statistics from a stable SQLite backup copy only."""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time
from contextlib import closing
from pathlib import Path, PurePosixPath


def inspect_backup(path, now=None):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('backup_not_file')
    if path == Path('/home/nordicr4/escape_app/var/escape.db'):
        raise ValueError('live_database_forbidden')
    if Path(str(path) + '-wal').exists():
        raise ValueError('backup_has_wal_use_consistent_standalone_copy')
    if Path(str(path) + '-journal').exists():
        raise ValueError('backup_has_journal_use_consistent_standalone_copy')
    original=path.stat()
    now = time.time() if now is None else now
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=1)) as db:
        db.execute('PRAGMA query_only=ON')
        value = lambda name: db.execute('PRAGMA ' + name).fetchone()[0]
        data = {'file_bytes':path.stat().st_size,'page_count':value('page_count'),
                'page_size':value('page_size'),'freelist_count':value('freelist_count')}
        try:
            rows=db.execute('SELECT name, sum(pgsize) FROM dbstat GROUP BY name ORDER BY sum(pgsize) DESC').fetchall()
            # Only database object names and aggregate bytes, never row content.
            data['objects']=[{'name':name,'bytes':size} for name,size in rows]
        except sqlite3.OperationalError:
            data['objects']=None
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'jobs' in tables:
            columns={r[1] for r in db.execute('PRAGMA table_info(jobs)')}
            data['completed_jobs_legacy_unknown']=db.execute("SELECT count(*) FROM jobs WHERE status='done'" + (" AND completed IS NULL" if 'completed' in columns else "")).fetchone()[0]
            data['completed_jobs_eligible']={'rows':0,'result_bytes':0}
            if {'completed','kind','lease','lease_until'}.issubset(columns):
                query="""WITH ranked AS (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id DESC) AS position FROM jobs)
                         SELECT count(*),coalesce(sum(length(CAST(coalesce(j.result,'') AS BLOB))),0)
                         FROM jobs j WHERE j.status='done' AND j.completed IS NOT NULL
                         AND j.completed < ? AND j.created < ?
                         AND j.kind IN ('ecb','news','report','pluto_data')
                         AND j.lease IS NULL AND j.lease_until IS NULL
                         AND j.id NOT IN (SELECT id FROM ranked WHERE position<=20)"""
                cutoff=now-30*86400
                count,result_bytes=db.execute(query,(cutoff,cutoff)).fetchone()
                data['completed_jobs_eligible']={'rows':count,'result_bytes':result_bytes}
        data['freelist_bytes']=data['freelist_count']*data['page_size']
        data['unallocated_file_bytes']=data['file_bytes']-data['page_count']*data['page_size']
        after=path.stat()
        if (original.st_dev,original.st_ino,original.st_size,original.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError('backup_changed_during_inspection')
        if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-journal')):
            raise ValueError('backup_journal_created_during_inspection')
        return data


def inspect_archive_database(archive_path, backup_name, expected_sha256, expected_bytes, now=None):
    """Inspect only the verified DB member of a locally held private backup archive.

    The caller supplies the SHA256 and size from the independently retrieved
    manifest/inventory. Never trust a hash supplied solely by the archive.
    This creates no server files and never extracts archive paths.
    """
    if not isinstance(backup_name,str) or not re.fullmatch(r'\d{8}-\d{6}-[A-Za-z0-9_-]+',backup_name):
        raise ValueError('invalid_backup_name')
    if not isinstance(expected_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_sha256):
        raise ValueError('invalid_database_sha256')
    if type(expected_bytes) is not int or not 512 < expected_bytes <= 10000000000:
        raise ValueError('invalid_database_size')
    archive_path=Path(archive_path).resolve(strict=True)
    if not archive_path.is_file():
        raise ValueError('archive_not_file')
    with tempfile.TemporaryDirectory(prefix='escape-private-dbstat-') as directory:
        # This is runner capacity, not the production quota.
        if shutil.disk_usage(directory).free < expected_bytes + 256*1024*1024:
            raise ValueError('insufficient_local_inspection_space')
        target=Path(directory)/'copy.sqlite'
        found=False
        with tarfile.open(archive_path,'r|gz') as archive:
            for member in archive:
                path=PurePosixPath(member.name)
                if '..' in path.parts or member.issym() or member.islnk():
                    raise ValueError('unsafe_archive_member')
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError('unsafe_archive_member')
                if path.parts.count(backup_name)!=1:
                    raise ValueError('unexpected_archive_member')
                relative=path.parts[path.parts.index(backup_name)+1:]
                if relative!=('escape.db',):
                    continue
                if found or member.size!=expected_bytes:
                    raise ValueError('database_member_mismatch')
                digest=hashlib.sha256()
                count=0
                with archive.extractfile(member) as source, target.open('xb') as output:
                    while block:=source.read(1024*1024):
                        count+=len(block)
                        if count>expected_bytes:
                            raise ValueError('database_member_mismatch')
                        digest.update(block)
                        output.write(block)
                if count!=expected_bytes or digest.hexdigest()!=expected_sha256:
                    raise ValueError('database_hash_mismatch')
                found=True
        if not found:
            raise ValueError('database_member_missing')
        report=inspect_backup(target,now)
        report['source']='verified_archive_database_member'
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup_copy',help='consistent, standalone backup copy; never the live database')
    parser.add_argument('--confirm-backup-copy',action='store_true',required=True)
    args=parser.parse_args()
    print(json.dumps(inspect_backup(args.backup_copy),sort_keys=True))


if __name__=='__main__':
    main()
