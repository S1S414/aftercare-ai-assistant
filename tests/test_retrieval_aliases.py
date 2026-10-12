import unittest
from pathlib import Path
from aftercare_app.retrieval import PolicyIndex, expand_query


class AliasTests(unittest.TestCase):
    def setUp(self):
        self.index = PolicyIndex(Path(__file__).resolve().parents[1] / 'data/policies.json')

    def test_original_failure_and_variants(self):
        self.assertEqual(self.index.search('东西坏掉了要找谁？', expand=False), [])
        for question in ('东西坏掉了要找谁？', '收到的东西碎了', '商品裂了怎么处理'):
            self.assertEqual(self.index.search(question)[0]['id'], 'product-damage')

    def test_scoped_expansion(self):
        for question in ('心情坏了', '天气坏了', '火星宇宙飞船'):
            self.assertEqual(expand_query(question).strip(), question)
        self.assertEqual(self.index.search('火星宇宙飞船'), [])

    def test_original_source_preserved(self):
        result = self.index.search('东西坏掉了要找谁')[0]
        source = next(c for c in self.index.chunks if c['id'] == result['id'])
        self.assertEqual(result['text'], source['text'])
        self.assertEqual(result['version'], self.index.document['version'])
