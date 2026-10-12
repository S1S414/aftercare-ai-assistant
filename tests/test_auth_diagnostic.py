import io
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
from check_deepseek_auth import check


class AuthDiagnosticTests(unittest.TestCase):
    def test_direct_disables_explicit_proxy(self):
        with patch('check_deepseek_auth.urllib.request.build_opener') as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"is_available":true}'
            self.assertTrue(check('test-secret', direct=True).startswith('AUTH_OK'))
            self.assertEqual(build.call_args.args[1].proxies, {})

    def test_success_one_get_no_secret_output(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"is_available":true}'
        result = check('test-secret', opener)
        self.assertTrue(result.startswith('AUTH_OK'))
        self.assertNotIn('test-secret', result)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.deepseek.com/user/balance')
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)

    def test_errors_do_not_echo_sensitive_body_or_exception(self):
        for failure, expected in [
            (urllib.error.HTTPError('https://api.deepseek.com/user/balance', 401, 'secret', {}, io.BytesIO(b'secret')), 'AUTH_FAILED_401'),
            (urllib.error.URLError('secret'), 'NETWORK_ERROR'),
        ]:
            opener = MagicMock()
            opener.open.side_effect = failure
            result = check('test-secret', opener)
            self.assertTrue(result.startswith(expected))
            self.assertNotIn('secret', result)
            opener.open.assert_called_once()

    def test_invalid_input_does_not_send(self):
        opener = MagicMock()
        for value in ['', 'Bearer abc', 'abc def', 'abc\nxyz', '密钥', '"abc"']:
            self.assertTrue(check(value, opener).startswith('LOCAL_INPUT_INVALID'))
        opener.open.assert_not_called()
