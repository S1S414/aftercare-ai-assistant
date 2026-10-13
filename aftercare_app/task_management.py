"""Customer draft management; destructive actions require explicit confirmation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Blueprint, request, jsonify, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature
from .auth import get_db, identity, require_role, error
from .db import transaction
from .services.assistant import get_task, _version
from .services.tickets import BusinessError

bp = Blueprint('task_management', __name__)


@bp.errorhandler(BusinessError)
def failed(exc):
    return error(exc.code, exc.message, exc.status)


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def beijing(value):
    parsed = stamp(value)
    return parsed.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S') if parsed else '时间未知'


def cancelled_at(db, task):
    rows = db.execute("SELECT created_at FROM assistant_events WHERE task_id=? AND action='cancelled'", (task['id'],)).fetchall()
    if len(rows) != 1:
        return None
    cancelled = stamp(rows[0]['created_at'])
    created = stamp(task['created_at'])
    return cancelled if cancelled and created and cancelled >= created else None


def eligible(db, task, cutoff):
    cancelled = cancelled_at(db, task)
    return task['state'] == 'cancelled' and task['ticket_id'] is None and cancelled and cancelled < cutoff


def grouped(db, actor):
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    groups = {'cancelled': [], 'draft': []}
    for row in db.execute("SELECT t.*,o.order_no FROM assistant_tasks t JOIN orders o ON o.id=t.order_id WHERE t.user_id=? AND t.state IN ('draft','cancelled') AND t.ticket_id IS NULL ORDER BY t.updated_at,t.id", (actor,)):
        task = dict(row)
        old = eligible(db, task, cutoff) if task['state'] == 'cancelled' else stamp(task['updated_at']) and stamp(task['updated_at']) < cutoff
        if old:
            groups[task['state']].append({**task, 'display_time': beijing(task['updated_at'])})
    return groups


def remove(db, task):
    if task['state'] not in ('draft', 'cancelled') or task['ticket_id'] is not None:
        raise BusinessError('state_conflict', '已建单任务不能删除', 409)
    db.execute('DELETE FROM assistant_events WHERE task_id=?', (task['id'],))
    db.execute('DELETE FROM assistant_tasks WHERE id=?', (task['id'],))


def listing(db, actor, args):
    try:
        if set(args) - {'page', 'order', 'state'} or any(len(args.getlist(k)) != 1 for k in args):
            raise ValueError()
        page = int(args.get('page', '1'))
        order = int(args.get('order', '0'))
        state = args.get('state', '')
        if page < 1 or order < 0 or state not in ('', 'draft', 'cancelled', 'completed'):
            raise ValueError()
    except ValueError:
        raise BusinessError('invalid_input', '筛选参数无效', 400)
    where, values = 't.user_id=?', [actor]
    if order:
        where += ' AND t.order_id=?'
        values.append(order)
    if state:
        where += ' AND t.state=?'
        values.append(state)
    total = db.execute('SELECT count(*) FROM assistant_tasks t WHERE ' + where, values).fetchone()[0]
    pages = max(1, (total + 9) // 10)
    page = min(page, pages)
    rows = db.execute('SELECT t.*,o.order_no FROM assistant_tasks t JOIN orders o ON o.id=t.order_id WHERE ' + where + ' ORDER BY t.created_at DESC,t.id DESC LIMIT 10 OFFSET ?', values + [(page-1)*10]).fetchall()
    tasks = [{**dict(r), 'display_time': beijing(r['created_at'])} for r in rows]
    size = Path(db.execute('PRAGMA database_list').fetchone()[2]).stat().st_size
    free = db.execute('PRAGMA freelist_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
    return dict(tasks=tasks, task_page=page, task_pages=pages, task_total=total, filter_order=order, filter_state=state,
                database_kib=round(size/1024, 1), reusable_kib=round(free/1024, 1), cleanup_groups=grouped(db, actor))


@bp.post('/api/assistant/cleanup/selected')
@require_role('customer')
def delete_selected():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'items', 'confirmed'} or data['confirmed'] is not True or not isinstance(data['items'], list) or not 1 <= len(data['items']) <= 100:
        raise BusinessError('invalid_input', '请选择1至100条并确认')
    if any(not isinstance(x, dict) or set(x) != {'id','version'} or not isinstance(x['id'],str) for x in data['items']):
        raise BusinessError('invalid_input', '选择格式无效')
    if len({x['id'] for x in data['items']}) != len(data['items']):
        raise BusinessError('invalid_input', '记录重复')
    db, actor = get_db(), identity()['id']
    with transaction(db):
        allowed = {t['id'] for rows in grouped(db, actor).values() for t in rows}
        checked = []
        for item in data['items']:
            task = get_task(db, actor, item['id'])
            _version(task, item['version'])
            if task['id'] not in allowed:
                raise BusinessError('state_conflict', '记录已变化或未满足7天条件，请刷新', 409)
            checked.append(task)
        for task in checked:
            remove(db, task)
    return jsonify(data={'deleted':len(checked)})


@bp.delete('/api/assistant/tasks/<task_id>')
@require_role('customer')
def delete(task_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'version', 'confirmed'} or data['confirmed'] is not True:
        raise BusinessError('invalid_input', '请明确确认删除')
    db = get_db()
    with transaction(db):
        task = get_task(db, identity()['id'], task_id)
        _version(task, data['version'])
        remove(db, task)
    return jsonify(data={'deleted': 1})


def signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='draft-cleanup-v1')


@bp.post('/api/assistant/cleanup/preview')
@require_role('customer')
def preview():
    db, actor = get_db(), identity()['id']
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    candidates = db.execute("SELECT t.*,o.order_no FROM assistant_tasks t JOIN orders o ON o.id=t.order_id WHERE t.user_id=? AND t.state='cancelled' ORDER BY t.created_at,t.id", (actor,)).fetchall()
    rows = []
    for row in candidates:
        task = dict(row)
        if eligible(db, task, cutoff):
            rows.append({'id': task['id'], 'version': task['version'], 'order': task['order_no'],
                         'summary': task['description'][:80], 'cancelled_at': beijing(cancelled_at(db, task).isoformat())})
        if len(rows) == 100:
            break
    token = signer().dumps({'actor': actor, 'items': [[r['id'], r['version']] for r in rows]})
    return jsonify(data={'rows': rows, 'token': token})


@bp.post('/api/assistant/cleanup/confirm')
@require_role('customer')
def cleanup():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'token', 'confirmed'} or data['confirmed'] is not True or not isinstance(data['token'], str):
        raise BusinessError('invalid_input', '请先预览并确认')
    try:
        payload = signer().loads(data['token'], max_age=600)
    except BadSignature:
        raise BusinessError('invalid_input', '预览已失效，请重新预览', 409)
    actor, db = identity()['id'], get_db()
    if payload['actor'] != actor:
        raise BusinessError('forbidden', '预览不属于当前用户', 403)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    with transaction(db):
        checked = []
        for task_id, version in payload['items']:
            task = get_task(db, actor, task_id)
            _version(task, version)
            if not eligible(db, task, cutoff):
                raise BusinessError('state_conflict', '记录已变化，请重新预览', 409)
            checked.append(task)
        for task in checked:
            remove(db, task)
    return jsonify(data={'deleted': len(checked)})
