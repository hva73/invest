import sqlite3,tempfile,unittest
from pathlib import Path
from tools.inspect_live_storage_bounded import inspect

class LiveStorageTests(unittest.TestCase):
    def test_read_only_aggregate_and_freelist(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"escape.db"
            with sqlite3.connect(p) as db:
                db.execute("CREATE TABLE hw_samples (payload TEXT)")
                db.executemany("INSERT INTO hw_samples VALUES (?)",[("sensitive fixture"*500,)]*100)
                db.execute("CREATE INDEX ix ON hw_samples(payload)")
                db.execute("DELETE FROM hw_samples WHERE rowid<=50")
            before=p.read_bytes()
            result=inspect(p)
            self.assertEqual(result["status"],"ok")
            self.assertGreater(result["freelist_bytes"],0)
            self.assertIn("hw_samples",[x["name"] for x in result["objects"]])
            # Verify aggregate-mode page counts and bytes against the old
            # page-by-page query on the disposable fixture only.
            with sqlite3.connect(p.as_uri()+"?mode=ro",uri=True) as db:
                expected={name:(size,pages) for name,size,pages in db.execute(
                    "SELECT name,sum(pgsize),count(*) FROM dbstat GROUP BY name")}
            self.assertEqual({x["name"]:(x["bytes"],x["pages"]) for x in result["objects"]},expected)
            self.assertEqual(sum(x["bytes"] for x in result["objects"])+result["freelist_bytes"],
                             result["page_count"]*result["page_size"])
            self.assertNotIn("sensitive fixture",str(result))
            self.assertEqual(before,p.read_bytes())
            self.assertEqual(list(Path(d).iterdir()),[p])
    def test_index_attribution_and_physical_page_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"escape.db"
            with sqlite3.connect(p) as db:
                db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                db.execute("CREATE TABLE hw_samples(id INTEGER PRIMARY KEY, payload TEXT UNIQUE)")
                db.execute("CREATE INDEX explicit_payload ON hw_samples(payload)")
                db.executemany("INSERT INTO hw_samples(payload) VALUES (?)",
                               [(str(i)+"x"*3000,) for i in range(90)])
                db.execute("DELETE FROM hw_samples WHERE id<40")
            before=p.read_bytes()
            result=inspect(p)
            self.assertEqual(result["status"],"ok")
            by_name={o["name"]:o for o in result["objects"]}
            owners=[o for o in result["objects"] if o["table"]=="hw_samples"]
            indexes=[o for o in owners if o["kind"]=="index"]
            self.assertEqual(len(indexes),2)
            self.assertIn("explicit_payload",by_name)
            with sqlite3.connect(p.as_uri()+"?mode=ro",uri=True) as db:
                physical={name:(payload,unused) for name,payload,unused in db.execute(
                    "SELECT name,sum(payload),sum(unused) FROM dbstat GROUP BY name")}
            self.assertEqual({o["name"]:(o["payload_bytes"],o["unused_bytes"])
                              for o in result["objects"]},physical)
            totals=result["tables"]["hw_samples"]
            self.assertEqual(totals["table_bytes"],by_name["hw_samples"]["bytes"])
            self.assertEqual(totals["index_bytes"],sum(o["bytes"] for o in indexes))
            self.assertEqual(totals["total_bytes"],sum(o["bytes"] for o in owners))
            accounting=result["page_accounting"]
            self.assertEqual(accounting["snapshot_bytes"],len(before))
            self.assertGreater(accounting["unattributed_bytes"],0)
            self.assertGreater(accounting["freelist_bytes"],0)
            self.assertEqual(accounting["snapshot_bytes"],accounting["btree_bytes"]+
                             accounting["freelist_bytes"]+accounting["unattributed_bytes"])
            self.assertEqual(before,p.read_bytes())

    def test_sidecar_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"escape.db"
            with sqlite3.connect(p) as db:db.execute("CREATE TABLE t(x)")
            Path(str(p)+"-wal").touch()
            with self.assertRaisesRegex(ValueError,"sidecar_present"):inspect(p)
            Path(str(p)+"-wal").unlink()
            link=Path(d)/"link";link.symlink_to(p)
            with self.assertRaisesRegex(ValueError,"unsafe_path"):inspect(link)
    def test_invalid_deadline(self):
        with self.assertRaisesRegex(ValueError,"invalid_deadline"):inspect(Path("unused"),16)

    def test_payload_age_buckets_and_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"escape.db"
            now=2000000000
            with sqlite3.connect(p) as db:
                db.execute("CREATE TABLE hw_samples (payload TEXT,event_epoch REAL)")
                db.executemany("INSERT INTO hw_samples VALUES (?,?)",[
                    ("æ",now-1),("abc",now-86400),("old",now-604800),
                    ("very old",now-2592000),(None,None),("future",now+10),
                    ("private", "invalid")])
            before=p.read_bytes()
            result=inspect(p,table="hw_samples",now=now)
            totals=result["table_totals"]
            self.assertEqual(result["status"],"ok")
            self.assertEqual(totals["rows"],7)
            self.assertEqual(totals["payload_bytes"],29)
            self.assertEqual([x["rows"] for x in totals["age_buckets"].values()],[1,1,1,1,3])
            self.assertEqual([x["payload_bytes"] for x in totals["age_buckets"].values()],[2,3,3,8,13])
            self.assertNotIn("private",str(result))
            self.assertEqual(before,p.read_bytes())
    def test_iso_age_and_missing_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"escape.db"
            with sqlite3.connect(p) as db:
                db.execute("CREATE TABLE hw_events(payload TEXT,created TEXT)")
                db.executemany("INSERT INTO hw_events VALUES (?,?)",[
                    ("a","2026-11-24T00:00:00+00:00"),("bb","bad"),("ccc","2026-10-01T00:00:00+00:00")])
            from datetime import datetime,timezone
            now=datetime(2026,11,24,12,tzinfo=timezone.utc).timestamp()
            totals=inspect(p,table="hw_events",now=now)["table_totals"]
            self.assertEqual(totals["age_buckets"]["under_1d"],{"rows":1,"payload_bytes":1})
            self.assertEqual(totals["age_buckets"]["30d_or_older"],{"rows":1,"payload_bytes":3})
            self.assertEqual(totals["age_buckets"]["unknown_or_future"],{"rows":1,"payload_bytes":2})
            self.assertEqual(inspect(p,table="hw_calculations")["status"],"schema_unavailable")
            with self.assertRaisesRegex(ValueError,"unknown_table"):inspect(p,table="hw_events; DROP TABLE hw_events")
    def test_no_timestamp_and_bounded_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"escape.db"
            with sqlite3.connect(p) as db:
                db.execute("CREATE TABLE hw_reference_cache(raw BLOB)")
                db.executemany("INSERT INTO hw_reference_cache VALUES (?)",[(b"abc",)]*10000)
            totals=inspect(p,table="hw_reference_cache")["table_totals"]
            self.assertEqual(totals["age_buckets"]["unknown_or_future"],{"rows":10000,"payload_bytes":30000})
            result=inspect(p,seconds=.000001,table="hw_reference_cache")
            self.assertEqual(result["status"],"partial")
            self.assertNotIn("table_totals",result)

    def test_backup_scope_date_and_age_reference(self):
        from unittest.mock import patch
        from tools import inspect_live_storage_bounded as census
        with tempfile.TemporaryDirectory() as d:
            live=Path(d)/"live.db"
            backup=Path(d)/"backup.db"
            captured=1700000000
            for p in (live,backup):
                with sqlite3.connect(p) as db:
                    db.execute("CREATE TABLE hw_samples(payload TEXT,event_epoch REAL)")
                    db.execute("INSERT INTO hw_samples VALUES (?,?)",("private",captured-60))
            with patch.object(census,"LIVE",live):
                self.assertEqual(inspect(live)["scope"],"live_read_only_aggregate")
                self.assertEqual(inspect(backup)["scope"],"offline_unclassified_read_only_aggregate")
                before=backup.read_bytes()
                result=inspect(backup,table="hw_samples",backup_epoch=captured)
                self.assertEqual(result["scope"],"operator_dated_backup_read_only_aggregate")
                self.assertEqual(result["backup_epoch"],captured)
                self.assertEqual(result["age_reference_epoch"],captured)
                self.assertGreater(result["observed_epoch"],captured)
                self.assertEqual(result["table_totals"]["age_buckets"]["under_1d"]["rows"],1)
                self.assertEqual(backup.read_bytes(),before)
                self.assertNotIn("private",str(result))
                for epoch in (0,float("nan"),float("inf"),-1,99999999999):
                    with self.assertRaisesRegex(ValueError,"invalid_backup_epoch"):
                        inspect(backup,backup_epoch=epoch)
                with self.assertRaisesRegex(ValueError,"backup_age_reference_mismatch"):
                    inspect(backup,backup_epoch=captured,now=captured+1)
                with self.assertRaisesRegex(ValueError,"live_not_backup"):
                    inspect(live,backup_epoch=captured)
                alias=Path(d)/"alias.db"
                alias.hardlink_to(live)
                with self.assertRaisesRegex(ValueError,"live_not_backup"):
                    inspect(alias,backup_epoch=captured)

    def test_offline_compaction_fixture_preserves_evidence(self):
        # Synthetic only: no operator path, no live VACUUM, no retention
        # of trading, learning or journal rows. The source stays byte-identical.
        from contextlib import closing
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"fixture.db"
            candidate=Path(d)/"compacted.db"
            with closing(sqlite3.connect(source)) as db:
                db.execute("PRAGMA foreign_keys=ON")
                db.executescript("""
                    CREATE TABLE hw_samples(id INTEGER PRIMARY KEY,payload BLOB);
                    CREATE TABLE hw_calculations(id INTEGER PRIMARY KEY,
                        sample_id INTEGER REFERENCES hw_samples(id),payload TEXT);
                    CREATE TABLE trade_journal(id INTEGER PRIMARY KEY,payload TEXT);
                    CREATE TABLE scratch(id INTEGER PRIMARY KEY,payload BLOB);
                """)
                db.execute("INSERT INTO hw_samples VALUES(7,?)",(b"sample",))
                db.execute("INSERT INTO hw_calculations VALUES(19,7,'calculation')")
                db.execute("INSERT INTO trade_journal VALUES(33,'trade')")
                db.executemany("INSERT INTO scratch(payload) VALUES(?)",[(b"x"*4000,)]*150)
                db.execute("DELETE FROM scratch")
                db.commit()
            before=source.read_bytes()
            with closing(sqlite3.connect(source.as_uri()+"?mode=ro",uri=True)) as db:
                db.execute("VACUUM INTO ?",(str(candidate),))
            self.assertEqual(source.read_bytes(),before)
            self.assertLess(candidate.stat().st_size,source.stat().st_size)
            with closing(sqlite3.connect(candidate.as_uri()+"?mode=ro",uri=True)) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchall(),[("ok",)])
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
                self.assertEqual(db.execute("SELECT * FROM hw_samples").fetchall(),[(7,b"sample")])
                self.assertEqual(db.execute("SELECT * FROM hw_calculations").fetchall(),[(19,7,"calculation")])
                self.assertEqual(db.execute("SELECT * FROM trade_journal").fetchall(),[(33,"trade")])
                self.assertEqual(db.execute("SELECT count(*) FROM scratch").fetchone(),(0,))

    def test_targeted_physical_census_matches_full_without_other_tables(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"escape.db"
            with sqlite3.connect(p) as db:
                db.execute("CREATE TABLE hw_samples(id INTEGER PRIMARY KEY,payload TEXT UNIQUE)")
                db.execute("CREATE INDEX samples_extra ON hw_samples(payload)")
                db.execute("CREATE TABLE hw_events(id INTEGER PRIMARY KEY,payload TEXT)")
                db.execute("CREATE INDEX event_extra ON hw_events(payload)")
                db.executemany("INSERT INTO hw_samples(payload) VALUES (?)",
                               [(str(i)+"x"*3000,) for i in range(50)])
                db.executemany("INSERT INTO hw_events(payload) VALUES (?)",
                               [("other"*1000,)]*100)
            before=p.read_bytes()
            full=inspect(p)
            selected=inspect(p,physical_table="hw_samples")
            self.assertEqual(selected["status"],"ok")
            self.assertEqual(selected["coverage"],"selected_table_and_indexes_only")
            self.assertNotIn("page_accounting",selected)
            self.assertEqual(selected["objects"],[o for o in full["objects"] if o["table"]=="hw_samples"])
            self.assertEqual(selected["tables"],{"hw_samples":full["tables"]["hw_samples"]})
            self.assertEqual(len(selected["objects"]),3)
            self.assertEqual(selected["freelist_bytes"],full["freelist_bytes"])
            self.assertEqual(inspect(p,physical_table="hw_calculations")["status"],"schema_unavailable")
            with self.assertRaisesRegex(ValueError,"conflicting_scan_modes"):
                inspect(p,table="hw_samples",physical_table="hw_samples")
            with self.assertRaisesRegex(ValueError,"unknown_table"):
                inspect(p,physical_table="hw_samples; DROP TABLE hw_events")
            self.assertEqual(before,p.read_bytes())
            self.assertEqual(list(Path(d).iterdir()),[p])
