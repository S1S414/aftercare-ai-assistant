import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import create_app


class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING':True, 'PUBLIC_DEMO':True,
                              'SECRET_KEY':'test-demo-secret', 'DEMO_DIRECTORY':self.temp.name,
                              'DATABASE':str(Path(self.temp.name)/'must-not-create.sqlite3'),
                              'DEEPSEEK_API_KEY':'must-never-send'})
        self.a, self.b = self.app.test_client(), self.app.test_client()

    def enter(self, client, role='customer'):
        client.get('/demo')
        token = client.get('/api/session').json['data']['csrf_token']
        response = client.post('/demo/enter', data={'csrf_token':token,'role':role})
        self.assertEqual(response.status_code, 302)
        return client.get('/api/session').json['data']['csrf_token']

    def post(self, client, url, data):
        token = client.get('/api/session').json['data']['csrf_token']
        return client.post(url, json=data, headers={'X-CSRF-Token':token})

    def test_full_flow_isolation_and_no_external_model(self):
        self.enter(self.a)
        self.enter(self.b)
        self.assertEqual(self.a.get('/assistant').status_code, 200)
        task = self.post(self.a, '/api/assistant/tasks', {'order_id':2,'description':'商品外壳破损，请核查'}).json['data']
        url = '/api/assistant/tasks/'+task['id']
        with patch('aftercare_app.assistant_routes.transport', side_effect=AssertionError('external call')), patch('aftercare_app.knowledge.transport', side_effect=AssertionError('external call')):
            suggestion = self.post(self.a, url+'/suggest', {'version':1}).json['data']
            self.assertEqual(suggestion['mode'], 'simulation')
            result = self.post(self.a, '/api/knowledge/model-answer', {'q':'商品破损怎么办'}).json['data']
            self.assertFalse(result['generated_answer'])
            self.assertEqual(result['mode'], 'simulation')
        self.assertEqual(self.b.get(url).status_code, 404)
        ticket = self.post(self.a, url+'/confirm', {'version':1}).json['data']['ticket_id']
        self.enter(self.a, 'staff')
        self.assertEqual(self.post(self.a, f'/api/staff/tickets/{ticket}/claim', {}).status_code, 200)
        self.assertEqual(self.post(self.a, f'/api/staff/tickets/{ticket}/close', {'resolution':'演示核查完成，无实际退款'}).status_code, 200)
        self.enter(self.a)
        self.assertEqual(self.a.get(f'/api/tickets/{ticket}').json['data']['status'], 'closed')
        self.enter(self.b, 'staff')
        self.assertEqual(self.b.get(f'/api/tickets/{ticket}').status_code, 404)
        self.assertFalse(Path(self.app.config['DATABASE']).exists())
        self.assertEqual(self.app.config['DEEPSEEK_API_KEY'], '')

    def test_entry_csrf_and_expiry(self):
        self.assertEqual(self.a.post('/demo/enter', data={'role':'staff'}).status_code, 403)
        self.assertEqual(self.a.get('/').location, '/demo')
        self.enter(self.a)
        with self.a.session_transaction() as session:
            sid = session['demo_id']
        path = Path(self.temp.name)/(sid+'.sqlite3')
        os.utime(path, (1,1))
        self.assertEqual(self.a.get('/orders').location, '/demo')
        self.assertFalse(path.exists())

    def test_local_mode_unchanged(self):
        app = create_app({'TESTING':True,'PUBLIC_DEMO':False})
        self.assertEqual(app.test_client().get('/demo').status_code, 404)


if __name__ == '__main__':
    unittest.main()
