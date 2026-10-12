import unittest
import test_assistant as base
from app import create_app


class AssistantRouteTests(unittest.TestCase):
    draft = base.AssistantTests.draft
    def setUp(self):
        base.AssistantTests.setUp(self)
        self.app = create_app({'TESTING':True,'DATABASE':str(self.path),'SECRET_KEY':'test'})
        self.client = self.app.test_client()
        with self.client.session_transaction() as s: s['user_id'] = self.actor
        self.headers = {'X-CSRF-Token':self.client.get('/api/session').json['data']['csrf_token']}

    def test_browser_api_flow(self):
        self.assertEqual(self.client.get('/assistant').status_code,200)
        r = self.client.post('/api/assistant/tasks',json={'order_id':self.order,'description':'破损'},headers=self.headers)
        self.assertEqual(r.status_code,201)
        task = r.json['data']; url = '/api/assistant/tasks/'+task['id']
        r = self.client.patch(url,json={'version':1,'category':'product','description':'商品破损'},headers=self.headers)
        self.assertEqual(r.json['data']['version'],2)
        self.assertEqual(self.client.post(url+'/confirm',json={'version':1},headers=self.headers).status_code,409)
        r = self.client.post(url+'/confirm',json={'version':2},headers=self.headers)
        self.assertEqual(r.json['data']['state'],'completed')
        ticket = r.json['data']['ticket_id']
        self.assertEqual(self.client.post(url+'/confirm',json={'version':2},headers=self.headers).json['data']['ticket_id'],ticket)
        self.assertEqual(self.client.get('/tickets/'+str(ticket)).status_code,200)

    def test_csrf_extra_fields_and_roles(self):
        payload = {'order_id':self.order,'description':'破损'}
        self.assertEqual(self.client.post('/api/assistant/tasks',json=payload).status_code,403)
        self.assertEqual(self.client.post('/api/assistant/tasks',json={**payload,'user_id':self.other},headers=self.headers).status_code,400)
        task = self.draft()
        for actor in (self.other,self.staff):
            with self.client.session_transaction() as s: s['user_id'] = actor
            self.assertIn(self.client.get('/api/assistant/tasks/'+task['id']).status_code,(403,404))
        self.assertEqual(self.client.get('/assistant').status_code,403)

    def test_cancel_api(self):
        task = self.draft(); url = '/api/assistant/tasks/'+task['id']
        r = self.client.post(url+'/cancel',json={'version':1},headers=self.headers)
        self.assertEqual(r.json['data']['state'],'cancelled')
        self.assertEqual(self.client.post(url+'/confirm',json={'version':1},headers=self.headers).status_code,409)
