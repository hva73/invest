"""Read aggregate storage statistics from a stable SQLite backup copy only."""
import argparse
import json
import sqlite3
import time
from pathlib import Path


def inspect_backup(path, now=None):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('backup_not_file')
    if Path(str(path) + '-wal').exists():
        raise ValueError('backup_has_wal_use_consistent_standalone_copy')
    now = time.time() if now is None else now
    with sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=1) as db:
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
            query="""WITH ranked AS (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id DESC) AS position FROM jobs)
                     SELECT count(*),coalesce(sum(length(CAST(coalesce(j.result,'') AS BLOB))),0)
                     FROM jobs j WHERE j.status='done' AND j.created<?
                     AND j.id NOT IN (SELECT id FROM ranked WHERE position<=20)"""
            count,result_bytes=db.execute(query,(now-30*86400,)).fetchone()
            data['completed_jobs_eligible']={'rows':count,'result_bytes':result_bytes}
        return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup_copy',help='consistent, standalone backup copy; never the live database')
    parser.add_argument('--confirm-backup-copy',action='store_true',required=True)
    args=parser.parse_args()
    print(json.dumps(inspect_backup(args.backup_copy),sort_keys=True))


if __name__=='__main__':
    main()
