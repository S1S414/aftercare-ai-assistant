"""4.2—4.3：工单写操作，授权与事务均在服务层执行。"""
from datetime import datetime, timezone
from uuid import UUID
from ..db import transaction


class BusinessError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def authorize(db, actor_id, role):
    user = db.execute('SELECT id,role FROM users WHERE id=?', (actor_id,)).fetchone()
    if not user:
        raise BusinessError('unauthenticated', '请先登录', 401)
    if user['role'] != role:
        raise BusinessError('forbidden', '当前账号没有此操作权限', 403)


def text_field(value, name):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
        raise BusinessError('invalid_input', f'{name}须为1—2000字符的文本')
    if '\x00' in value:
        raise BusinessError('invalid_input', f'{name}不能包含空字符')
    return value.strip()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def event(db, ticket_id, actor_id, kind, before, after, note, timestamp):
    db.execute('INSERT INTO ticket_events(ticket_id,actor_id,event_type,from_status,to_status,note,created_at) VALUES (?,?,?,?,?,?,?)',
               (ticket_id,actor_id,kind,before,after,note,timestamp))


def create_ticket(db, actor_id, data):
    with transaction(db):
        return _create_ticket_in_transaction(db, actor_id, data)


def _create_ticket_in_transaction(db, actor_id, data):
    if not db.in_transaction:
        raise RuntimeError('Active transaction required')
    if not isinstance(data, dict) or set(data) != {'order_id','category','description','request_key'}:
        raise BusinessError('invalid_input','需要订单编号、问题类型、描述和请求标识；不能指定身份或状态')
    if type(data['order_id']) is not int or data['order_id'] < 1:
        raise BusinessError('invalid_input','订单编号必须为正整数')
    if not isinstance(data['category'],str) or data['category'] not in ('delivery','product','return_query','other'):
        raise BusinessError('invalid_input','问题类型无效')
    description = text_field(data['description'],'问题描述')
    try:
        if not isinstance(data['request_key'],str):
            raise ValueError()
        key = str(UUID(data['request_key']))
    except (ValueError, AttributeError):
        raise BusinessError('invalid_input','请求标识必须是UUID') from None
    authorize(db,actor_id,'customer')
    order = db.execute('SELECT id FROM orders WHERE id=? AND user_id=?',(data['order_id'],actor_id)).fetchone()
    if not order:
        raise BusinessError('not_found','订单不存在或不可访问',404)
    previous = db.execute('SELECT * FROM tickets WHERE requester_id=? AND request_key=?',(actor_id,key)).fetchone()
    if previous:
        if (previous['order_id'],previous['category'],previous['description']) != (data['order_id'],data['category'],description):
            raise BusinessError('request_conflict','同一请求标识不能用于不同内容',409)
        return previous['id'], True
    timestamp=now()
    cursor=db.execute('INSERT INTO tickets(order_id,requester_id,category,description,created_at,request_key) VALUES (?,?,?,?,?,?)',
                      (data['order_id'],actor_id,data['category'],description,timestamp,key))
    event(db,cursor.lastrowid,actor_id,'created',None,'pending','用户创建工单',timestamp)
    return cursor.lastrowid, False


def claim_ticket(db, actor_id, ticket_id):
    with transaction(db):
        authorize(db,actor_id,'staff')
        if not db.execute('SELECT id FROM tickets WHERE id=?',(ticket_id,)).fetchone():
            raise BusinessError('not_found','工单不存在',404)
        timestamp=now()
        cursor=db.execute("UPDATE tickets SET status='in_progress',assignee_id=?,claimed_at=? WHERE id=? AND status='pending'",(actor_id,timestamp,ticket_id))
        if cursor.rowcount != 1:
            raise BusinessError('state_conflict','工单已被领取或关闭，请刷新',409)
        event(db,ticket_id,actor_id,'claimed','pending','in_progress','客服领取工单',timestamp)


def close_ticket(db, actor_id, ticket_id, resolution):
    resolution=text_field(resolution,'处理结果')
    with transaction(db):
        authorize(db,actor_id,'staff')
        ticket=db.execute('SELECT * FROM tickets WHERE id=?',(ticket_id,)).fetchone()
        if not ticket:
            raise BusinessError('not_found','工单不存在',404)
        if ticket['status'] != 'in_progress':
            raise BusinessError('state_conflict','仅能关闭处理中的工单',409)
        if ticket['assignee_id'] != actor_id:
            raise BusinessError('forbidden','仅领取客服可以关闭工单',403)
        timestamp=now()
        db.execute("UPDATE tickets SET status='closed',resolution=?,closed_at=? WHERE id=? AND status='in_progress' AND assignee_id=?",(resolution,timestamp,ticket_id,actor_id))
        event(db,ticket_id,actor_id,'closed','in_progress','closed',resolution,timestamp)
