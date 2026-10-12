"""阶段5：页面授权与数据展示；写操作仍走阶段4接口。"""
from functools import wraps
from flask import Blueprint, redirect, render_template, request, abort
from .auth import identity, get_db
from .api import ticket_data, paging
from .services.tickets import BusinessError

bp = Blueprint('pages', __name__)


def page_role(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = identity()
            if not user:
                return redirect('/login')
            if user['role'] not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


@bp.errorhandler(BusinessError)
def business_error(exc):
    return render_template('business.html', user=identity(), view='error', title='无法完成请求', message=exc.message), exc.status


@bp.get('/orders')
@page_role('customer')
def orders():
    page,size=paging()
    db=get_db(); uid=identity()['id']
    total=db.execute('SELECT count(*) FROM orders WHERE user_id=?',(uid,)).fetchone()[0]
    rows=db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(uid,size,(page-1)*size)).fetchall()
    return render_template('business.html',user=identity(),view='orders',title='我的订单',rows=rows,page=page,size=size,total=total)


@bp.get('/orders/<int:order_id>')
@page_role('customer')
def order(order_id):
    row=get_db().execute('SELECT * FROM orders WHERE id=? AND user_id=?',(order_id,identity()['id'])).fetchone()
    if not row:
        raise BusinessError('not_found','订单不存在或不可访问',404)
    return render_template('business.html',user=identity(),view='order',title='订单详情与售后申请',order=row)


@bp.get('/tickets')
@page_role('customer')
def tickets():
    return ticket_list(False)


@bp.get('/staff/tickets')
@page_role('staff')
def staff_tickets():
    return ticket_list(True)


def ticket_list(staff):
    page,size=paging(('status','mine') if staff else ('status',))
    status=request.args.get('status','')
    mine=request.args.get('mine','false')
    if status not in ('','pending','in_progress','closed') or mine not in ('true','false'):
        raise BusinessError('invalid_input','筛选条件无效')
    clauses=['1=1']; args=[]
    if not staff:
        clauses.append('requester_id=?'); args.append(identity()['id'])
    if status:
        clauses.append('status=?'); args.append(status)
    if staff and mine=='true':
        clauses.append('assignee_id=?'); args.append(identity()['id'])
    where=' AND '.join(clauses); db=get_db()
    total=db.execute('SELECT count(*) FROM tickets WHERE '+where,args).fetchone()[0]
    rows=db.execute('SELECT * FROM tickets WHERE '+where+' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(*args,size,(page-1)*size)).fetchall()
    return render_template('business.html',user=identity(),view='tickets',title='客服工作台' if staff else '我的工单',rows=rows,page=page,size=size,total=total,status=status,mine=mine)


@bp.get('/tickets/<int:ticket_id>')
@page_role('customer')
def ticket(ticket_id):
    return render_template('business.html',user=identity(),view='ticket',title='工单详情',ticket=ticket_data(ticket_id))


@bp.get('/staff/tickets/<int:ticket_id>')
@page_role('staff')
def staff_ticket(ticket_id):
    return render_template('business.html',user=identity(),view='ticket',title='工单处理',ticket=ticket_data(ticket_id))
