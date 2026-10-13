"""Isolated, temporary public demo. No provider credentials or network calls."""
from pathlib import Path
import re
import secrets
import shutil
import threading
import time

from flask import abort, current_app, g, redirect, render_template, request, session
from .db import connect_database, initialize_database
from .seed import seed_demo


def database_path():
    sid = session.get('demo_id', '')
    if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{32}', sid):
        abort(403, '请从演示入口开始体验。')
    path = current_app.extensions['demo_root'] / (sid + '.sqlite3')
    if not path.is_file():
        abort(403, '临时数据已过期，请重新开始体验。')
    return path


def register_demo(app):
    root = Path(app.config.get('DEMO_DIRECTORY', '/tmp/aftercare-demo')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    template = root / 'template.sqlite3'
    initialize_database(template)
    db = connect_database(template)
    try:
        seed_demo(db, secrets.token_urlsafe(32))
    finally:
        db.close()
    app.extensions['demo_root'] = root
    app.config.update(DEEPSEEK_API_KEY='', DEEPSEEK_MODEL='demo-rules-no-ai')
    lock = threading.RLock()

    @app.before_request
    def demo_guard():
        # One worker; serialize requests so cleanup never deletes an active DB.
        if request.path.startswith('/static/') or request.path == '/health':
            return
        lock.acquire()
        g.demo_locked = True
        now = time.time()
        for path in root.glob('*.sqlite3'):
            if re.fullmatch(r'[a-f0-9]{32}\.sqlite3', path.name) and now-path.stat().st_mtime > 86400:
                path.unlink()
        sid = session.get('demo_id', '')
        if isinstance(sid, str) and re.fullmatch(r'[a-f0-9]{32}', sid):
            if not (root / (sid+'.sqlite3')).is_file():
                session.clear()
        if request.path == '/api/auth/login':
            abort(403, '公开演示请使用顾客或客服体验入口。')
        if request.path not in ('/demo', '/demo/enter', '/static/demo.js', '/api/session') and not session.get('demo_id'):
            if request.path.startswith('/api/'):
                abort(403, '请重新进入演示。')
            return redirect('/demo')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and session.get('demo_id'):
            path = database_path()
            if path.stat().st_size > 2 * 1024 * 1024:
                abort(429, '本次演示数据已达上限，请稍后重新体验。')

    @app.teardown_request
    def unlock_demo(_exc):
        if g.pop('demo_locked', False):
            # Close before releasing the cleanup lock.
            from .auth import close_db
            close_db(None)
            lock.release()

    @app.context_processor
    def demo_context():
        from .auth import csrf_token
        return {'public_demo': True, 'demo_csrf': csrf_token()}

    @app.get('/demo')
    def demo_home():
        return render_template('demo.html')

    @app.post('/demo/enter')
    def demo_enter():
        token = session.get('csrf_token', '')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(403)
        role = request.form.get('role')
        if role not in ('customer', 'staff'):
            abort(400)
        sid = session.get('demo_id')
        if not sid:
            if len(list(root.glob('*.sqlite3'))) > 100:
                abort(503, '演示空间暂满，请稍后再试。')
            sid = secrets.token_hex(16)
            shutil.copyfile(template, root / (sid+'.sqlite3'))
        session.clear()
        session.permanent = True
        session['demo_id'] = sid
        db = connect_database(database_path())
        try:
            row = db.execute('SELECT id FROM users WHERE username=?', ('demo_'+role+'_a',)).fetchone()
            session['user_id'] = row['id']
        finally:
            db.close()
        return redirect('/orders' if role == 'customer' else '/staff/tickets')


def simulated_suggestion(index, description):
    category = 'product' if any(x in description for x in ('破损', '损坏', '质量')) else 'other'
    return {'status':'suggested', 'reason':'demo_simulation', 'mode':'simulation',
            'answer':'模拟整理：规则分类并保留原文，未调用 AI，不计费。',
            'category':category, 'summary':description[:500], 'citations':[],
            'usage':None, 'elapsed_ms':0}
