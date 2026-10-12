import sqlite3
import tempfile
import unittest
from pathlib import Path
from maintain_storage import compact, backup_files, delete_backups, offline, old_calls, delete_calls


class StorageTests(unittest.TestCase):
    def test_call_cleanup_retains_recent_pending_and_changed(self):
        from datetime import datetime,timedelta,timezone
        path=self.root/'calls.sqlite3'
        old=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat()
        recent=datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE model_calls(id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, day TEXT, status TEXT)')
            db.executemany('INSERT INTO model_calls VALUES (?,?,?,?,?)', [('old',old,old,old[:10],'answered'),('pending',old,None,old[:10],'pending'),('recent',recent,recent,recent[:10],'answered')])
        db.close()
        rows=old_calls(path); self.assertEqual([r['id'] for r in rows],['old'])
        with sqlite3.connect(path) as db: db.execute("UPDATE model_calls SET status='unavailable' WHERE id='old'")
        db.close()
        with self.assertRaises(ValueError): delete_calls(path,rows)
        self.assertEqual(delete_calls(path,old_calls(path)),1)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('SELECT id FROM model_calls ORDER BY id').fetchall(),[('pending',),('recent',)])
        db.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_delete_reopen_compact_preserves_remaining_data(self):
        path = self.root/'test.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE records(id INTEGER PRIMARY KEY, body BLOB)')
            db.executemany('INSERT INTO records VALUES (?,?)', [(i, b'x'*10000) for i in range(200)])
            db.execute('DELETE FROM records WHERE id>0')
        db.close()
        before, after, released = compact(path)
        self.assertGreater(released, 0)
        self.assertEqual(before-after, released)
        with sqlite3.connect(path) as reopened:
            self.assertEqual(reopened.execute('SELECT id,length(body) FROM records').fetchall(), [(0,10000)])
        reopened.close()

    def test_exact_backup_selection_and_changed_file_rejected(self):
        folder = self.root/'instance'/'restore-checks'/'example'
        folder.mkdir(parents=True)
        a, b = folder/'backup.sqlite3', folder/'restored.sqlite3'
        a.write_bytes(b'old'); b.write_bytes(b'keep')
        original = self.root/'instance'/'aftercare.sqlite3'
        original.write_bytes(b'original')
        rows = backup_files(self.root)
        a.write_bytes(b'changed')
        with self.assertRaises(ValueError): delete_backups(self.root, rows)
        self.assertTrue(b.exists())
        row = [r for r in backup_files(self.root) if r[0] == a]
        self.assertEqual(delete_backups(self.root, row), 7)
        self.assertFalse(a.exists())
        self.assertEqual(b.read_bytes(), b'keep')
        self.assertEqual(original.read_bytes(), b'original')
        with self.assertRaises(ValueError): delete_backups(self.root, [(original,8,'fake')])

    def test_busy_database_is_not_compacted(self):
        path = self.root/'busy.sqlite3'
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        db.execute('CREATE TABLE x(id INTEGER)')
        db.execute('BEGIN EXCLUSIVE')
        with self.assertRaises(sqlite3.OperationalError): compact(path)
        db.rollback()

    def test_offline_guard_rejects_second_service(self):
        import socket
        # A currently running project also makes this guard reject maintenance.
        try:
            with offline():
                with socket.socket() as other:
                    with self.assertRaises(OSError): other.bind(('127.0.0.1',5005))
        except OSError:
            pass
