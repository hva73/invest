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
