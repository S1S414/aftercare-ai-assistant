import unittest
import test_assistant as base
from app import create_app
from aftercare_app.analytics import metrics
from aftercare_app.services.tickets import create_ticket
from uuid import uuid4


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        base.AssistantTests.setUp(self)
        self.app=create_app({'TESTING':True,'DATABASE':str(self.path),'SECRET_KEY':'test'})
        self.client=self.app.test_client()

    def test_deduplicated_orders_and_empty(self):
        for _ in range(2): create_ticket(self.db,self.actor,{'order_id':self.order,'category':'product','description':'test','request_key':str(uuid4())})
        r=metrics(self.db,'2000-01-01','2100-01-01','2099-01-01')
        expected=self.db.execute('SELECT count(DISTINCT order_id) FROM tickets').fetchone()[0]
        self.assertEqual(r['orders_with_ticket'],expected)
        self.assertEqual(r['order_count'],3)
        self.assertEqual(r['aftercare_rate'],expected/3)
        empty=metrics(self.db,'2000-01-01','2000-01-02','2099-01-01')
        self.assertIsNone(empty['aftercare_rate']); self.assertIsNone(empty['average_seconds'])
        self.assertEqual(empty['ticket_count'],0)

    def test_hand_calculated_duration(self):
        tid,_=create_ticket(self.db,self.actor,{'order_id':self.order,'category':'product','description':'test','request_key':str(uuid4())})
        self.db.execute("UPDATE tickets SET status='closed',assignee_id=?,created_at='2020-01-01T00:00:00.000Z',claimed_at='2020-01-01T01:00:00.000Z',closed_at='2020-01-01T02:00:00.000Z',resolution='done' WHERE id=?",(self.staff,tid))
        r=metrics(self.db,'2020-01-01','2020-01-02','2099-01-01')
        self.assertEqual(r['closed_count'],1)
        self.assertAlmostEqual(r['average_seconds'],7200,places=2)

    def test_permissions_and_dates(self):
        with self.client.session_transaction() as s:s['user_id']=self.actor
        self.assertEqual(self.client.get('/staff/analytics').status_code,403)
        self.assertEqual(self.client.get('/api/staff/analytics').status_code,403)
        with self.client.session_transaction() as s:s['user_id']=self.staff
        self.assertEqual(self.client.get('/staff/analytics').status_code,200)
        self.assertEqual(self.client.get('/api/staff/analytics?start=bad').status_code,400)
        self.assertEqual(self.client.get('/api/staff/analytics?start=2026-09-20&end=2026-09-21').status_code,200)
