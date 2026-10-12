import json
import unittest
from unittest.mock import Mock, patch
from evaluate_quality import run, ROOT
from aftercare_app.retrieval import PolicyIndex
from aftercare_app.model_usage import UsageBlocked


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.rows=json.loads((ROOT/'data/quality-cases.json').read_text(encoding='utf-8'))
        self.index=PolicyIndex(ROOT/'data/policies.json')

    def test_failure_saved_once_then_stop(self):
        send=Mock(side_effect=TimeoutError())
        save=Mock()
        with patch('evaluate_quality.model_usage.reserve',return_value='test'), patch('evaluate_quality.model_usage.finish') as finish:
            run(self.rows,self.index,None,1,'synthetic',save,send=send,wait=Mock())
        send.assert_called_once(); save.assert_called_once(); finish.assert_called_once()
        self.assertEqual(self.rows[0]['result']['reason'],'network_error')
        self.assertNotIn('result',self.rows[1])
        self.assertIsNone(self.rows[0]['human_review']['overall'])

    def test_limit_blocks_before_network(self):
        send=Mock(); save=Mock()
        with patch('evaluate_quality.model_usage.reserve',side_effect=UsageBlocked('limit')):
            run(self.rows,self.index,None,1,'synthetic',save,send=send,wait=Mock())
        send.assert_not_called(); save.assert_called_once()
        self.assertEqual(self.rows[0]['blocked'],'limit')

    def test_both_paths_and_human_review_remains_pending(self):
        qa={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'answerable':False,'answer':'','citations':[]})}}]}
        draft={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'category':'product','summary':'杯子裂了，希望核查','citations':['product-damage']})}}]}
        rows=[self.rows[1],self.rows[3]]
        with patch('evaluate_quality.model_usage.reserve',return_value='test'),patch('evaluate_quality.model_usage.finish'):
            run(rows,self.index,None,1,'synthetic',Mock(),send=Mock(side_effect=[qa,draft]),wait=Mock())
        self.assertTrue(rows[0]['automatic_checks']['status'])
        self.assertTrue(rows[1]['automatic_checks']['category'])
        self.assertTrue(rows[1]['automatic_checks']['citation'])
        self.assertIsNone(rows[1]['human_review']['overall'])
