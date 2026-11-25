"""Offline-only rollback proof. All databases are disposable synthetic fixtures.

Not a migration CLI: do not import this test as a production restore tool.
"""
import copy
import hashlib
import json
import os
import sqlite3
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import app
import hotwatch_engine as engine
import strategy_lab
from test_hotwatch_engine import HotWatch
from test_hotwatch_bar_evidence import BarEvidenceTests


class StorageRollbackQA(unittest.TestCase):
    def setUp(self):
        self.fixture = HotWatch()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.feed = BarEvidenceTests()
        self.feed.setUp()

    def populate(self, unique=False, count=120, suffix='rollback'):
        req = copy.deepcopy(self.fixture.req)
        req.update(watch_id=suffix, purpose='synthetic '+suffix,
                   provider='eodhd', provider_symbol='MERC.US')
        base = self.feed.now
        engine.create(app.connect, 1, req, base)
        samples, results = [], []
        for i in range(count):
            event = base + timedelta(seconds=i)
            at = event + timedelta(seconds=1)
            sample = copy.deepcopy(self.feed.sample)
            sample.update(sample_id=suffix+'-'+str(i), event_time=event.isoformat(),
                          bid_at=at.isoformat(), ask_at=at.isoformat(), status_at=at.isoformat())
            sample['context']['as_of'] = at.isoformat()
            sample['bar_evidence']['schedule_received_at'] = at.isoformat()
            if unique:
                sample['bar_history'][-1]['volume'] = str(1000+i)
            samples.append(sample)
            results.append(engine.ingest(app.connect, 1, req['watch_id'], True,
                                         sample, at, include_session=False)['calculation'])
        later = at + timedelta(seconds=120)
        renewed = copy.deepcopy(sample)
        renewed['context']['as_of'] = later.isoformat()
        results.append(engine.ingest(app.connect, 1, req['watch_id'], True,
                                     renewed, later, include_session=False)['calculation'])
        return req, samples, results

    @staticmethod
    def snapshot(c):
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        # Compare row values and identities, including unrelated journal/business data.
        return {n: sorted([tuple(r) for r in c.execute('SELECT * FROM "'+n.replace('"','""')+'"')], key=repr)
                for n in names}

    @staticmethod
    def inline_copy(c):
        # A transaction on a disposable copy only. Retain dictionary evidence.
        with c:
            for row in c.execute('SELECT * FROM hw_samples ORDER BY id').fetchall():
                sample = engine.sample_read(c, row['watch_row_id'], row['payload'])
                if engine.checksum(sample) != row['digest']:
                    raise ValueError('original sample checksum mismatch')
                c.execute('UPDATE hw_samples SET payload=? WHERE id=?',
                          (engine.canonical(sample), row['id']))
            for row in c.execute('SELECT * FROM hw_calculations ORDER BY id').fetchall():
                calc = engine.calculation_read(row['payload'])
                c.execute('UPDATE hw_calculations SET payload=? WHERE id=?',
                          (engine.canonical(calc), row['id']))

    def test_legacy_reader_negative_and_isolated_inline_restore(self):
        with patch.dict(os.environ, {'ESCAPE_HW_DEDUPE_BAR_HISTORY':'1',
                                     'ESCAPE_HW_COMPACT_RENEWAL_AUDIT':'1'}):
            req, samples, results = self.populate()
        choices = {'watch_id':req['watch_id'], 'is_test':True,
                   'strategies':[{'strategy_id':req['strategy_id'],'version':req['strategy_version']}]}
        source = Path(app.DB)
        clone = source.with_name('isolated-rollback.db')
        with patch.dict(os.environ, {'ESCAPE_HW_DEDUPE_BAR_HISTORY':'0',
                                     'ESCAPE_HW_COMPACT_RENEWAL_AUDIT':'0'}):
            replay = strategy_lab.compare(app.connect,1,choices)
            self.assertEqual((replay['evaluated'], replay['skipped']), (121,0))
            with app.connect() as c:
                before = self.snapshot(c)
                sr = c.execute('SELECT * FROM hw_samples ORDER BY id').fetchall()
                cr = c.execute('SELECT * FROM hw_calculations ORDER BY id').fetchall()
                # Frozen code uses json.loads, without hydration. OFF is not rollback.
                self.assertNotIn('bar_history', json.loads(sr[0]['payload']))
                self.assertNotEqual(engine.checksum(json.loads(sr[0]['payload'])), sr[0]['digest'])
                self.assertIn(engine._RENEWAL_AUDIT_KEY, json.loads(cr[-1]['payload']))
                self.assertNotEqual(json.loads(cr[-1]['payload']), results[-1])
                dest = sqlite3.connect(clone)
                try:
                    c.backup(dest)
                finally:
                    dest.close()
            original_bytes = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch.object(app,'DB',str(clone)):
                with app.connect() as c:
                    self.assertEqual(self.snapshot(c), before)
                    # Wrong reference on last row: reject and roll back all preceding updates.
                    c.execute('UPDATE hw_samples SET digest=? WHERE id=?', ('0'*64, sr[-1]['id']))
                with app.connect() as c:
                    corrupt = self.snapshot(c)
                    with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                        self.inline_copy(c)
                    self.assertEqual(self.snapshot(c),corrupt)
                    c.execute('UPDATE hw_samples SET digest=? WHERE id=?',(sr[-1]['digest'],sr[-1]['id']))
                with app.connect() as c:
                    self.inline_copy(c)
                    restored = self.snapshot(c)
                    for table in before:
                        if table not in ('hw_samples','hw_calculations'):
                            self.assertEqual(before[table], restored[table], table)
                    after_s = c.execute('SELECT * FROM hw_samples ORDER BY id').fetchall()
                    after_c = c.execute('SELECT * FROM hw_calculations ORDER BY id').fetchall()
                    for old,new in list(zip(sr,after_s))+list(zip(cr,after_c)):
                        self.assertEqual({k:old[k] for k in old.keys() if k!='payload'},
                                         {k:new[k] for k in new.keys() if k!='payload'})
                    self.assertEqual([json.loads(r['payload']) for r in after_s],samples)
                    self.assertEqual([engine.checksum(json.loads(r['payload'])) for r in after_s],
                                     [r['digest'] for r in sr])
                    self.assertEqual([json.loads(r['payload']) for r in after_c],results)
                    self.assertEqual([engine.checksum(json.loads(r['payload'])) for r in after_c],
                                     [engine.checksum(r) for r in results])
                    self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                    self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
                self.assertEqual(strategy_lab.compare(app.connect,1,choices),replay)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original_bytes)
            with app.connect() as c:
                self.assertEqual(self.snapshot(c),before)
            print('HW_ROLLBACK_QA legacy_negative=PASS restore=PASS samples=120 calculations=121 all_other_tables_equal=1 source_unchanged=1')

    def test_unique_vs_repeated_bar_dictionary_cost(self):
        for unique in (False,True):
            with self.subTest(unique=unique), patch.dict(os.environ, {
                    'ESCAPE_HW_DEDUPE_BAR_HISTORY':'1','ESCAPE_HW_COMPACT_RENEWAL_AUDIT':'0'}):
                req,samples,_ = self.populate(unique=unique,count=40,suffix='cost-'+str(unique))
                with app.connect() as c:
                    row = engine.row_for(c,1,req['watch_id'],True)
                    stored = c.execute('SELECT payload,digest FROM hw_samples WHERE watch_row_id=? ORDER BY id',(row['id'],)).fetchall()
                    blocks = c.execute('SELECT payload,digest FROM hw_bar_history_payloads WHERE watch_row_id=?',(row['id'],)).fetchall()
                    self.assertEqual(len(stored),40)
                    self.assertEqual(len(blocks),40 if unique else 1)
                    self.assertEqual([engine.sample_read(c,row['id'],r['payload']) for r in stored],samples)
                    before=sum(len(engine.canonical(s).encode()) for s in samples)
                    # Include dictionary digest key, not SQLite page/index overhead.
                    after=sum(len(r['payload'].encode()) for r in stored)+sum(len(r['payload'].encode())+len(r['digest'].encode()) for r in blocks)
                    first_block=next(r for r in blocks if r['digest']==engine.checksum(samples[0]['bar_history']))
                    first_cost=len(stored[0]['payload'].encode())+len(first_block['payload'].encode())+len(first_block['digest'].encode())-len(engine.canonical(samples[0]).encode())
                    self.assertGreater(first_cost,0)
                    if unique:self.assertGreater(after,before)
                    else:self.assertLess(after,before)
                    print('HW_CARDINALITY unique=%s samples=40 blocks=%d before=%d after=%d first_occurrence_overhead=%d'%(unique,len(blocks),before,after,first_cost))


if __name__=='__main__':
    unittest.main()
