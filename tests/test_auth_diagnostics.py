import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from check_deepseek_auth import check


class AuthDiagnosticsTests(unittest.TestCase):
    def response(self, body, headers=None):
        opener = Mock()
        opener.open.side_effect = HTTPError(
            'https://api.deepseek.com/user/balance', 401, 'Unauthorized',
            headers or {}, io.BytesIO(body))
        return opener

    def test_auth_error_has_safe_details_without_echoed_key(self):
        key = 'test-secret-value'
        opener = self.response(json.dumps({'error': {
            'code': 'invalid_api_key', 'message': 'Invalid API key: ' + key,
            'debug': key}}).encode(), {'x-request-id': 'request-123'})
        result = check(key, opener=opener, direct=True)
        self.assertIn('AUTH_FAILED_401', result)
        self.assertIn('invalid_api_key', result)
        self.assertIn('request-123', result)
        self.assertNotIn(key, result)
        opener.open.assert_called_once()

    def test_secret_in_identifiers_and_raw_html_not_printed(self):
        key = 'test-secret-value'
        for body in [b'<html>private diagnostic</html>', json.dumps({
            'error': {'code': key, 'message': key}}).encode()]:
            result = check(key, opener=self.response(body, {'x-request-id': key}))
            self.assertNotIn(key, result)
            self.assertNotIn('private diagnostic', result)
            self.assertIn('AUTH_FAILED_401', result)

    def test_oversized_error_is_not_exposed(self):
        result = check('test-only', opener=self.response(b'x' * 65537))
        self.assertIn('AUTH_FAILED_401', result)
        self.assertLess(len(result), 500)

    def test_invalid_local_input_does_not_send(self):
        opener = Mock()
        self.assertIn('LOCAL_INPUT_INVALID', check('Bearer secret', opener=opener))
        opener.open.assert_not_called()
