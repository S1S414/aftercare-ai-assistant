"""3.2—3.4：会话身份、角色检查和 CSRF 校验。"""
from functools import wraps
import secrets
import sqlite3

from flask import Blueprint, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import connect_database

bp = Blueprint('auth', __name__)
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(24))


def error(code, message, status):
    return jsonify(error={'code': code, 'message': message}), status


def get_db():
    if 'db' not in g:
        g.db = connect_database(current_app.config['DATABASE'])
    return g.db


def close_db(_exception=None):
    connection = g.pop('db', None)
    if connection is not None:
        connection.close()


def identity():
    if 'identity' not in g:
        user_id = session.get('user_id')
        g.identity = None
        if type(user_id) is int:
            row = get_db().execute('SELECT id,username,role FROM users WHERE id=?', (user_id,)).fetchone()
            if row is not None:
                g.identity = dict(row)
            else:
                session.clear()
    return g.identity


def require_role(*roles):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            user = identity()
            if user is None:
                return error('unauthenticated', '请先登录', 401)
            if roles and user['role'] not in roles:
                return error('forbidden', '当前账号没有此操作权限', 403)
            return function(*args, **kwargs)
        return wrapped
    return decorate


def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


def protect_modifications():
    if request.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        expected = session.get('csrf_token')
        provided = request.headers.get('X-CSRF-Token', '')
        if not isinstance(expected, str) or not secrets.compare_digest(expected, provided):
            return error('csrf_failed', '请求校验失败，请刷新后重试', 403)


@bp.get('/api/session')
def current_session():
    user = identity()
    return jsonify(data={'user': user, 'csrf_token': csrf_token()})


@bp.post('/api/auth/login')
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'username', 'password'}:
        return error('invalid_input', '请提供登录名和密码', 400)
    username, password = data['username'], data['password']
    if not isinstance(username, str) or not isinstance(password, str):
        return error('invalid_input', '登录名和密码必须是文本', 400)
    username = username.strip()
    if not 1 <= len(username) <= 100 or not 1 <= len(password) <= 1024:
        return error('invalid_input', '登录名或密码长度不正确', 400)
    row = get_db().execute('SELECT id,username,role,password_hash FROM users WHERE username=?', (username,)).fetchone()
    valid = check_password_hash(row['password_hash'] if row else _DUMMY_HASH, password)
    if row is None or not valid:
        return error('invalid_credentials', '登录名或密码错误', 401)
    session.clear()
    session.permanent = True
    session['user_id'] = row['id']
    # Rotate the CSRF token when privilege/identity changes.
    token = csrf_token()
    return jsonify(data={'user': {key: row[key] for key in ('id','username','role')}, 'csrf_token': token})


@bp.post('/api/auth/logout')
@require_role()
def logout():
    session.clear()
    return jsonify(data={'logged_out': True})


def register_auth(app):
    app.register_blueprint(bp)
    app.before_request(protect_modifications)
    app.teardown_appcontext(close_db)

    @app.after_request
    def response_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        return response

    @app.errorhandler(sqlite3.OperationalError)
    def database_unavailable(exception):
        app.logger.error('Database operational error (%s)', type(exception).__name__)
        return error('database_unavailable', '数据库暂不可用，请检查初始化或稍后重试', 503)

    @app.errorhandler(413)
    def too_large(_exception):
        return error('request_too_large', '请求内容过大', 413)
