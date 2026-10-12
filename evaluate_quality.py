"""7/8集中评测：默认只预览题目；--live最多6次付费请求，无自动重试。"""
import argparse
import getpass
import hashlib
import json
import time
import warnings
from datetime import datetime, timezone
from uuid import uuid4
from evaluate_suite import ROOT
from aftercare_app.db import connect_database
from aftercare_app.retrieval import PolicyIndex
from aftercare_app.model_qa import model_answer, transport
from aftercare_app.draft_model import suggest
from aftercare_app import model_usage


def run(cases, index, db, actor, key, save, send=transport, wait=time.sleep):
    for number, row in enumerate(cases):
        if number: wait(13)
        rid = None
        result = {'status':'unknown','reason':'interrupted','usage':None}
        def metered(secret, payload):
            nonlocal rid
            rid = model_usage.reserve(db,actor,'local-quality-evaluation',payload['model'],endpoint='cli:evaluate_suite')
            return send(secret,payload)
        try:
            if row['kind']=='qa':
                result=model_answer(index,row['input'],key,send=metered,context_strategy='all-small')
            else:
                result=suggest(index,row['input'],key,'deepseek-flash',metered)
        except model_usage.UsageBlocked as exc:
            row['blocked']=str(exc)
            save()
            break
        finally:
            if rid: model_usage.finish(db,rid,result)
        row['result']=result
        row['local_request_id']=rid
        row['automatic_checks']={
            'status':result['status']==row['expected_status'],
            'category':result.get('category')==row['category'] if row.get('category') else None,
            'citation':row['source'] in [c['id'] for c in result.get('citations',[])] if row.get('source') else None}
        row['human_review']={'faithfulness':None,'citation_support':None,'no_false_action':None,'overall':None,'notes':''}
        save()
        print(row['id'],result['status'],flush=True)
        if result['status'] in ('unavailable','unknown'): break


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--cases',nargs='+',choices=('q1','q2','q3','d1','d2','d3'))
    args=parser.parse_args()
    raw=(ROOT/'data/quality-cases.json').read_bytes()
    cases=[c for c in json.loads(raw) if not args.cases or c['id'] in args.cases]
    print('Maximum calls:',len(cases),'(only with --live)')
    for row in cases: print(row['id'],row['kind'],row['input'],row['criteria'])
    if not args.live: return
    # Hidden prompt must fail closed on terminals that cannot disable echo.
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        try: key=getpass.getpass('DeepSeek API Key (hidden input): ').strip()
        except (getpass.GetPassWarning,EOFError,KeyboardInterrupt):
            raise SystemExit('输入已取消或终端无法隐藏密钥，未调用。')
    if not key: raise SystemExit('密钥为空，未调用。')
    index=PolicyIndex(ROOT/'data/policies.json')
    report={'created_at':datetime.now(timezone.utc).isoformat(),'dataset_sha256':hashlib.sha256(raw).hexdigest(),
            'corpus_sha256':index.digest,'model':'deepseek-flash','context':'all-small',
            'note':'Developer-authored regression cases, not a blind evaluation; automatic checks do not prove factual correctness.',
            'rows':cases}
    folder=ROOT/'instance/evaluations'; folder.mkdir(parents=True,exist_ok=True)
    path=folder/('quality-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid4().hex[:8]+'.json')
    def save():
        tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(path)
    save(); print('Report:',path,flush=True)
    db=connect_database(ROOT/'instance/aftercare.sqlite3')
    try:
        user=db.execute("SELECT id FROM users WHERE username='demo_staff_a' AND role='staff'").fetchone()
        if not user: raise SystemExit('未找到本地评测记账账号demo_staff_a，未调用。')
        run(cases,index,db,user['id'],key,save)
    finally: db.close()


if __name__=='__main__': main()
