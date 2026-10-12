import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
import json
from app import create_app
from aftercare_app.db import initialize_database, connect_database
from aftercare_app.seed import seed_demo
from aftercare_app import model_usage as usage


class UsageTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'usage.sqlite3'
        initialize_database(self.path)
        self.db=connect_database(self.path); self.addCleanup(self.db.close)
        seed_demo(self.db,'usage-test-only-password')
        self.users=[dict(r) for r in self.db.execute('SELECT id,role FROM users ORDER BY id')]
        self.uid=self.users[0]['id']
        self.now=datetime(2026,9,18,0,0,tzinfo=timezone.utc)
        usage.ensure_table(self.db)

    def complete(self, now):
        rid=usage.reserve(self.db,self.uid,'127.0.0.1','mock',now)
        usage.finish(self.db,rid,{'status':'unavailable','reason':'timeout','usage':None})
        return rid

    def test_daily_cap_persists_after_reopen(self):
        for i in range(20): self.complete(self.now+timedelta(minutes=i))
        other=connect_database(self.path)
        try:
            with self.assertRaises(usage.UsageBlocked): usage.reserve(other,self.uid,'local','mock',self.now+timedelta(hours=1))
            usage.reserve(other,self.uid,'local','mock',self.now+timedelta(days=1))
        finally: other.close()

    def test_minute_cap_and_shared_users(self):
        for i in range(5): self.complete(self.now+timedelta(seconds=i))
        with self.assertRaises(usage.UsageBlocked):
            usage.reserve(self.db,self.users[1]['id'],'local','mock',self.now+timedelta(seconds=6))

    def test_beijing_midnight(self):
        before=datetime(2026,9,18,15,59,tzinfo=timezone.utc)
        rid=self.complete(before)
        self.assertEqual(self.db.execute('SELECT day FROM model_calls WHERE id=?',(rid,)).fetchone()[0],'2026-09-18')
        rid=self.complete(before+timedelta(minutes=1))
        self.assertEqual(self.db.execute('SELECT day FROM model_calls WHERE id=?',(rid,)).fetchone()[0],'2026-09-19')

    def test_concurrent_reservation_only_one(self):
        barrier=Barrier(2)
        def task():
            db=connect_database(self.path)
            try:
                barrier.wait()
                return usage.reserve(db,self.uid,'local','mock',self.now)
            except usage.UsageBlocked: return None
            finally: db.close()
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:task(),range(2)))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_visibility_and_unknown_usage(self):
        self.complete(self.now)
        self.assertEqual(usage.recent(self.db,self.users[1]),[])
        staff=next(u for u in self.users if u['role']=='staff')
        self.assertEqual(len(usage.recent(self.db,staff)),1)
        self.assertIsNone(usage.recent(self.db,staff)[0]['total_tokens'])

    def test_endpoint_audit_and_block_before_network(self):
        app=create_app({'TESTING':True,'DATABASE':str(self.path),'SECRET_KEY':'test','DEEPSEEK_API_KEY':'synthetic'})
        client=app.test_client()
        with client.session_transaction() as s: s['user_id']=self.uid
        headers={'X-CSRF-Token':client.get('/api/session').json['data']['csrf_token']}
        raw={'id':'provider-test','usage':{'prompt_tokens':12,'completion_tokens':8,'total_tokens':20},
             'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'answerable':True,'answer':'请提交商品工单。','citations':['product-damage']})}}]}
        with patch('aftercare_app.knowledge.transport',return_value=raw) as send:
            r=client.post('/api/knowledge/model-answer',json={'q':'商品破损怎么办'},headers=headers)
            self.assertEqual(r.status_code,200)
            self.assertTrue(r.json['data']['local_request_id'])
            record=usage.recent(self.db,self.users[0])[0]
            self.assertEqual(record['total_tokens'],20)
            self.assertEqual(record['provider_id'],'provider-test')
            usage.reserve(self.db,self.uid,'local','mock')
            r=client.post('/api/knowledge/model-answer',json={'q':'商品破损怎么办'},headers=headers)
            self.assertEqual(r.status_code,429)
            self.assertEqual(send.call_count,1)
        page=client.get('/knowledge/usage')
        self.assertEqual(page.status_code,200)
        self.assertNotIn('synthetic',page.get_data(as_text=True))

    def test_audit_failure_prevents_network(self):
        app=create_app({'TESTING':True,'DATABASE':str(self.path),'SECRET_KEY':'test','DEEPSEEK_API_KEY':'synthetic'})
        client=app.test_client()
        with client.session_transaction() as s: s['user_id']=self.uid
        headers={'X-CSRF-Token':client.get('/api/session').json['data']['csrf_token']}
        import sqlite3
        with patch('aftercare_app.model_usage.reserve',side_effect=sqlite3.OperationalError('locked')), patch('aftercare_app.knowledge.transport') as send:
            self.assertEqual(client.post('/api/knowledge/model-answer',json={'q':'商品破损'},headers=headers).status_code,503)
            send.assert_not_called()

    def test_pending_requires_explicit_reconciliation_and_stays_counted(self):
        rid=usage.reserve(self.db,self.uid,'local','mock',self.now)
        with self.assertRaises(ValueError): usage.resolve_pending(self.db,rid)
        with self.assertRaises(usage.UsageBlocked):
            usage.reserve(self.db,self.uid,'local','mock',self.now+timedelta(seconds=1))
        usage.resolve_pending(self.db,rid,reviewed=True)
        row=dict(self.db.execute('SELECT * FROM model_calls WHERE id=?',(rid,)).fetchone())
        self.assertEqual(row['status'],'unavailable')
        self.assertEqual(row['reason'],'manually_reconciled_unknown')
        self.assertIsNotNone(row['finished_at'])
        # A late response must not overwrite the operator's reconciliation.
        self.assertFalse(usage.finish(self.db,rid,{'status':'answered','reason':'ok','usage':{'total_tokens':1}}))
        self.assertEqual(self.db.execute('SELECT reason FROM model_calls WHERE id=?',(rid,)).fetchone()[0],
                         'manually_reconciled_unknown')
        usage.reserve(self.db,self.uid,'local','mock',self.now+timedelta(seconds=1))

    def test_reconciliation_rejects_unknown_or_finished_call(self):
        with self.assertRaises(ValueError): usage.resolve_pending(self.db,'not-a-uuid',reviewed=True)
        with self.assertRaises(ValueError): usage.resolve_pending(self.db,str(__import__('uuid').uuid4()),reviewed=True)
        rid=self.complete(self.now)
        with self.assertRaises(ValueError): usage.resolve_pending(self.db,rid,reviewed=True)

    def test_endpoint_is_written_atomically_with_reservation(self):
        rid=usage.reserve(self.db,self.uid,'local','mock',self.now,
                          endpoint='/api/assistant/tasks/suggest')
        self.assertEqual(self.db.execute('SELECT endpoint FROM model_calls WHERE id=?',(rid,)).fetchone()[0],
                         '/api/assistant/tasks/suggest')
        usage.finish(self.db,rid,{'status':'unavailable','reason':'test','usage':None})
        with self.assertRaises(ValueError):
            usage.reserve(self.db,self.uid,'local','mock',self.now+timedelta(minutes=2),endpoint='/unknown')
