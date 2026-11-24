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
