import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from aftercare_app.retrieval import PolicyIndex
from aftercare_app.model_qa import model_answer


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.index=PolicyIndex(Path(__file__).resolve().parents[1]/'data/policies.json')

    def response(self, data, finish='stop'):
        return {'choices':[{'finish_reason':finish,'message':{'content':json.dumps(data)}}],
                'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}

    def test_valid_and_payload(self):
        send=Mock(return_value=self.response({'answerable':True,'answer':'可提交商品问题工单。','citations':['product-damage']}))
        result=model_answer(self.index,'商品破损怎么办','test-only',send=send)
        self.assertEqual(result['status'],'answered')
        self.assertEqual(result['usage']['total_tokens'],120)
        payload=send.call_args.args[1]
        self.assertEqual(payload['thinking'],{'type':'disabled'})
        self.assertEqual(payload['max_tokens'],800)
        self.assertNotIn('test-only',json.dumps(result))

    def test_missing_key_or_evidence_no_call(self):
        send=Mock()
        self.assertEqual(model_answer(self.index,'商品破损','',send=send)['reason'],'not_configured')
        self.assertEqual(model_answer(self.index,'火星宇宙飞船','test',send=send)['reason'],'no_evidence')
        send.assert_not_called()

    def test_invalid_citations_and_schema(self):
        for data in [{'answerable':True,'answer':'退款已到账','citations':['invented']},
                     {'answerable':True,'answer':'退款已到账','citations':[]},
                     {'answerable':'true','answer':'abc','citations':['product-damage']},
                     {'answerable':False,'answer':'已退款','citations':[]}]:
            result=model_answer(self.index,'商品破损','test',send=lambda *args:self.response(data))
            self.assertEqual(result['status'],'unavailable')
            self.assertFalse(result['generated_answer'])

    def test_refusal(self):
        result=model_answer(self.index,'退款多少钱','test',send=lambda *args:self.response({'answerable':False,'answer':'','citations':[]}))
        self.assertEqual(result['status'],'abstained')

    def test_http_errors_are_distinguished_without_leaking_body(self):
        from urllib.error import HTTPError
        for code in (401,402,429,500):
            send=Mock(side_effect=HTTPError('https://api.deepseek.com/chat/completions',code,'private-error',{},None))
            result=model_answer(self.index,'商品破损','test',send=send)
            self.assertEqual(result['reason'],'provider_http_'+str(code))
            self.assertIn(str(code),result['answer'])
            self.assertNotIn('private-error',json.dumps(result))

    def test_truncation_and_timeout(self):
        for send in [Mock(side_effect=TimeoutError('secret-provider-error')),
                     Mock(return_value=self.response({},'length')),
                     Mock(return_value={'choices':[]})]:
            result=model_answer(self.index,'商品破损','test',send=send)
            self.assertEqual(result['status'],'unavailable')
            self.assertNotIn('secret-provider-error',json.dumps(result))
            self.assertIn('elapsed_ms',result)
