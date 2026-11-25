"""Bounded offline SQLite proof for issue #14, using only synthetic evidence.

Run with python -m unittest discover -s tests -p test_storage_reclaim_proof.py.
Footprint measurements cover named files at phase boundaries. They neither
capture SQLite transient files nor predict production disk requirements.
"""

from contextlib import closing
import hashlib
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_only(path):
    return closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True))


def verify_database(path, expected_checksum):
    if checksum(path) != expected_checksum:
        raise ValueError("snapshot checksum mismatch")
    with read_only(path) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("SQLite foreign key check failed")


def restore(snapshot, expected_checksum, target):
    verify_database(snapshot, expected_checksum)
    staged = target.with_suffix(".staged")
    shutil.copyfile(snapshot, staged)
    verify_database(staged, expected_checksum)
    footprint = sum(path.stat().st_size for path in target.parent.iterdir())
    staged.replace(target)
    return footprint


def storage(path):
    with read_only(path) as db:
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        free_pages = db.execute("PRAGMA freelist_count").fetchone()[0]
    return path.stat().st_size, page_size * free_pages


def evidence(path):
    with read_only(path) as db:
        rows = db.execute("""
            SELECT evidence.kind, evidence.id, evidence.payload,
                   samples.id, hex(samples.payload)
            FROM evidence JOIN samples ON samples.id = evidence.sample_id
            ORDER BY evidence.id
        """).fetchall()
    return len(rows), hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def reclaim(snapshot, expected_checksum, working, compact, available_bytes):
    # Fixture budget for the working copy, compact output and staged restore.
    # This deliberately does not model SQLite scratch or a production quota.
    if available_bytes < 3 * snapshot.stat().st_size:
        raise ValueError("insufficient synthetic scratch space")
    restore(snapshot, expected_checksum, working)
    before = storage(working)
    with closing(sqlite3.connect(working)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        with db:
            db.execute("""
                DELETE FROM samples
                WHERE NOT EXISTS (
                    SELECT 1 FROM evidence WHERE evidence.sample_id = samples.id
                )
            """)
        after_delete = storage(working)
        db.execute("VACUUM INTO ?", (str(compact),))
    return before, after_delete, storage(compact)


class StorageReclaimProof(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source.sqlite"
        self.snapshot = self.root / "snapshot.sqlite"
        self.working = self.root / "working.sqlite"
        self.compact = self.root / "compact.sqlite"
        self.target = self.root / "restored.sqlite"

        with closing(sqlite3.connect(self.source)) as db:
            db.executescript("""
                PRAGMA page_size = 4096;
                PRAGMA auto_vacuum = NONE;
                PRAGMA journal_mode = DELETE;
                PRAGMA foreign_keys = ON;
                CREATE TABLE samples (id INTEGER PRIMARY KEY, payload BLOB NOT NULL);
                CREATE TABLE evidence (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    sample_id INTEGER NOT NULL REFERENCES samples(id),
                    payload TEXT NOT NULL
                );
            """)
            with db:
                db.executemany(
                    "INSERT INTO samples VALUES (?, zeroblob(3072))",
                    ((sample_id,) for sample_id in range(1, 257)),
                )
                db.executemany(
                    "INSERT INTO evidence VALUES (?, ?, ?, ?)",
                    [(1, "trade", 5, "fill"), (2, "signal", 128, "decision"),
                     (3, "lab", 250, "simulation")],
                )
        # All handles are closed and the fixture uses rollback journaling.
        self.source_checksum = checksum(self.source)
        restore(self.source, self.source_checksum, self.snapshot)
        self.required_bytes = 3 * self.snapshot.stat().st_size

    def test_offline_compaction_and_restore(self):
        before, after_delete, after_compact = reclaim(
            self.snapshot, self.source_checksum, self.working, self.compact,
            min(shutil.disk_usage(self.root).free, self.required_bytes),
        )
        self.assertEqual(before[1], 0)
        self.assertEqual(before[0], after_delete[0])
        self.assertGreater(after_delete[1], before[1])
        self.assertLess(after_compact[0], after_delete[0])
        self.assertEqual(after_compact[1], 0)

        compact_checksum = checksum(self.compact)
        install_bytes = restore(self.compact, compact_checksum, self.target)
        expected_evidence = evidence(self.source)
        self.assertEqual(expected_evidence[0], 3)
        for path in (self.working, self.compact, self.target):
            self.assertEqual(evidence(path), expected_evidence)
            with read_only(path) as db:
                self.assertEqual(db.execute(
                    "SELECT id FROM samples ORDER BY id"
                ).fetchall(), [(5,), (128,), (250,)])
        self.assertEqual(checksum(self.target), compact_checksum)

        rollback_bytes = restore(self.snapshot, self.source_checksum, self.target)
        peak_bytes = max(install_bytes, rollback_bytes)
        self.assertEqual(checksum(self.target), self.source_checksum)
        self.assertEqual(storage(self.target), before)
        verify_database(self.source, self.source_checksum)
        verify_database(self.snapshot, self.source_checksum)
        print(
            f"Synthetic SQLite bytes (file, freelist): before={before}, "
            f"DELETE={after_delete}, compact={after_compact}. "
            f"Peak named files at measured checkpoints={peak_bytes} bytes "
            "(no production estimate)."
        )

    def test_reclaim_rejects_insufficient_scratch_and_corrupt_snapshot(self):
        with self.assertRaisesRegex(ValueError, "insufficient synthetic scratch space"):
            reclaim(self.snapshot, self.source_checksum, self.working,
                    self.compact, self.required_bytes - 1)
        self.assertFalse(self.working.exists())
        self.assertFalse(self.compact.exists())
        verify_database(self.snapshot, self.source_checksum)

        with self.snapshot.open("r+b") as handle:
            handle.write(b"invalid header")
        with self.assertRaisesRegex(ValueError, "snapshot checksum mismatch"):
            reclaim(self.snapshot, self.source_checksum, self.working,
                    self.compact, self.required_bytes)
        self.assertFalse(self.working.exists())
        self.assertFalse(self.compact.exists())
        verify_database(self.source, self.source_checksum)

    def test_restore_rejects_invalid_snapshot_even_with_matching_checksum(self):
        restore(self.source, self.source_checksum, self.target)
        with closing(sqlite3.connect(self.snapshot)) as db:
            db.execute("PRAGMA foreign_keys = OFF")
            with db:
                db.execute("DELETE FROM samples WHERE id = 5")
        with self.assertRaisesRegex(ValueError, "SQLite foreign key check failed"):
            restore(self.snapshot, checksum(self.snapshot), self.target)
        self.assertEqual(checksum(self.target), self.source_checksum)

        self.snapshot.write_bytes(b"invalid SQLite file")
        with self.assertRaises(sqlite3.DatabaseError):
            restore(self.snapshot, checksum(self.snapshot), self.target)
        self.assertEqual(checksum(self.target), self.source_checksum)
        self.assertFalse(self.target.with_suffix(".staged").exists())
