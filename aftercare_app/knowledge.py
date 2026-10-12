"""6.3：登录后检索政策与核对原文；不读订单、不产生业务操作。"""
from flask import Blueprint, current_app, jsonify, render_template, request
from .auth import identity, require_role, error, get_db
from . import model_usage
from .model_qa import transport
from .pages import page_role
from .answers import answer, FAQ
from .retrieval import METHOD
from .model_qa import model_answer, ContextLimitError

bp = Blueprint('knowledge', __name__)


def index():
    return current_app.extensions['policy_index']


def query_value():
    if set(request.args) - {'q'} or len(request.args.getlist('q')) != 1:
        raise ValueError('请提供唯一的 q 查询参数')
    query = request.args['q'].strip()
    if not 2 <= len(query) <= 200:
        raise ValueError('请输入2—200个字符的问题')
    return query


@bp.get('/api/knowledge/search')
@require_role('customer', 'staff')
def search_api():
    try:
        query = query_value()
    except ValueError as exc:
        return error('invalid_input', str(exc), 400)
    return jsonify(data={'query': query, 'items': index().search(query), 'method': METHOD,
                         'document': index().document, 'corpus_sha256': index().digest, 'generated_answer': False})


@bp.get('/knowledge')
@page_role('customer', 'staff')
def search_page():
    query, results, message, status = '', [], '', 200
    if request.args:
        try:
            query = query_value()
            results = index().search(query)
        except ValueError as exc:
            message, status = str(exc), 400
    return render_template('business.html', user=identity(), view='knowledge', title='政策检索',
                           query=query, results=results, message=message, document=index().document), status


@bp.get('/knowledge/sources/<section_id>')
@page_role('customer', 'staff')
def source(section_id):
    chunk = next((c for c in index().chunks if c['id'] == section_id), None)
    if chunk is None:
        return render_template('business.html', user=identity(), view='error', title='条款不存在', message='未找到该政策条款。'), 404
    return render_template('business.html', user=identity(), view='source', title='政策原文', chunk=chunk, document=index().document)


@bp.get('/api/knowledge/answer')
@require_role('customer', 'staff')
def answer_api():
    try:
        query = query_value()
    except ValueError as exc:
        return error('invalid_input', str(exc), 400)
    return jsonify(data=answer(index(), query))


@bp.get('/knowledge/ask')
@page_role('customer', 'staff')
def answer_page():
    query, result, message, status = '', None, '', 200
    if request.args:
        try:
            query = query_value()
            result = answer(index(), query)
        except ValueError as exc:
            message, status = str(exc), 400
    return render_template('business.html', user=identity(), view='answer', title='政策问答基线',
                           query=query, result=result, message=message, examples=list(FAQ)), status


@bp.post('/api/knowledge/model-answer')
@require_role('customer', 'staff')
def model_answer_api():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'q'} or not isinstance(data['q'], str) or not 2 <= len(data['q'].strip()) <= 200:
        return error('invalid_input', '请提供2—200个字符的问题', 400)
    call_id = None
    db = get_db()
    def metered_send(key, payload):
        nonlocal call_id
        call_id = model_usage.reserve(db, identity()['id'], request.remote_addr or 'unknown', payload['model'])
        return transport(key, payload)
    result = {'status':'unknown', 'reason':'interrupted', 'usage':None}
    try:
        result = model_answer(index(), data['q'].strip(), current_app.config['DEEPSEEK_API_KEY'], current_app.config['DEEPSEEK_MODEL'], send=metered_send,
                              context_strategy=current_app.config['QA_CONTEXT_STRATEGY'])
    except ContextLimitError:
        return error('context_limit', '政策资料已超出当前问答容量，请使用政策检索或联系维护者调整配置。本次未调用模型。', 503)
    except model_usage.UsageBlocked as exc:
        return error('model_limit', str(exc), 429)
    finally:
        if call_id:
            model_usage.finish(db, call_id, result)
    result['local_request_id'] = call_id
    return jsonify(data=result)


@bp.get('/knowledge/usage')
@page_role('customer', 'staff')
def usage_page():
    return render_template('business.html', user=identity(), view='model_usage', title='模型调用记录',
                           calls=model_usage.recent(get_db(), identity()))
