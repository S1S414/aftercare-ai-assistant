"""6.1—6.2：按条款分块的中文双字词TF-IDF基线，无外部请求。"""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

METHOD = 'tfidf-char-bigram-alias-v2'
# 人工维护的领域别名，仅扩展检索词，不改写政策或决定是否可以回答。
ALIASES = (
    (('东西', '商品', '货物', '收到'), ('坏掉', '坏了', '碎了', '裂了'), '商品破损'),
    (('包裹', '快递', '货物'), ('没到', '没收到', '迟迟不到'), '配送未收到货'),
    (('售后单',), ('进度', '处理情况', '哪里看', '哪看'), '工单进度'),
)


def expand_query(query):
    additions = [target for subjects, descriptions, target in ALIASES
                 if any(word in query for word in subjects) and any(word in query for word in descriptions)]
    return query + ' ' + ' '.join(additions)


def terms(text):
    result = []
    for run in re.findall(r'[\u4e00-\u9fff]+|[a-z0-9]+', text.lower()):
        if re.fullmatch(r'[a-z0-9]+', run):
            result.append(run)
        elif len(run) > 1:
            result.extend(run[i:i + 2] for i in range(len(run) - 1))
    return Counter(result)


class PolicyIndex:
    def __init__(self, path):
        raw = Path(path).read_bytes()
        doc = json.loads(raw)
        self.digest = hashlib.sha256(raw).hexdigest()
        self.document = {k: doc[k] for k in ('document_id', 'title', 'version', 'notice')}
        self.chunks = []
        seen = set()
        for section in doc['sections']:
            if section['id'] in seen or not re.fullmatch(r'[a-z0-9-]+', section['id']):
                raise ValueError('政策条款编号重复或格式错误')
            seen.add(section['id'])
            if not section['text'].strip():
                raise ValueError('政策条款不能为空')
            self.chunks.append(dict(section))
        self.counts = [terms(c['title'] + ' ' + c['text']) for c in self.chunks]
        df = Counter(t for count in self.counts for t in count)
        self.idf = {t: math.log((1 + len(self.chunks)) / (1 + n)) + 1 for t, n in df.items()}

    def search(self, query, limit=3, expand=True):
        if expand:
            query = expand_query(query)
        weights = {t: n * self.idf[t] for t, n in terms(query).items() if t in self.idf}
        qnorm = math.sqrt(sum(v * v for v in weights.values()))
        results = []
        if not qnorm:
            return results
        for chunk, count in zip(self.chunks, self.counts):
            dnorm = math.sqrt(sum((n * self.idf[t]) ** 2 for t, n in count.items()))
            score = sum(w * count[t] * self.idf[t] for t, w in weights.items()) / (qnorm * dnorm)
            if score > 0:
                results.append({**chunk, 'score': round(score, 6), 'source_url': '/knowledge/sources/' + chunk['id'],
                                'version': self.document['version'], 'document_id': self.document['document_id']})
        return sorted(results, key=lambda item: (-item['score'], item['id']))[:limit]
