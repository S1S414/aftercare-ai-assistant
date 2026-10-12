"""7.5.6.5：离线检索对照；显式--live时运行6题真实模型评测。"""
import argparse
import getpass
import hashlib
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from aftercare_app.retrieval import PolicyIndex, METHOD
from aftercare_app.answers import answer
from aftercare_app.model_qa import model_answer, transport
from aftercare_app import model_usage
from aftercare_app.db import connect_database

ROOT = Path(__file__).resolve().parent


def load_cases():
    cases, hashes = [], {}
    for name in ('qa-eval.json', 'qa-next-round.json'):
        raw = (ROOT / 'data' / name).read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        cases.extend({**c, 'dataset': name} for c in json.loads(raw))
    return cases, hashes


def retrieval_comparison(index, cases):
    rows = []
    for case in cases:
        before = index.search(case['question'], expand=False)
        after = index.search(case['question'])
        rows.append({**case, 'v1_sources': [c['id'] for c in before],
                     'v2_sources': [c['id'] for c in after],
                     'v1_hit': case['source'] in [c['id'] for c in before] if case['source'] else None,
                     'v2_hit': case['source'] in [c['id'] for c in after] if case['source'] else None,
                     'faq_baseline': answer(index, case['question'])})
    return rows


def run_live(index, rows, db, user_id, key, save, send=transport, wait=time.sleep, context_strategy='top3', case_ids=None):
    """仅下一轮6题；任何失败/限流立即停止，不自动重试。"""
    selected = [r for r in rows if r['dataset'] == 'qa-next-round.json' and (case_ids is None or r['id'] in case_ids)]
    for number, row in enumerate(selected):
        if number:
            wait(13)
        request_id = None
        result = {'status': 'unknown', 'reason': 'interrupted', 'usage': None}
        def metered(secret, payload):
            nonlocal request_id
            request_id = model_usage.reserve(db, user_id, 'local-evaluation-cli', payload['model'],
                                             endpoint='cli:evaluate_suite')
            return send(secret, payload)
        try:
            result = model_answer(index, row['question'], key, send=metered, context_strategy=context_strategy)
        except model_usage.UsageBlocked as exc:
            row['blocked'] = str(exc)
            save()
            break
        finally:
            if request_id:
                model_usage.finish(db, request_id, result)
        row['model_result'] = result
        row['local_request_id'] = request_id
        row['structural_expectation_met'] = (
            result['status'] == 'answered' and row['source'] in [c['id'] for c in result['citations']]
            if row['source'] else result['status'] == 'abstained')
        row['human_review'] = 'pending: verify answer against source and check field'
        save()
        print(row['id'], result['status'], flush=True)
        if result['status'] in ('unavailable', 'unknown'):
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='最多6次付费调用；隐藏输入密钥，沿用项目限额')
    parser.add_argument('--staff', default='demo_staff_a')
    parser.add_argument('--context', choices=('top3','all-small'), default='top3')
    parser.add_argument('--cases', nargs='+', choices=tuple('new0'+str(i) for i in range(1,7)))
    args = parser.parse_args()
    selected_ids = list(dict.fromkeys(args.cases)) if args.cases else ['new0'+str(i) for i in range(1,7)]
    index = PolicyIndex(ROOT / 'data/policies.json')
    cases, hashes = load_cases()
    rows = retrieval_comparison(index, cases)
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'mode': 'live' if args.live else 'offline',
              'method': METHOD, 'context_strategy': args.context, 'selected_cases': args.cases,
              'dataset_hashes': hashes, 'corpus_sha256': index.digest,
              'note': 'Developer-authored cases; retrieval hits and schema checks are not answer accuracy. Human review required.',
              'rows': rows}
    output = ROOT / 'instance' / 'evaluations'
    output.mkdir(parents=True, exist_ok=True)
    path = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    def save():
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    save()
    print('Report:', path, flush=True)
    if not args.live:
        return
    print('Live cases: ' + ', '.join(selected_ids) + '; context: ' + args.context + '; maximum calls: ' + str(len(selected_ids)), flush=True)
    db = connect_database(ROOT / 'instance' / 'aftercare.sqlite3')
    try:
        user = db.execute("SELECT id FROM users WHERE username=? AND role='staff'", (args.staff,)).fetchone()
        if user is None:
            raise SystemExit('未找到指定的本地客服账号。')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('DeepSeek API Key (hidden input; at most ' + str(len(selected_ids)) + ' calls): ').strip()
        if not key:
            raise SystemExit('密钥为空，未调用模型。')
        run_live(index, rows, db, user['id'], key, save, context_strategy=args.context, case_ids=args.cases)
    finally:
        db.close()


if __name__ == '__main__':
    main()
