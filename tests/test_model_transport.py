import unittest
from unittest.mock import MagicMock, patch
from aftercare_app.model_qa import transport, NoRedirect


class TransportTests(unittest.TestCase):
    def test_direct_authenticated_request_is_bounded(self):
        with patch('aftercare_app.model_qa.urllib.request.build_opener') as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"choices": []}'
            self.assertEqual(transport('test-only', {'model': 'test'}), {'choices': []})
            handlers = build.call_args.args
            self.assertIs(handlers[0], NoRedirect)
            self.assertEqual(handlers[1].proxies, {})
            build.return_value.open.assert_called_once()
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.deepseek.com/chat/completions')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-only')
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(build.return_value.open.call_args.kwargs['timeout'], 20)
            response.read.assert_called_once_with(262145)

    def test_oversized_response_rejected(self):
        with patch('aftercare_app.model_qa.urllib.request.build_opener') as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value = b'x' * 262145
            with self.assertRaises(ValueError):
                transport('test-only', {})

    def test_redirect_rejected(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))
