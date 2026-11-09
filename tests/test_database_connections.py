"""Exercise actual SQLite locks and commit/rollback with retained handles."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import app


class DatabaseConnections(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = self.temp.name + '/db'
        self.setting = patch.object(app, 'DB', self.db)
        self.setting.start()
        with app.connect() as c:
            c.execute('CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT)')
            c.executemany('INSERT INTO items(value) VALUES(?)', [('a',), ('b',)])

    def tearDown(self):
        self.setting.stop()
        self.temp.cleanup()

    def assert_closed(self, connection):
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_commit_and_close_even_when_connection_is_retained(self):
        with app.connect() as c:
            c.execute("INSERT INTO items(value) VALUES('committed')")
        self.assert_closed(c)
        with app.connect() as other:
            self.assertEqual(other.execute('SELECT count(*) FROM items').fetchone()[0], 3)
            self.assertEqual(other.execute('PRAGMA foreign_keys').fetchone()[0], 1)

    def test_exception_rolls_back_and_closes(self):
        with self.assertRaisesRegex(ValueError, 'abort'):
            with app.connect() as c:
                c.execute("INSERT INTO items(value) VALUES('rolled back')")
                raise ValueError('abort')
        self.assert_closed(c)
        with app.connect() as other:
            self.assertEqual(other.execute('SELECT count(*) FROM items').fetchone()[0], 2)

    def test_unconsumed_read_cursor_releases_lock_at_scope_exit(self):
        # sqlite3's ordinary context manager leaves this cursor's read lock
        # alive while the cursor/connection is referenced after the with block.
        with app.connect() as reader:
            cursor = reader.execute('SELECT * FROM items')
            self.assertIsNotNone(cursor.fetchone())
        with sqlite3.connect(self.db, timeout=0) as writer:
            writer.execute("INSERT INTO items(value) VALUES('writer')")
        self.assert_closed(reader)
        with self.assertRaises(sqlite3.ProgrammingError):
            cursor.fetchone()

    def test_original_context_retains_read_lock_until_cursor_is_closed(self):
        reader = sqlite3.connect(self.db)
        writer = sqlite3.connect(self.db, timeout=0)
        try:
            with reader:
                cursor = reader.execute('SELECT * FROM items')
                cursor.fetchone()
            with self.assertRaises(sqlite3.OperationalError):
                with writer:
                    writer.execute("INSERT INTO items(value) VALUES('blocked')")
            cursor.close()
            with writer:
                writer.execute("INSERT INTO items(value) VALUES('released')")
        finally:
            writer.close()
            reader.close()

    def test_five_concurrent_readers_and_writers_release_their_cursors(self):
        barrier = Barrier(5)
        def scan(index):
            for step in range(10):
                with app.connect() as reader:
                    retained = reader.execute('SELECT * FROM items')
                    retained.fetchone()
                if step == 0:
                    barrier.wait(timeout=10)
                with app.connect() as writer:
                    writer.execute('INSERT INTO items(value) VALUES(?)', (f'{index}:{step}',))
            return True
        with ThreadPoolExecutor(max_workers=5) as pool:
            self.assertEqual(list(pool.map(scan, range(5))), [True] * 5)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM items').fetchone()[0], 52)

    def test_failed_commit_rolls_back_and_closes(self):
        reader = sqlite3.connect(self.db)
        try:
            reader.execute('BEGIN')
            reader.execute('SELECT * FROM items').fetchall()
            with self.assertRaises(sqlite3.OperationalError):
                with app.connect() as writer:
                    writer.execute('PRAGMA busy_timeout=0')
                    writer.execute("INSERT INTO items(value) VALUES('must roll back')")
            self.assert_closed(writer)
        finally:
            reader.close()
        with app.connect() as other:
            self.assertEqual(other.execute('SELECT count(*) FROM items').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
