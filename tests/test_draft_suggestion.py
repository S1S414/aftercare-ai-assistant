import unittest
import json
from unittest.mock import patch
import test_assistant as base
from app import create_app


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        base.AssistantTests.setUp(self)
        self.app=create_app({'TESTING':True,'DATABASE':str(self.path),'SECRET_KEY':'test','DEEPSEEK_API_KEY':'synthetic'})
        self.client=self.app.test_client()
        with self.client.session_transaction() as s: s['user_id']=self.actor
        self.headers={'X-CSRF-Token':self.client.get('/api/session').json['data']['csrf_token']}
        self.task=base.AssistantTests.draft(self)
        self.url='/api/assistant/tasks/'+self.task['id']+'/suggest'

    def raw(self, data):
        return {'id':'mock','usage':{'total_tokens':40},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]}

    def test_suggestion_does_not_write_and_is_metered(self):
        value={'category':'product','summary':'商品破损，请核查','citations':['product-damage']}
        with patch('aftercare_app.assistant_routes.transport',return_value=self.raw(value)) as send:
            r=self.client.post(self.url,json={'version':1},headers=self.headers)
            self.assertEqual(r.json['data']['status'],'suggested')
            self.assertEqual(send.call_count,1)
            payload=json.loads(send.call_args.args[1]['messages'][1]['content'])
            self.assertEqual(set(payload),{'description','policies'})
        row=self.db.execute('SELECT * FROM assistant_tasks WHERE id=?',(self.task['id'],)).fetchone()
        self.assertEqual(row['state'],'draft'); self.assertEqual(row['version'],1); self.assertIsNone(row['ticket_id'])
        self.assertEqual(self.db.execute('SELECT endpoint FROM model_calls').fetchone()[0],'/api/assistant/tasks/suggest')

    def test_invalid_output_fails_closed(self):
        with patch('aftercare_app.assistant_routes.transport',return_value=self.raw({'category':'product','summary':'问题','citations':['invented']})):
            r=self.client.post(self.url,json={'version':1},headers=self.headers)
            self.assertEqual(r.json['data']['status'],'unavailable')

    def test_stale_and_missing_csrf_no_network(self):
        with patch('aftercare_app.assistant_routes.transport') as send:
            self.assertEqual(self.client.post(self.url,json={'version':1}).status_code,403)
            self.assertEqual(self.client.post(self.url,json={'version':2},headers=self.headers).status_code,409)
            send.assert_not_called()

    def test_changed_during_call_discarded(self):
        from aftercare_app.services.assistant import cancel_task
        def response(*args):
            cancel_task(self.db,self.actor,self.task['id'],1)
            return self.raw({'category':'other','summary':'问题','citations':[]})
        with patch('aftercare_app.assistant_routes.transport',side_effect=response):
            self.assertEqual(self.client.post(self.url,json={'version':1},headers=self.headers).status_code,409)

    def test_business_end_to_end(self):
        r=self.client.post('/api/assistant/tasks/'+self.task['id']+'/confirm',json={'version':1},headers=self.headers)
        tid=r.json['data']['ticket_id']
        with self.client.session_transaction() as s: s['user_id']=self.staff
        self.assertEqual(self.client.post(f'/api/staff/tickets/{tid}/claim',json={},headers=self.headers).status_code,200)
        self.assertEqual(self.client.post(f'/api/staff/tickets/{tid}/close',json={'resolution':'已记录并核查模拟问题'},headers=self.headers).status_code,200)
        with self.client.session_transaction() as s: s['user_id']=self.actor
        r=self.client.get(f'/api/tickets/{tid}')
        self.assertEqual(r.json['data']['status'],'closed')
        self.assertEqual(len(r.json['data']['events']),3)
