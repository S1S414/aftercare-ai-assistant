import json
import unittest
from unittest.mock import Mock
from evaluate_suite import ROOT
from aftercare_app.retrieval import PolicyIndex
from aftercare_app.model_qa import context_sources, model_answer


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.index=PolicyIndex(ROOT/'data/policies.json')

    def test_missing_sources_available_in_full_context(self):
        for q, target in [('客服把售后单结了，钱就会自动到账对吧？','ticket-progress'),
                          ('另一个客服已经接手了，我能替他关单吗？','ticket-close')]:
            self.assertNotIn(target,[c['id'] for c in context_sources(self.index,q)])
            self.assertIn(target,[c['id'] for c in context_sources(self.index,q,'all-small')])

    def test_full_context_bound(self):
        self.index.chunks=self.index.chunks*2
        with self.assertRaises(ValueError): context_sources(self.index,'test','all-small')

    def test_full_context_payload_and_citation_validation(self):
        response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'answerable':True,'answer':'关闭不等于退款。','citations':['ticket-progress']})}}]}
        send=Mock(return_value=response)
        result=model_answer(self.index,'售后单结了会到账吗','synthetic',send=send,context_strategy='all-small')
        self.assertEqual(result['status'],'answered')
        self.assertEqual(len(json.loads(send.call_args.args[1]['messages'][1]['content'])['sources']),6)
        self.assertEqual(result['context_strategy'],'all-small')
