import tempfile
import unittest
from pathlib import Path

from flask import jsonify
from app import create_app
from aftercare_app.auth import require_role
from aftercare_app.db import connect_database, initialize_database
from aftercare_app.seed import seed_demo


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'auth.sqlite3'
        initialize_database(cls.path)
        db = connect_database(cls.path)
        seed_demo(db, 'local-test-password')
        db.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'isolated-test-secret', 'DATABASE': str(self.path)})

        @self.app.get('/api/test/staff')
        @require_role('staff')
        def staff_only():
            return jsonify(data={'allowed': True})

        self.client = self.app.test_client()

    def token(self, client=None):
        return (client or self.client).get('/api/session').json['data']['csrf_token']

    def login(self, username='demo_customer_a', password='local-test-password'):
        return self.client.post('/api/auth/login', json={'username':username,'password':password}, headers={'X-CSRF-Token':self.token()})

    def test_anonymous_session_is_safe(self):
        response = self.client.get('/api/session')
        self.assertIsNone(response.json['data']['user'])
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_login_rotate_token_and_logout(self):
        old = self.token()
        response = self.login()
        self.assertEqual(response.status_code,200)
        self.assertNotIn('password_hash',response.get_data(as_text=True))
        current = response.json['data']['csrf_token']
        self.assertNotEqual(old,current)
        self.assertEqual(self.client.post('/api/auth/logout', json={}, headers={'X-CSRF-Token':old}).status_code,403)
        self.assertEqual(self.client.post('/api/auth/logout', json={}, headers={'X-CSRF-Token':current}).status_code,200)
        self.assertIsNone(self.client.get('/api/session').json['data']['user'])
        self.assertEqual(self.client.get('/api/test/staff').status_code,401)

    def test_wrong_password_and_unknown_user_same_response(self):
        first = self.login(password='wrong')
        second = self.login(username='no-such-user')
        self.assertEqual(first.status_code,401)
        self.assertEqual(first.json,second.json)

    def test_csrf_missing_wrong_and_other_session(self):
        other_token = self.token(self.app.test_client())
        self.token()
        for value in ['', 'wrong',other_token]:
            with self.subTest(value=value):
                response=self.client.post('/api/auth/login', json={'username':'demo_customer_a','password':'local-test-password'}, headers={'X-CSRF-Token':value})
                self.assertEqual(response.status_code,403)

    def test_bad_inputs_do_not_crash_or_set_role(self):
        token=self.token()
        for body in [[],{}, {'username':None,'password':'x'}, {'username':'a','password':3}, {'username':'a','password':'x','role':'staff'}, {'username':'a'*101,'password':'x'}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post('/api/auth/login',json=body,headers={'X-CSRF-Token':token}).status_code,400)
        response=self.client.post('/api/auth/login',data='{bad',content_type='application/json',headers={'X-CSRF-Token':token})
        self.assertEqual(response.status_code,400)

    def test_role_enforcement(self):
        self.assertEqual(self.client.get('/api/test/staff').status_code,401)
        self.login()
        self.assertEqual(self.client.get('/api/test/staff').status_code,403)
        self.login(username='demo_staff_a')
        self.assertEqual(self.client.get('/api/test/staff').status_code,200)

    def test_role_read_from_database_not_cookie(self):
        self.login()
        with self.client.session_transaction() as session:
            session['role']='staff'
        self.assertEqual(self.client.get('/api/test/staff').status_code,403)

    def test_nonexistent_session_user_cleared(self):
        with self.client.session_transaction() as session:
            session['user_id']=999999
        self.assertIsNone(self.client.get('/api/session').json['data']['user'])

    def test_login_page_assets_and_health(self):
        for path in ['/login','/static/auth.js','/static/auth.css','/health']:
            with self.client.get(path) as response:
                self.assertEqual(response.status_code,200)
        self.assertTrue(self.client.get('/health').json['business_ready'])

    def test_request_too_large_rejected(self):
        response=self.client.post('/api/auth/login',json={'username':'a','password':'x'*20000},headers={'X-CSRF-Token':self.token()})
        self.assertEqual(response.status_code,413)

    def test_wrong_http_method_does_not_logout(self):
        self.login()
        self.assertEqual(self.client.get('/api/auth/logout').status_code,405)
        self.assertIsNotNone(self.client.get('/api/session').json['data']['user'])


if __name__ == '__main__':
    unittest.main()
