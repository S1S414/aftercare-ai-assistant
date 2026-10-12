"""阶段4：订单查询、工单查询与操作接口。"""
from flask import Blueprint, jsonify, request
from .auth import error, get_db, identity, require_role
from .services.tickets import BusinessError, create_ticket, claim_ticket, close_ticket

bp=Blueprint('business',__name__)


@bp.errorhandler(BusinessError)
def business_error(exc):
    return error(exc.code,exc.message,exc.status)


def paging(allowed=()):
    if set(request.args) - {'page','page_size',*allowed} or any(len(request.args.getlist(k)) != 1 for k in request.args):
        raise BusinessError('invalid_input','查询参数无效')
    try:
        page=int(request.args.get('page','1'))
        size=int(request.args.get('page_size','20'))
        if not 1 <= page <= 1000000 or not 1 <= size <= 100:
            raise ValueError()
    except ValueError:
        raise BusinessError('invalid_input','分页参数无效') from None
    return page,size


def listing(table,where,params,page,size):
    # table/where are developer-controlled, values remain parameterized.
    db=get_db()
    total=db.execute(f'SELECT count(*) FROM {table} WHERE {where}',params).fetchone()[0]
    rows=db.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(*params,size,(page-1)*size)).fetchall()
    items=[dict(row) for row in rows]
    for item in items:
        item.pop('request_key',None)
    return jsonify(data={'items':items,'page':page,'page_size':size,'total':total})


@bp.get('/api/orders')
@require_role('customer')
def orders():
    page,size=paging()
    return listing('orders','user_id=?',(identity()['id'],),page,size)


@bp.get('/api/orders/<int:order_id>')
@require_role('customer')
def order_detail(order_id):
    row=get_db().execute('SELECT * FROM orders WHERE id=? AND user_id=?',(order_id,identity()['id'])).fetchone()
    if not row:
        raise BusinessError('not_found','订单不存在或不可访问',404)
    return jsonify(data=dict(row))


def ticket_data(ticket_id):
    user=identity()
    clause='id=?' if user['role']=='staff' else 'id=? AND requester_id=?'
    args=(ticket_id,) if user['role']=='staff' else (ticket_id,user['id'])
    db=get_db()
    row=db.execute('SELECT * FROM tickets WHERE '+clause,args).fetchone()
    if not row:
        raise BusinessError('not_found','工单不存在或不可访问',404)
    result=dict(row)
    result.pop('request_key',None)
    result['order']=dict(db.execute('SELECT id,order_no,product_name,delivery_status,expected_delivery_at,delivered_at FROM orders WHERE id=?',(row['order_id'],)).fetchone())
    result['events']=[dict(r) for r in db.execute('SELECT id,actor_id,event_type,from_status,to_status,note,created_at FROM ticket_events WHERE ticket_id=? ORDER BY id',(ticket_id,))]
    return result


@bp.get('/api/tickets/<int:ticket_id>')
@require_role('customer','staff')
def detail(ticket_id):
    return jsonify(data=ticket_data(ticket_id))


def ticket_listing(staff=False):
    page,size=paging(('status','mine') if staff else ('status',))
    where=['1=1'] if staff else ['requester_id=?']
    params=[] if staff else [identity()['id']]
    if 'status' in request.args:
        status=request.args['status']
        if status not in ('pending','in_progress','closed'):
            raise BusinessError('invalid_input','工单状态无效')
        where.append('status=?'); params.append(status)
    if staff and 'mine' in request.args:
        if request.args['mine'] not in ('true','false'):
            raise BusinessError('invalid_input','mine须为true或false')
        if request.args['mine']=='true':
            where.append('assignee_id=?'); params.append(identity()['id'])
    return listing('tickets',' AND '.join(where),tuple(params),page,size)


@bp.get('/api/tickets')
@require_role('customer')
def tickets():
    return ticket_listing()


@bp.get('/api/staff/tickets')
@require_role('staff')
def staff_tickets():
    return ticket_listing(staff=True)


@bp.post('/api/tickets')
@require_role('customer')
def create():
    ticket_id,replayed=create_ticket(get_db(),identity()['id'],request.get_json(silent=True))
    return jsonify(data={'ticket':ticket_data(ticket_id),'replayed':replayed}),200 if replayed else 201


@bp.post('/api/staff/tickets/<int:ticket_id>/claim')
@require_role('staff')
def claim(ticket_id):
    if request.get_data() and request.get_json(silent=True) != {}:
        raise BusinessError('invalid_input','接单请求不接受额外字段')
    claim_ticket(get_db(),identity()['id'],ticket_id)
    return jsonify(data=ticket_data(ticket_id))


@bp.post('/api/staff/tickets/<int:ticket_id>/close')
@require_role('staff')
def close(ticket_id):
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or set(body) != {'resolution'}:
        raise BusinessError('invalid_input','需要且仅接受处理结果resolution')
    close_ticket(get_db(),identity()['id'],ticket_id,body['resolution'])
    return jsonify(data=ticket_data(ticket_id))
