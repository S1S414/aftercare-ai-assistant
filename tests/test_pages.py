"""5.4：服务端页面权限、转义和状态相关操作入口。"""
import tempfile
import unittest
from pathlib import Path
from app import create_app
from aftercare_app.db import initialize_database, connect_database
from aftercare_app.seed import seed_demo
from aftercare_app.services.tickets import claim_ticket, close_ticket


class PageTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'pages.sqlite3'
        initialize_database(self.path)
        self.db=connect_database(self.path); self.addCleanup(self.db.close)
        seed_demo(self.db,'page-test-password')
        self.app=create_app({'TESTING':True,'SECRET_KEY':'page-tests','DATABASE':str(self.path)})
        self.client=self.app.test_client()
        self.users={r['username']:r['id'] for r in self.db.execute('SELECT id,username FROM users')}
        self.ticket=self.db.execute('SELECT id FROM tickets').fetchone()[0]
        self.order=self.db.execute("SELECT id FROM orders WHERE order_no='DEMO-001'").fetchone()[0]

    def login(self,name):
        with self.client.session_transaction() as session:
            session.clear(); session['user_id']=self.users['demo_'+name]

    def test_anonymous_redirects_and_role_protection(self):
        for path in ['/orders','/tickets','/staff/tickets',f'/tickets/{self.ticket}']:
            self.assertEqual(self.client.get(path).headers['Location'],'/login')
        self.login('customer_a')
        self.assertEqual(self.client.get('/staff/tickets').status_code,403)
        self.assertEqual(self.client.get('/').headers['Location'],'/orders')
        self.login('staff_a')
        self.assertEqual(self.client.get('/orders').status_code,403)
        self.assertEqual(self.client.get('/').headers['Location'],'/staff/tickets')

    def test_customer_pages_and_hidden_other_resources(self):
        self.login('customer_a')
        for path in ['/orders',f'/orders/{self.order}','/tickets',f'/tickets/{self.ticket}']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.login('customer_b')
        for path in [f'/orders/{self.order}',f'/tickets/{self.ticket}']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,404)
            self.assertNotIn('模拟订单已超过',response.get_data(as_text=True))

    def test_user_text_escaped(self):
        payload='<script>alert("x")</script>'
        self.db.execute('UPDATE tickets SET description=?',(payload,))
        self.login('customer_a')
        for path in ['/tickets',f'/tickets/{self.ticket}']:
            html=self.client.get(path).get_data(as_text=True)
            self.assertNotIn(payload,html)
            self.assertIn('&lt;script&gt;',html)

    def test_staff_actions_follow_state_and_owner(self):
        self.login('staff_a'); path=f'/staff/tickets/{self.ticket}'
        self.assertIn('id="claim-ticket"',self.client.get(path).get_data(as_text=True))
        claim_ticket(self.db,self.users['demo_staff_a'],self.ticket)
        html=self.client.get(path).get_data(as_text=True)
        self.assertIn('id="close-ticket"',html)
        self.assertNotIn('id="claim-ticket"',html)
        self.login('staff_b')
        self.assertNotIn('id="close-ticket"',self.client.get(path).get_data(as_text=True))
        close_ticket(self.db,self.users['demo_staff_a'],self.ticket,'已记录结果')
        self.login('staff_a'); html=self.client.get(path).get_data(as_text=True)
        self.assertIn('已记录结果',html)
        self.assertNotIn('id="close-ticket"',html)

    def test_filters_empty_and_pagination(self):
        self.login('customer_a')
        self.assertIn('下一页',self.client.get('/orders?page_size=1').get_data(as_text=True))
        self.assertEqual(self.client.get('/tickets?status=bad').status_code,400)
        self.assertIn('没有符合条件',self.client.get('/tickets?status=closed').get_data(as_text=True))
        self.login('staff_a')
        self.assertEqual(self.client.get('/staff/tickets?status=&mine=false').status_code,200)

    def test_static_resources(self):
        for path in ['/static/business.js','/static/business.css']:
            with self.client.get(path) as response:
                self.assertEqual(response.status_code,200)


if __name__=='__main__':
    unittest.main()
