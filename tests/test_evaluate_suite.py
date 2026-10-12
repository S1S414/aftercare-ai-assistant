import unittest
from unittest.mock import patch, Mock
from evaluate_suite import load_cases, retrieval_comparison, run_live, ROOT
from aftercare_app.retrieval import PolicyIndex
from aftercare_app.model_usage import UsageBlocked


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.index = PolicyIndex(ROOT / 'data/policies.json')
        cases, _ = load_cases()
        self.rows = retrieval_comparison(self.index, cases)

    def test_separate_datasets_and_unknown_denominator(self):
        self.assertEqual(len(self.rows),22)
        self.assertEqual(sum(r['source'] is not None for r in self.rows),13)
        self.assertTrue(all(r['v2_hit'] is None for r in self.rows if r['source'] is None))

    def test_failure_stops_and_saves(self):
        send=Mock(side_effect=TimeoutError())
        save=Mock()
        with patch('evaluate_suite.model_usage.reserve',return_value='test-id'), patch('evaluate_suite.model_usage.finish') as finish:
            run_live(self.index,self.rows,Mock(),1,'synthetic',save,send=send,wait=Mock())
        self.assertEqual(send.call_count,1)
        self.assertEqual(finish.call_count,1)
        self.assertEqual(sum('model_result' in r for r in self.rows),1)
        save.assert_called_once()

    def test_cap_cannot_be_bypassed(self):
        send=Mock()
        with patch('evaluate_suite.model_usage.reserve',side_effect=UsageBlocked('limit')):
            run_live(self.index,self.rows,Mock(),1,'synthetic',Mock(),send=send,wait=Mock())
        send.assert_not_called()
        self.assertTrue(any('blocked' in r for r in self.rows))
