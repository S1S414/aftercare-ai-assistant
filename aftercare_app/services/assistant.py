"""8.2 Local draft workflow; no model calls and no automatic submission."""
from uuid import uuid4
from ..db import transaction
from .tickets import authorize, text_field, now, BusinessError, _create_ticket_in_transaction


def _owned_order(db, actor, order_id):
    if type(order_id) is not int or order_id < 1:
        raise BusinessError('invalid_input', '订单编号必须为正整数')
    if not db.execute('SELECT id FROM orders WHERE id=? AND user_id=?', (order_id, actor)).fetchone():
        raise BusinessError('not_found', '订单不存在或不可访问', 404)


def get_task(db, actor, task_id):
    authorize(db, actor, 'customer')
    row = db.execute('SELECT * FROM assistant_tasks WHERE id=? AND user_id=?', (task_id, actor)).fetchone()
    if row is None:
        raise BusinessError('not_found', '任务不存在或不可访问', 404)
    result = dict(row)
    result.pop('request_key')
    return result


def _event(db, actor, task_id, action, version):
    db.execute('INSERT INTO assistant_events(task_id,actor_id,action,version,created_at) VALUES (?,?,?,?,?)',
               (task_id, actor, action, version, now()))


def create_draft(db, actor, order_id, description):
    description = text_field(description, '问题描述')
    # Conservative baseline: preserve the user's words; classification is user-editable.
    with transaction(db):
        authorize(db, actor, 'customer')
        _owned_order(db, actor, order_id)
        task_id, key, stamp = str(uuid4()), str(uuid4()), now()
        db.execute("INSERT INTO assistant_tasks(id,user_id,order_id,category,description,request_key,created_at,updated_at) VALUES (?,?,?,'other',?,?,?,?)",
                   (task_id, actor, order_id, description, key, stamp, stamp))
        _event(db, actor, task_id, 'created', 1)
        return get_task(db, actor, task_id)


def _version(task, version):
    if type(version) is not int or version < 1:
        raise BusinessError('invalid_input', '版本号必须为正整数')
    if version != task['version']:
        raise BusinessError('version_conflict', '草稿已修改，请重新查看并确认', 409)


def _draft(task):
    if task['state'] != 'draft':
        raise BusinessError('state_conflict', '任务已结束，不能修改或执行', 409)


def edit_draft(db, actor, task_id, version, category, description):
    if not isinstance(category, str) or category not in ('delivery','product','return_query','other'):
        raise BusinessError('invalid_input', '问题类型无效')
    description = text_field(description, '问题描述')
    with transaction(db):
        task = get_task(db, actor, task_id)
        _version(task, version)
        _draft(task)
        _owned_order(db, actor, task['order_id'])
        db.execute('UPDATE assistant_tasks SET category=?,description=?,version=version+1,updated_at=? WHERE id=?',
                   (category, description, now(), task_id))
        _event(db, actor, task_id, 'edited', version + 1)
        return get_task(db, actor, task_id)


def cancel_task(db, actor, task_id, version):
    with transaction(db):
        task = get_task(db, actor, task_id)
        _version(task, version)
        if task['state'] == 'cancelled':
            return task
        _draft(task)
        db.execute("UPDATE assistant_tasks SET state='cancelled',updated_at=? WHERE id=?", (now(), task_id))
        _event(db, actor, task_id, 'cancelled', version)
        return get_task(db, actor, task_id)


def confirm_task(db, actor, task_id, version):
    with transaction(db):
        task = get_task(db, actor, task_id)
        _version(task, version)
        _owned_order(db, actor, task['order_id'])
        if task['state'] == 'completed':
            return task
        _draft(task)
        key = db.execute('SELECT request_key FROM assistant_tasks WHERE id=?', (task_id,)).fetchone()[0]
        ticket_id, _ = _create_ticket_in_transaction(db, actor, {
            'order_id': task['order_id'], 'category': task['category'],
            'description': task['description'], 'request_key': key})
        db.execute("UPDATE assistant_tasks SET state='completed',ticket_id=?,updated_at=? WHERE id=?",
                   (ticket_id, now(), task_id))
        _event(db, actor, task_id, 'completed', version)
        return get_task(db, actor, task_id)
