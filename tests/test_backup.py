import sqlite3
import tempfile
import unittest
from pathlib import Path
from backup_database import snapshot


class BackupTests(unittest.TestCase):
    def test_live_wal_snapshot_and_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src = root / 'source.sqlite3'
            db = sqlite3.connect(src)
            try:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)')
                db.execute("INSERT INTO items VALUES (1, 'committed')")
                db.commit()
                snapshot(src, root / 'backup.sqlite3')
                snapshot(root / 'backup.sqlite3', root / 'restored.sqlite3')
                restored = sqlite3.connect(root / 'restored.sqlite3')
                try:
                    self.assertEqual(restored.execute('SELECT * FROM items').fetchall(), [(1, 'committed')])
                finally:
                    restored.close()
                with self.assertRaises(FileExistsError):
                    snapshot(src, root / 'restored.sqlite3')
                with self.assertRaises(ValueError):
                    snapshot(src, src)
            finally:
                db.close()

    def test_missing_and_corrupt_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                snapshot(root / 'missing', root / 'output')
            self.assertFalse((root / 'output').exists())
            (root / 'bad').write_text('not a sqlite database')
            with self.assertRaises(sqlite3.DatabaseError):
                snapshot(root / 'bad', root / 'output')
            self.assertFalse((root / 'output').exists())
