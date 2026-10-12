import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from aftercare_app.db import initialize_database, connect_database
from aftercare_app.seed import seed_demo
from aftercare_app.services import assistant as service
from aftercare_app.services.tickets import BusinessError


class AssistantTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'test.sqlite3'
        initialize_database(self.path)
        self.db = connect_database(self.path)
        self.addCleanup(self.db.close)
        seed_demo(self.db, 'test-assistant-password')
        self.actor = self.db.execute("SELECT id FROM users WHERE username='demo_customer_a'").fetchone()[0]
        self.other = self.db.execute("SELECT id FROM users WHERE username='demo_customer_b'").fetchone()[0]
        self.staff = self.db.execute("SELECT id FROM users WHERE role='staff' LIMIT 1").fetchone()[0]
        self.order = self.db.execute('SELECT id FROM orders WHERE user_id=?', (self.actor,)).fetchone()[0]

    def draft(self):
        return service.create_draft(self.db, self.actor, self.order, '商品破损，请核查')

    def count(self):
        return self.db.execute('SELECT count(*) FROM tickets').fetchone()[0]

    def test_edit_stale_confirm_and_replay(self):
        count = self.count()
        task = self.draft()
        self.assertEqual(self.count(), count)
        self.assertNotIn('request_key', task)
        updated = service.edit_draft(self.db, self.actor, task['id'], 1, 'product', '包装破损')
        self.assertEqual(updated['version'], 2)
        with self.assertRaises(BusinessError): service.confirm_task(self.db, self.actor, task['id'], 1)
        result = service.confirm_task(self.db, self.actor, task['id'], 2)
        repeat = service.confirm_task(self.db, self.actor, task['id'], 2)
        self.assertEqual(result['ticket_id'], repeat['ticket_id'])
        self.assertEqual(self.count(), count + 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM assistant_events WHERE action='completed'").fetchone()[0], 1)

    def test_cancel_blocks_confirmation(self):
        task = self.draft()
        count = self.count()
        service.cancel_task(self.db, self.actor, task['id'], 1)
        service.cancel_task(self.db, self.actor, task['id'], 1)
        with self.assertRaises(BusinessError): service.confirm_task(self.db, self.actor, task['id'], 1)
        self.assertEqual(self.count(), count)

    def test_ownership_and_role(self):
        task = self.draft()
        for actor in (self.other, self.staff):
            with self.assertRaises(BusinessError): service.get_task(self.db, actor, task['id'])
            with self.assertRaises(BusinessError): service.confirm_task(self.db, actor, task['id'], 1)
            with self.assertRaises(BusinessError): service.create_draft(self.db, actor, self.order, '问题')
        with self.assertRaises(BusinessError): service.confirm_task(self.db, self.actor, task['id'], True)

    def test_event_failure_rolls_back_ticket_and_task(self):
        task = self.draft()
        count = self.count()
        events = self.db.execute('SELECT count(*) FROM ticket_events').fetchone()[0]
        with patch.object(service, '_event', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError): service.confirm_task(self.db, self.actor, task['id'], 1)
        self.assertEqual(self.count(), count)
        self.assertEqual(self.db.execute('SELECT count(*) FROM ticket_events').fetchone()[0], events)
        self.assertEqual(service.get_task(self.db, self.actor, task['id'])['state'], 'draft')
        self.assertEqual(service.confirm_task(self.db, self.actor, task['id'], 1)['state'], 'completed')

    def test_concurrent_confirm_and_persistence(self):
        task = self.draft()
        count = self.count()
        barrier = Barrier(2)
        def run(_):
            db = connect_database(self.path)
            try:
                barrier.wait()
                return service.confirm_task(db, self.actor, task['id'], 1)['ticket_id']
            finally:
                db.close()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.count(), count + 1)
        initialize_database(self.path)
        db = connect_database(self.path)
        try:
            self.assertEqual(service.get_task(db, self.actor, task['id'])['ticket_id'], results[0])
        finally:
            db.close()
