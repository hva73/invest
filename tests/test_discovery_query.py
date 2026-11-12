"""Discovery query semantics and bounded work with accumulated report history."""
import json
import random
import sqlite3
import tempfile
import unittest
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import app
import hotwatch_service as service
import hotwatch_engine as engine

OLD_QUERY = "SELECT l.candidate_id,l.generated,r.id,r.received,r.payload FROM report_candidate_links l JOIN ingested_reports r ON r.id=l.report_row_id WHERE l.user_id=? AND l.is_test=0 AND r.report_type!='deep_analysis' AND l.generated<=? AND NOT EXISTS (SELECT 1 FROM report_candidate_links newer JOIN ingested_reports nr ON nr.id=newer.report_row_id WHERE newer.user_id=l.user_id AND newer.is_test=0 AND newer.candidate_id=l.candidate_id AND nr.report_type!='deep_analysis' AND newer.generated<=? AND (newer.generated>l.generated OR (newer.generated=l.generated AND nr.id>r.id))) ORDER BY l.generated DESC,r.id DESC,(SELECT CAST(j.key AS INTEGER) FROM json_each(r.payload,'$.candidates') j WHERE json_extract(j.value,'$.candidate_id')=l.candidate_id LIMIT 1)"

class DiscoveryQuery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.setting=patch.object(app,'DB',str(Path(self.temp.name)/'db'))
        self.setting.start();app.init();app.create_user('test-password-long-enough')
        with app.connect() as c:
            c.execute("INSERT INTO users(id,username,active) VALUES(2,'other',1)")
        self.sequence=0

    def tearDown(self):
        self.setting.stop();self.temp.cleanup()

    def insert(self,c,candidates,generated,user=1,mode=0,kind='hourly',padding=0):
        self.sequence+=1
        payload=json.dumps({'report_id':'synthetic-'+str(self.sequence),'candidates':[{'candidate_id':cid,'body':'x'*padding} for cid in candidates]})
        row=c.execute('INSERT INTO ingested_reports(user_id,report_id,received,payload,digest,is_test,generated_epoch,report_type) VALUES(?,?,?,?,?,?,?,?)',
                      (user,'synthetic-'+str(self.sequence),'2026-11-09T14:00:00Z',payload,str(self.sequence),mode,generated,kind)).lastrowid
        c.executemany('INSERT INTO report_candidate_links VALUES(?,?,?,?,?)',[(user,mode,cid,row,generated) for cid in candidates])
        return row

    def rows(self,c,user,now):
        rows=c.execute(service.DISCOVERY_CANDIDATES_SQL,(user,user,now)).fetchall()
        return [tuple(r) for r in service.discovery_candidate_order(rows)]

    def test_latest_assessment_ties_future_deep_analysis_owner_and_order(self):
        with app.connect() as c:
            self.insert(c,['A','B'],10)
            latest=self.insert(c,['B','A'],20)
            self.insert(c,['A','DEEP_ONLY'],30,kind='deep_analysis')
            self.insert(c,['A','FUTURE_ONLY'],101)
            self.insert(c,['A','TEST_ONLY'],40,mode=1)
            self.insert(c,['A','OTHER_ONLY'],40,user=2)
            tie=self.insert(c,['C'],20)
            rows=self.rows(c,1,100)
            self.assertEqual([(r[0],r[2]) for r in rows],[('C',tie),('B',latest),('A',latest)])
            self.assertEqual(rows,[tuple(r) for r in c.execute(OLD_QUERY,(1,100,100))])
            self.assertEqual(self.rows(c,1,0),[])

    def test_equivalent_to_previous_selection_across_mixed_history(self):
        rng=random.Random(7321)
        with app.connect() as c:
            for _ in range(90):
                self.insert(c,rng.sample(['A','B','C','D','E','F'],rng.randint(1,6)),rng.randint(0,50),
                            user=rng.choice([1,1,2]),mode=rng.choice([0,0,1]),kind=rng.choice(['hourly','legacy','deep_analysis']))
            for user in (1,2):
                for now in (0,10,25,50):
                    self.assertEqual(self.rows(c,user,now),[tuple(r) for r in c.execute(OLD_QUERY,(user,now,now))])

    def test_large_history_does_not_repeat_a_history_scan_for_each_old_link(self):
        with app.connect() as c:
            candidates=['C'+str(i) for i in range(50)]
            for i in range(150):latest=self.insert(c,candidates,i,padding=3500)
        with app.connect() as c:
            # Count SQLite VM work instead of making a flaky wall-clock claim.
            # The old query needs ~10 million steps on this synthetic history.
            count=[0]
            def limit_work():
                count[0]+=1000
                return int(count[0]>400000)
            c.set_progress_handler(limit_work,1000)
            try:
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    list(c.execute(OLD_QUERY,(1,200,200)))
                self.assertEqual(caught.exception.sqlite_errorcode,sqlite3.SQLITE_INTERRUPT)
                count[0]=0
                rows=self.rows(c,1,200)
                self.assertLess(count[0],400000)
                self.assertEqual([(r[0],r[2]) for r in rows],[(cid,latest) for cid in candidates])
            finally:c.set_progress_handler(None,0)

    def test_discovery_with_large_history_does_not_block_heartbeat_and_status(self):
        with app.connect() as c:
            for i in range(150):self.insert(c,['C'+str(j) for j in range(50)],i,padding=3500)
        def bounded_connection():
            c=app.connect();steps=[0]
            def budget():
                steps[0]+=1000
                return int(steps[0]>400000)
            c.set_progress_handler(budget,1000)
            return c
        runner=service.Runner(bounded_connection)
        gate=threading.Barrier(3)
        def discover():
            gate.wait(timeout=3);cursor=0
            for _ in range(5):cursor=service.auto_discover(runner.connect,cursor)
        def beat():
            gate.wait(timeout=3)
            for _ in range(25):runner.heartbeat('running')
        def status():
            gate.wait(timeout=3)
            for _ in range(20):engine.sync(app.connect,1,False,session_limit=1)
        with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':'2026-11-09T00:00:00Z'}),patch.object(service,'auto_activate_candidate',return_value={'status':'ALREADY_ACTIVE'}) as activate:
            with ThreadPoolExecutor(max_workers=3) as pool:
                tasks=[pool.submit(fn) for fn in (discover,beat,status)]
                for task in tasks:task.result(timeout=10)
            self.assertEqual(activate.call_count,5)
            self.assertEqual(len({call.args[4]['candidate_id'] for call in activate.call_args_list}),5)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM hw_heartbeat WHERE id=1').fetchone()[0],'running')
            self.assertEqual(c.execute('SELECT count(*) FROM broker_proposals').fetchone()[0],0)

    def test_discovery_reuses_report_parsed_before_serialized_scope(self):
        with app.connect() as c:
            report_id=self.insert(c,['A','B','C'],10,padding=3500)
            payload=c.execute('SELECT payload FROM ingested_reports WHERE id=?',(report_id,)).fetchone()[0]
        runner=service.Runner(app.connect)
        loads=json.loads
        with patch.dict(os.environ,{'ESCAPE_HW_AUTOSTART_ENABLED':'1','ESCAPE_HW_AUTOSTART_AFTER':'2026-11-09T00:00:00Z'}), \
             patch.object(service.json,'loads',wraps=loads) as decode, \
             patch.object(service,'auto_activate_candidate',return_value={'status':'ALREADY_ACTIVE'}) as activate:
            service.auto_discover(runner.connect,0)
        self.assertEqual(sum(call.args[0]==payload for call in decode.call_args_list),1)
        self.assertEqual(activate.call_args.args[4]['candidate_id'],'A')

if __name__=='__main__':unittest.main()
