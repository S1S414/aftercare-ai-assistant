"""8.3 Customer-only local draft workflow."""
from flask import Blueprint, jsonify, render_template, request, current_app
from . import model_usage
from .draft_model import suggest
from .model_qa import transport
from .auth import get_db, identity, require_role, error
from .pages import page_role
from .services import assistant as service
from .services.tickets import BusinessError
from .task_management import listing

bp = Blueprint('assistant', __name__)


@bp.errorhandler(BusinessError)
def failed(exc):
    return error(exc.code, exc.message, exc.status)


def body(fields):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != set(fields):
        raise BusinessError('invalid_input', '请求字段不完整或包含多余字段')
    return data


@bp.get('/assistant')
@page_role('customer')
def page():
    db, user = get_db(), identity()
    orders = db.execute('SELECT id,order_no,product_name FROM orders WHERE user_id=? ORDER BY id DESC', (user['id'],)).fetchall()
    return render_template('assistant.html', user=user, orders=orders, **listing(db, user['id'], request.args))


@bp.post('/api/assistant/tasks')
@require_role('customer')
def create():
    data = body(('order_id', 'description'))
    return jsonify(data=service.create_draft(get_db(), identity()['id'], data['order_id'], data['description'])), 201


@bp.get('/api/assistant/tasks/<task_id>')
@require_role('customer')
def detail(task_id):
    return jsonify(data=service.get_task(get_db(), identity()['id'], task_id))


@bp.patch('/api/assistant/tasks/<task_id>')
@require_role('customer')
def edit(task_id):
    data = body(('version', 'category', 'description'))
    return jsonify(data=service.edit_draft(get_db(), identity()['id'], task_id, **data))


@bp.post('/api/assistant/tasks/<task_id>/confirm')
@require_role('customer')
def confirm(task_id):
    data = body(('version',))
    return jsonify(data=service.confirm_task(get_db(), identity()['id'], task_id, data['version']))


@bp.post('/api/assistant/tasks/<task_id>/cancel')
@require_role('customer')
def cancel(task_id):
    data = body(('version',))
    return jsonify(data=service.cancel_task(get_db(), identity()['id'], task_id, data['version']))


@bp.post('/api/assistant/tasks/<task_id>/suggest')
@require_role('customer')
def suggestion(task_id):
    data = body(('version',))
    db, actor = get_db(), identity()['id']
    task = service.get_task(db, actor, task_id)
    service._version(task, data['version'])
    service._draft(task)
    if current_app.config.get('PUBLIC_DEMO'):
        from .public_demo import simulated_suggestion
        return jsonify(data={**simulated_suggestion(current_app.extensions['policy_index'], task['description']),
                             'version':task['version'], 'local_request_id':None})
    call_id = None
    result = {'status':'unknown','reason':'interrupted','usage':None}
    def send(key, payload):
        nonlocal call_id
        call_id = model_usage.reserve(db, actor, request.remote_addr or 'unknown', payload['model'],
                                      endpoint='/api/assistant/tasks/suggest')
        return transport(key,payload)
    try:
        result = suggest(current_app.extensions['policy_index'],task['description'],
                         current_app.config['DEEPSEEK_API_KEY'],current_app.config['DEEPSEEK_MODEL'],send)
    except model_usage.UsageBlocked as exc:
        return error('model_limit',str(exc),429)
    finally:
        if call_id: model_usage.finish(db,call_id,result)
    # Read again: another tab may have edited/cancelled while the model was running.
    latest = service.get_task(db,actor,task_id)
    if latest['version'] != task['version'] or latest['state'] != 'draft':
        return error('version_conflict','草稿已变化，未应用模型建议；本次模型调用可能已计费，请刷新查看。',409)
    return jsonify(data={**result,'version':task['version'],'local_request_id':call_id})
