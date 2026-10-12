import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from werkzeug.security import check_password_hash
from aftercare_app.db import connect_database, initialize_database, transaction
from aftercare_app.seed import seed_demo


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        initialize_database(self.path)
        self.db = connect_database(self.path)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.db.close)
        seed_demo(self.db, 'local-test-password', datetime(2026,9,17,tzinfo=timezone.utc))

    def test_seed_repeat_preserves_records_and_password(self):
        before = [tuple(r) for r in self.db.execute('SELECT * FROM users')]
        initialize_database(self.path)
        seed_demo(self.db, 'different-test-password')
        self.assertEqual(before, [tuple(r) for r in self.db.execute('SELECT * FROM users')])
        self.assertEqual([self.db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ['users','orders','tickets','ticket_events']], [4,3,1,1])
        self.assertTrue(check_password_hash(before[0][2], 'local-test-password'))

    def test_foreign_keys_enabled_each_connection_and_persistence(self):
        other = connect_database(self.path)
        try:
            self.assertEqual(other.execute('PRAGMA foreign_keys').fetchone()[0],1)
            self.assertEqual(other.execute('SELECT count(*) FROM tickets').fetchone()[0],1)
        finally:
            other.close()

    def test_wrong_order_owner_rejected(self):
        ticket = self.db.execute('SELECT * FROM tickets').fetchone()
        other = self.db.execute("SELECT id FROM users WHERE username='demo_customer_b'").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO tickets(order_id,requester_id,category,description,created_at,request_key) VALUES (?,?,?,?,?,?)',
                            (ticket['order_id'],other,'other','test',ticket['created_at'],'wrong-owner'))

    def test_duplicate_key_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO tickets(order_id,requester_id,category,description,created_at,request_key) SELECT order_id,requester_id,category,description,created_at,request_key FROM tickets')

    def test_invalid_states_and_inputs_rejected(self):
        for assignment in ["status='closed'", "status='in_progress'", "description=''", "category='invalid'", "request_key=''", "description='   '"]:
            with self.subTest(assignment=assignment), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute('UPDATE tickets SET '+assignment)

    def test_valid_lifecycle(self):
        staff = self.db.execute("SELECT id FROM users WHERE username='demo_staff_a'").fetchone()[0]
        self.db.execute("UPDATE tickets SET status='in_progress',assignee_id=?,claimed_at='2026-09-17T01:00:00.000Z'", (staff,))
        self.db.execute("UPDATE tickets SET status='closed',resolution='模拟处理完成',closed_at='2026-09-17T02:00:00.000Z'")
        self.assertEqual(self.db.execute('SELECT status FROM tickets').fetchone()[0],'closed')

    def test_closed_requires_result_and_valid_time(self):
        staff = self.db.execute("SELECT id FROM users WHERE role='staff' LIMIT 1").fetchone()[0]
        for result,closed in [(None,'2026-09-17T02:00:00.000Z'),('','2026-09-17T02:00:00.000Z'),('done','2026-09-16T02:00:00.000Z')]:
            with self.subTest(result=result,closed=closed), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute("UPDATE tickets SET status='closed',assignee_id=?,claimed_at='2026-09-17T01:00:00.000Z',resolution=?,closed_at=?",(staff,result,closed))

    def test_event_failure_rolls_back_ticket(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with transaction(self.db):
                self.db.execute("INSERT INTO tickets(order_id,requester_id,category,description,created_at,request_key) SELECT order_id,requester_id,category,description,created_at,'rollback-test' FROM tickets LIMIT 1")
                self.db.execute("INSERT INTO ticket_events(ticket_id,actor_id,event_type,to_status,note,created_at) VALUES (9999,9999,'created','pending','bad','2026-09-17T00:00:00.000Z')")
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0],1)

    def test_invalid_event_transition_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE ticket_events SET event_type='closed',from_status=NULL,to_status='closed'")

    def test_delete_referenced_order_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM orders WHERE id IN (SELECT order_id FROM tickets)')


if __name__ == '__main__':
    unittest.main()
