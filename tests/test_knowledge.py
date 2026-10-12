"""6.4：检索基线、来源一致性与访问边界。"""
import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path
from app import create_app
from aftercare_app.db import initialize_database, connect_database
from aftercare_app.seed import seed_demo


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'test.sqlite3'
        initialize_database(path)
        db = connect_database(path)
        seed_demo(db, 'knowledge-test-only')
        self.users = {r['role']: r['id'] for r in db.execute('SELECT id,role FROM users')}
        db.close()
        self.app = create_app({'TESTING': True, 'DATABASE': str(path), 'SECRET_KEY': 'test'})
        self.client = self.app.test_client()
        self.index = self.app.extensions['policy_index']

    def login(self, role='customer'):
        with self.client.session_transaction() as session:
            session['user_id'] = self.users[role]

    def test_web_full_context_and_top3_override(self):
        self.login()
        self.app.config['DEEPSEEK_API_KEY'] = 'synthetic'
        headers = {'X-CSRF-Token': self.client.get('/api/session').json['data']['csrf_token']}
        raw = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(
            {'answerable': True, 'answer': '关闭不等于退款。', 'citations': ['ticket-progress']})}}]}
        with patch('aftercare_app.knowledge.transport', return_value=raw) as send:
            self.assertEqual(self.client.get('/knowledge/ask').status_code, 200)
            send.assert_not_called()
            response = self.client.post('/api/knowledge/model-answer', json={'q': '客服把售后单结了，钱就会自动到账对吧？'}, headers=headers)
            self.assertEqual(response.json['data']['status'], 'answered')
            self.assertEqual(response.json['data']['context_strategy'], 'all-small')
            sources = json.loads(send.call_args.args[1]['messages'][1]['content'])['sources']
            self.assertEqual(len(sources), 6)
            self.assertIn('ticket-progress', [s['id'] for s in sources])
            self.app.config['QA_CONTEXT_STRATEGY'] = 'top3'
            response = self.client.post('/api/knowledge/model-answer', json={'q': '客服把售后单结了，钱就会自动到账对吧？'}, headers=headers)
            self.assertEqual(response.json['data']['context_strategy'], 'top3')
            self.assertEqual(response.json['data']['reason'], 'provider_or_validation_error')

    def test_web_context_bounds_prevent_network_and_reservation(self):
        self.login()
        self.app.config['DEEPSEEK_API_KEY'] = 'synthetic'
        headers = {'X-CSRF-Token': self.client.get('/api/session').json['data']['csrf_token']}
        original = self.index.chunks
        for chunks in (original * 2, [{**original[0], 'text': '长' * 6001}]):
            self.index.chunks = chunks
            with patch('aftercare_app.knowledge.transport') as send, patch('aftercare_app.model_usage.reserve') as reserve:
                response = self.client.post('/api/knowledge/model-answer', json={'q': '商品破损怎么办'}, headers=headers)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json['error']['code'], 'context_limit')
                send.assert_not_called()
                reserve.assert_not_called()

    def test_known_questions(self):
        for query, expected in [('商品破损怎么办', 'product-damage'), ('退货换货', 'return-query'), ('配送超时', 'delivery-delay')]:
            self.assertEqual(self.index.search(query)[0]['id'], expected)

    def test_empty_and_deterministic_results(self):
        self.assertEqual(self.index.search('火星宇宙飞船'), [])
        self.assertEqual(self.index.search('退款'), self.index.search('退款'))
        self.assertLessEqual(len(self.index.search('工单')), 3)

    def test_authentication(self):
        self.assertEqual(self.client.get('/knowledge').headers['Location'], '/login')
        self.assertEqual(self.client.get('/api/knowledge/search?q=退款').status_code, 401)
        self.assertEqual(self.client.get('/knowledge/sources/privacy').status_code, 302)
        for role in ('customer', 'staff'):
            self.login(role)
            self.assertEqual(self.client.get('/knowledge?q=配送超时').status_code, 200)

    def test_invalid_queries(self):
        self.login()
        for qs in ['', 'q=', 'q=a', 'q=' + 'a'*201, 'q=abc&q=def', 'q=abc&other=1']:
            self.assertEqual(self.client.get('/api/knowledge/search?' + qs).status_code, 400)

    def test_answer_page_and_api(self):
        self.login()
        response = self.client.get('/knowledge/ask?q=商品破损怎么办')
        self.assertEqual(response.status_code, 200)
        self.assertIn('政策原文答复', response.get_data(as_text=True))
        data = self.client.get('/api/knowledge/answer?q=商品破损怎么办').json['data']
        self.assertEqual(data['status'], 'quoted')
        self.assertEqual(self.client.get('/api/knowledge/answer?q=').status_code, 400)
        html = self.client.get('/knowledge/ask', query_string={'q':'<script>alert(1)</script>'}).get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', html)

    def test_model_endpoint_guards_and_no_key(self):
        self.app.config['DEEPSEEK_API_KEY']=''
        self.login()
        self.assertEqual(self.client.post('/api/knowledge/model-answer',json={'q':'商品破损'}).status_code,403)
        token=self.client.get('/api/session').json['data']['csrf_token']
        headers={'X-CSRF-Token':token}
        response=self.client.post('/api/knowledge/model-answer',json={'q':'商品破损'},headers=headers)
        self.assertEqual(response.json['data']['reason'],'not_configured')
        self.assertEqual(self.client.post('/api/knowledge/model-answer',json={'q':1},headers=headers).status_code,400)
        self.assertEqual(self.client.get('/api/knowledge/model-answer').status_code,405)

    def test_sources_and_no_generation(self):
        self.login()
        data = self.client.get('/api/knowledge/search?q=商品破损').json['data']
        self.assertFalse(data['generated_answer'])
        self.assertEqual(len(data['corpus_sha256']), 64)
        for item in data['items']:
            response = self.client.get(item['source_url'])
            self.assertIn(item['text'], response.get_data(as_text=True))
            self.assertIn(item['version'], response.get_data(as_text=True))
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/knowledge/sources/missing').status_code, 404)

    def test_query_escaping_and_no_match_message(self):
        self.login()
        html = self.client.get('/knowledge', query_string={'q': '<script>alert(1)</script>'}).get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)
        html = self.client.get('/knowledge?q=火星宇宙飞船').get_data(as_text=True)
        self.assertIn('未找到词语匹配', html)
