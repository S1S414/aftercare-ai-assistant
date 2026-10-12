"""7.4：可复现的开发题集报告，不是独立测试集或LLM评审。"""
import hashlib
import json
from pathlib import Path
from aftercare_app.retrieval import PolicyIndex
from aftercare_app.answers import answer

ROOT = Path(__file__).resolve().parent


def evaluate():
    index = PolicyIndex(ROOT / 'data/policies.json')
    raw = (ROOT / 'data/qa-eval.json').read_bytes()
    cases = json.loads(raw)
    rows = []
    for case in cases:
        result = answer(index, case['question'])
        ids = [c['id'] for c in result['citations']]
        passed = result['status'] == case['expected'] and (case['source'] is None or case['source'] in ids)
        rows.append({**case, 'actual': result['status'], 'passed': passed,
                     'retrieval_hit_at_3': case['source'] in [c['id'] for c in result['related']] if case['source'] else None,
                     'citations': ids})
    positive = [r for r in rows if r['source']]
    negative = [r for r in rows if not r['source']]
    return {'dataset': 'development-only', 'dataset_sha256': hashlib.sha256(raw).hexdigest(),
            'corpus_sha256': index.digest, 'total': len(rows), 'passed': sum(r['passed'] for r in rows),
            'retrieval_hits_at_3': sum(r['retrieval_hit_at_3'] for r in positive), 'answerable_count': len(positive),
            'correct_abstentions': sum(r['actual']=='abstained' for r in negative), 'unanswerable_count': len(negative),
            'cases': rows}


if __name__ == '__main__':
    report = evaluate()
    destination = ROOT / 'docs/01-项目说明与验收记录/qa-evaluation.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"{report['passed']}/{report['total']} development cases passed; report: {destination}")
