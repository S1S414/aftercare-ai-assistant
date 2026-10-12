import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from app import create_app
from aftercare_app.db import connect_database, initialize_database
from aftercare_app.seed import seed_demo
from aftercare_app.services.tickets import claim_ticket, create_ticket, BusinessError


class TicketTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'tickets.sqlite3'
        initialize_database(self.path)
        self.db=connect_database(self.path)
        self.addCleanup(self.db.close)
        seed_demo(self.db,'test-password-long')
        self.app=create_app({'TESTING':True,'SECRET_KEY':'test-only-secret','DATABASE':str(self.path)})
        self.clients={}
        self.ids={r['username']:r['id'] for r in self.db.execute('SELECT id,username FROM users')}
        for short in ('customer_a','customer_b','staff_a','staff_b'):
            client=self.app.test_client()
            with client.session_transaction() as s:
                s['user_id']=self.ids['demo_'+short]
                s['csrf_token']='test-token'
            self.clients[short]=client
        self.order=self.db.execute("SELECT id FROM orders WHERE order_no='DEMO-001'").fetchone()[0]
        self.ticket=self.db.execute('SELECT id FROM tickets').fetchone()[0]

    def post(self,who,path,body):
        return self.clients[who].post(path,json=body,headers={'X-CSRF-Token':'test-token'})

    def payload(self):
        return {'order_id':self.order,'category':'delivery','description':'请检查配送','request_key':str(uuid4())}

    def test_order_and_ticket_isolation(self):
        self.assertEqual(self.clients['customer_a'].get('/api/orders').json['data']['total'],2)
        self.assertEqual(self.clients['customer_b'].get('/api/orders').json['data']['total'],1)
        for path in [f'/api/orders/{self.order}',f'/api/tickets/{self.ticket}']:
            self.assertEqual(self.clients['customer_a'].get(path).status_code,200)
            self.assertEqual(self.clients['customer_b'].get(path).status_code,404)
        self.assertEqual(self.clients['customer_b'].get('/api/tickets').json['data']['total'],0)
        self.assertEqual(self.post('customer_b','/api/tickets',self.payload()).status_code,404)

    def test_creation_replay_and_conflict(self):
        payload=self.payload()
        first=self.post('customer_a','/api/tickets',payload)
        second=self.post('customer_a','/api/tickets',payload)
        self.assertEqual(first.status_code,201)
        self.assertEqual(second.status_code,200)
        self.assertEqual(first.json['data']['ticket']['id'],second.json['data']['ticket']['id'])
        self.assertTrue(second.json['data']['replayed'])
        self.assertEqual(len(second.json['data']['ticket']['events']),1)
        payload['description']='不同问题'
        self.assertEqual(self.post('customer_a','/api/tickets',payload).status_code,409)

    def test_invalid_creation(self):
        for change in [{'order_id':True},{'description':' '},{'description':'x'*2001},{'category':[]},{'request_key':'bad'},{'requester_id':999}]:
            payload=self.payload();payload.update(change)
            with self.subTest(change=change):
                self.assertEqual(self.post('customer_a','/api/tickets',payload).status_code,400)
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0],1)

    def test_roles_and_anonymous(self):
        for path in ['/api/orders','/api/tickets','/api/staff/tickets']:
            self.assertEqual(self.app.test_client().get(path).status_code,401)
        self.assertEqual(self.clients['customer_a'].get('/api/staff/tickets').status_code,403)
        self.assertEqual(self.post('staff_a','/api/tickets',self.payload()).status_code,403)
        self.assertEqual(self.post('customer_a',f'/api/staff/tickets/{self.ticket}/claim',{}).status_code,403)

    def test_full_lifecycle_and_events(self):
        base=f'/api/staff/tickets/{self.ticket}'
        self.assertEqual(self.post('staff_a',base+'/close',{'resolution':'完成'}).status_code,409)
        self.assertEqual(self.post('staff_a',base+'/claim',{}).status_code,200)
        self.assertEqual(self.post('staff_b',base+'/claim',{}).status_code,409)
        self.assertEqual(self.post('staff_b',base+'/close',{'resolution':'完成'}).status_code,403)
        self.assertEqual(self.post('staff_a',base+'/close',{'resolution':' '}).status_code,400)
        closed=self.post('staff_a',base+'/close',{'resolution':'已记录模拟处理结果'})
        self.assertEqual(closed.status_code,200)
        self.assertEqual(closed.json['data']['status'],'closed')
        self.assertEqual([x['event_type'] for x in closed.json['data']['events']],['created','claimed','closed'])
        self.assertEqual(self.post('staff_a',base+'/close',{'resolution':'再关闭'}).status_code,409)
        self.assertEqual(self.clients['staff_a'].get('/api/staff/tickets?mine=true&status=closed').json['data']['total'],1)

    def test_paging_and_filters(self):
        for query in ['page=0','page_size=101','page=abc','page=1&page=2','status=no','unknown=x']:
            self.assertEqual(self.clients['customer_a'].get('/api/tickets?'+query).status_code,400)
        self.assertEqual(self.clients['staff_a'].get('/api/staff/tickets?mine=bad').status_code,400)
        data=self.clients['customer_a'].get('/api/orders?page=2&page_size=1').json['data']
        self.assertEqual(data['total'],2)
        self.assertEqual(len(data['items']),1)

    def test_csrf_enforced_on_business_writes(self):
        self.assertEqual(self.clients['customer_a'].post('/api/tickets',json=self.payload()).status_code,403)

    def test_failed_event_rolls_back_service_write(self):
        with patch('aftercare_app.services.tickets.event',side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):
                create_ticket(self.db,self.ids['demo_customer_a'],self.payload())
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0],1)

    def test_concurrent_claim_one_winner(self):
        barrier=Barrier(2)
        def worker(actor):
            db=connect_database(self.path)
            try:
                barrier.wait(timeout=5)
                try:
                    claim_ticket(db,actor,self.ticket)
                    return 200
                except BusinessError as error:
                    return error.status
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(worker,[self.ids['demo_staff_a'],self.ids['demo_staff_b']]))
        self.assertEqual(sorted(results),[200,409])
        self.assertEqual(self.db.execute("SELECT count(*) FROM ticket_events WHERE event_type='claimed'").fetchone()[0],1)

    def test_concurrent_creation_one_ticket(self):
        barrier=Barrier(2);payload=self.payload()
        def worker(_):
            db=connect_database(self.path)
            try:
                barrier.wait(timeout=5)
                return create_ticket(db,self.ids['demo_customer_a'],payload)
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(worker,range(2)))
        self.assertEqual(results[0][0],results[1][0])
        self.assertEqual(sorted(x[1] for x in results),[False,True])


if __name__=='__main__':
    unittest.main()
