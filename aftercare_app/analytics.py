"""9: staff-only SQL metrics, Beijing calendar dates, explicit denominators."""
from datetime import datetime, time, timedelta, timezone, date
from flask import Blueprint, request, render_template, jsonify
from .auth import get_db, identity, require_role, error
from .pages import page_role

bp = Blueprint('analytics',__name__)
BEIJING = timezone(timedelta(hours=8))


def bounds(args):
    if set(args)-{'start','end'} or any(len(args.getlist(k))!=1 for k in args): raise ValueError('日期参数无效')
    today=datetime.now(BEIJING).date()
    start=date.fromisoformat(args.get('start',(today-timedelta(days=29)).isoformat()))
    end=date.fromisoformat(args.get('end',today.isoformat()))
    if start>end or (end-start).days>365: raise ValueError('请选择不超过366天的有效日期范围')
    def stamp(d): return datetime.combine(d,time(),BEIJING).astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    return start.isoformat(),end.isoformat(),stamp(start),stamp(end+timedelta(days=1))


def metrics(db, start, end, cutoff):
    # One read snapshot; do not mix counts from concurrent ticket state changes.
    db.execute('BEGIN')
    try:
        effective_end=min(end,cutoff)
        categories=[dict(r) for r in db.execute('SELECT category,count(*) AS count FROM tickets WHERE created_at>=? AND created_at<? GROUP BY category ORDER BY category',(start,effective_end))]
        pending=db.execute("SELECT count(*) FROM tickets WHERE status='pending'").fetchone()[0]
        closed=db.execute("SELECT count(*) AS count,avg((julianday(closed_at)-julianday(created_at))*86400) AS seconds FROM tickets WHERE status='closed' AND closed_at>=? AND closed_at<?",(start,effective_end)).fetchone()
        orders=db.execute('SELECT count(*) FROM orders WHERE created_at>=? AND created_at<?',(start,effective_end)).fetchone()[0]
        with_ticket=db.execute('SELECT count(*) FROM orders o WHERE o.created_at>=? AND o.created_at<? AND EXISTS(SELECT 1 FROM tickets t WHERE t.order_id=o.id AND t.created_at<=?)',(start,effective_end,cutoff)).fetchone()[0]
        invalid=db.execute("SELECT count(*) FROM tickets WHERE julianday(created_at) IS NULL OR (closed_at IS NOT NULL AND (julianday(closed_at) IS NULL OR julianday(closed_at)<julianday(created_at)))").fetchone()[0]
        return {'by_category':categories,'ticket_count':sum(r['count'] for r in categories),'current_pending':pending,
                'closed_count':closed['count'],'average_seconds':closed['seconds'],'order_count':orders,
                'orders_with_ticket':with_ticket,'aftercare_rate':with_ticket/orders if orders else None,
                'invalid_ticket_times':invalid,'cutoff':cutoff}
    finally: db.rollback()


def report():
    start_day,end_day,start,end=bounds(request.args)
    cutoff=datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    return start_day,end_day,metrics(get_db(),start,end,cutoff)


@bp.get('/staff/analytics')
@page_role('staff')
def page():
    try:
        start,end,data=report()
    except (ValueError,OverflowError):
        return render_template('analytics.html',user=identity(),message='日期无效，请使用YYYY-MM-DD，开始不晚于结束，范围最多366天。',data=None),400
    return render_template('analytics.html',user=identity(),data=data,start=start,end=end)


@bp.get('/api/staff/analytics')
@require_role('staff')
def api():
    try: start,end,data=report()
    except (ValueError,OverflowError): return error('invalid_input','日期范围无效',400)
    return jsonify(data={**data,'start':start,'end':end})
