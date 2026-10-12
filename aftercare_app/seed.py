"""2.3：显式创建本地模拟数据，不覆盖既有账号或订单。"""
from datetime import datetime, timedelta, timezone
from uuid import uuid5, NAMESPACE_URL
from werkzeug.security import generate_password_hash
from .db import transaction


def seed_demo(connection, password, now=None):
    if len(password) < 12:
        raise ValueError('本地演示密码至少 12 个字符')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('时间必须包含时区')
    def stamp(days=0):
        return (now + timedelta(days=days)).astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    with transaction(connection):
        for username, role in [('demo_customer_a','customer'), ('demo_customer_b','customer'), ('demo_staff_a','staff'), ('demo_staff_b','staff')]:
            connection.execute(
                'INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?,?,?) ON CONFLICT(username) DO NOTHING',
                (username, generate_password_hash(password), role, stamp(-10)))
        users = {row['username']: row['id'] for row in connection.execute('SELECT id,username FROM users')}
        for no, owner, status, expected, delivered in [
            ('DEMO-001','demo_customer_a','in_transit',-1,None),
            ('DEMO-002','demo_customer_a','delivered',-2,-3),
            ('DEMO-003','demo_customer_b','in_transit',2,None),
        ]:
            connection.execute(
                'INSERT INTO orders(order_no,user_id,product_name,delivery_status,expected_delivery_at,delivered_at,created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(order_no) DO NOTHING',
                (no,users[owner],'模拟商品（非真实订单）',status,stamp(expected),stamp(delivered) if delivered is not None else None,stamp(-5)))
        order = connection.execute("SELECT id,user_id FROM orders WHERE order_no='DEMO-001'").fetchone()
        key = str(uuid5(NAMESPACE_URL, 'aftercare/local-demo/ticket-001'))
        existing = connection.execute('SELECT id FROM tickets WHERE requester_id=? AND request_key=?', (order['user_id'],key)).fetchone()
        if not existing:
            cursor = connection.execute(
                'INSERT INTO tickets(order_id,requester_id,category,description,created_at,request_key) VALUES (?,?,?,?,?,?)',
                (order['id'],order['user_id'],'delivery','模拟订单已超过预计送达时间，请协助核查。',stamp(),key))
            connection.execute(
                "INSERT INTO ticket_events(ticket_id,actor_id,event_type,to_status,note,created_at) VALUES (?,?,'created','pending',?,?)",
                (cursor.lastrowid,order['user_id'],'创建模拟工单',stamp()))
