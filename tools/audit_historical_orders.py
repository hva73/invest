"""Read-only, bounded inspection of known order IDs in ESCAPE's local journal.

This does not access a broker, modify the application or infer an execution
time. Reports are claims; status_time is a provider status timestamp, not
necessarily a fill timestamp. Run only with the owner's authorization.
"""
import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote


ORDER_ID = re.compile(r'^[0-9a-fA-F-]{36}$')


def _object(value):
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def _explicit_order_items(value, order_ids, depth=0):
    if depth > 8:
        return
    if isinstance(value, dict):
        identity = value.get('orderId')
        if isinstance(identity, str) and identity in order_ids:
            fields = ('orderId', 'source', 'origin', 'filledAt', 'executedAt', 'statusChangedAt', 'updatedAt')
            yield {k: v for k in fields if isinstance((v := value.get(k)), str) and len(v) <= 120}
        for child in value.values():
            yield from _explicit_order_items(child, order_ids, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _explicit_order_items(child, order_ids, depth + 1)


def inspect(connection, order_ids, report_limit=500):
    if (not order_ids or len(order_ids) > 10
            or any(not isinstance(x, str) or not ORDER_ID.fullmatch(x) for x in order_ids)):
        raise ValueError('Expected one to ten exact broker order IDs')
    if not 1 <= report_limit <= 500:
        raise ValueError('Invalid report limit')
    results = {identity: {'execution_observations': [], 'report_observations': [], 'proposal_references': []} for identity in order_ids}
    placeholders = ','.join('?' for _ in order_ids)
    query = ('SELECT order_id,status,occurred_at,verification,payload FROM candidate_execution_events '
             'WHERE is_test=0 AND order_id IN (' + placeholders + ') ORDER BY id DESC LIMIT 100')
    for order_id, status, observed, verification, payload in connection.execute(query, order_ids):
        data = _object(payload)
        results[order_id]['execution_observations'].append({
            'status': status, 'observed_at': observed, 'verification': verification,
            'provider_status_time': data.get('status_time'),
            'filled_quantity': data.get('filled_quantity'),
        })
    query = ('SELECT report_id,received,payload FROM ingested_reports WHERE is_test=0 '
             'ORDER BY id DESC LIMIT ?')
    scanned = 0
    for report_id, received, payload in connection.execute(query, (report_limit,)):
        scanned += 1
        orders = _object(payload).get('orders') or []
        if not isinstance(orders, list):
            continue
        for item in orders:
            if not isinstance(item, dict) or item.get('order_id') not in results:
                continue
            results[item['order_id']]['report_observations'].append({
                'report_id': report_id, 'received_at': received,
                'reported_created_at': item.get('created_at'),
                'reported_status_changed_at': item.get('status_changed_at'),
                'reported_as_of': item.get('as_of'),
                'reported_execution_source': item.get('execution_source'),
                'reported_lifecycle': item.get('lifecycle'),
            })
    proposals_scanned = 0
    for status, created, response in connection.execute('SELECT status,created,response FROM broker_proposals ORDER BY id DESC LIMIT 500'):
        proposals_scanned += 1
        for item in _explicit_order_items(_object(response), results):
            identity = item.pop('orderId')
            results[identity]['proposal_references'].append({'proposal_status': status, 'proposal_created_epoch': created,
                                                               'provider_order_fields': item})
    return {'orders': results, 'reports_scanned': scanned, 'report_scan_limit': report_limit,
            'proposals_scanned': proposals_scanned, 'proposal_scan_limit': 500,
            'coverage': 'bounded_not_complete',
            'note': 'Report timestamps are reported claims; provider status time and observation time are not necessarily execution time.'}


def open_database(path):
    path = Path(path)
    # Follow the existing Nordicway read-only diagnostic policy: refuse WAL,
    # journals and unsafe links instead of creating SQLite sidecar files.
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        raise ValueError('Database missing or unsafe')
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise ValueError('Database has a journal; use an independently verified read-only snapshot')
    with path.open('rb') as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01':
        raise ValueError('Unsupported database journal mode')
    connection = sqlite3.connect('file:' + quote(str(path.resolve()), safe='/') + '?mode=ro', uri=True, timeout=1)
    connection.execute('PRAGMA query_only=ON')
    deadline = time.monotonic() + 3
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return connection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('order_ids', nargs='+')
    args = parser.parse_args()
    connection = open_database(args.database)
    try:
        print(json.dumps(inspect(connection, args.order_ids), ensure_ascii=False, indent=2))
    finally:
        connection.close()


if __name__ == '__main__':
    main()
