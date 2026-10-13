"""项目启动骨架：业务接口在 A 模块逐步实现。"""

from flask import Flask, jsonify, render_template, redirect
from pathlib import Path
from datetime import timedelta
import os
import secrets
import click
from aftercare_app.auth import register_auth, identity
from aftercare_app.api import bp as business_api
from aftercare_app.pages import bp as page_routes
from aftercare_app.db import connect_database, initialize_database
from aftercare_app.seed import seed_demo
from aftercare_app.knowledge import bp as knowledge_routes
from aftercare_app.retrieval import PolicyIndex
from aftercare_app import model_usage
from aftercare_app.assistant_routes import bp as assistant_routes
from aftercare_app.analytics import bp as analytics_routes
from aftercare_app.task_management import bp as task_management_routes


_LOCAL_SECRET = secrets.token_hex(32)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=str(Path(__file__).resolve().parent / 'instance' / 'aftercare.sqlite3'),
        SECRET_KEY=os.environ.get('AFTERCARE_SECRET_KEY') or _LOCAL_SECRET,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('AFTERCARE_ENV') == 'production',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=16 * 1024,
        DEEPSEEK_API_KEY=os.environ.get('DEEPSEEK_API_KEY', ''),
        DEEPSEEK_MODEL='deepseek-flash',
        QA_CONTEXT_STRATEGY='all-small',
        PUBLIC_DEMO=os.environ.get('AFTERCARE_PUBLIC_DEMO') == '1',
    )
    if test_config:
        app.config.update(test_config)
    if os.environ.get('AFTERCARE_ENV') == 'production' and not os.environ.get('AFTERCARE_SECRET_KEY'):
        raise RuntimeError('生产环境必须配置 AFTERCARE_SECRET_KEY')
    if app.config['PUBLIC_DEMO']:
        from aftercare_app.public_demo import register_demo
        register_demo(app)
    register_auth(app)
    app.register_blueprint(business_api)
    app.register_blueprint(page_routes)
    app.extensions['policy_index'] = PolicyIndex(Path(__file__).resolve().parent / 'data' / 'policies.json')
    app.register_blueprint(knowledge_routes)
    app.register_blueprint(assistant_routes)
    app.register_blueprint(analytics_routes)
    app.register_blueprint(task_management_routes)

    @app.get('/')
    def index():
        user=identity()
        return redirect('/login' if not user else '/staff/tickets' if user['role']=='staff' else '/orders')

    @app.get('/login')
    def login_preview():
        return render_template('login.html')

    @app.cli.command('init-db')
    def init_db_command():
        initialize_database(app.config['DATABASE'])
        click.echo('2.2 数据库初始化完成；既有数据保留。')

    @app.cli.command('seed-demo')
    @click.option('--password', prompt='本地演示密码（至少12字符）', hide_input=True, confirmation_prompt=True)
    def seed_demo_command(password):
        if len(password) < 12:
            raise click.ClickException('本地演示密码至少12字符')
        initialize_database(app.config['DATABASE'])
        connection = connect_database(app.config['DATABASE'])
        try:
            seed_demo(connection, password)
        finally:
            connection.close()
        click.echo('2.3 模拟数据已准备；重复执行不重置既有密码或业务记录。')

    @app.cli.command('resolve-model-call')
    @click.argument('request_id')
    @click.option('--reviewed-platform', is_flag=True,
                  help='确认已在DeepSeek平台核对该时段用量；不会退款或恢复次数。')
    def resolve_model_call_command(request_id, reviewed_platform):
        """人工解除服务中断后遗留的pending调用。"""
        connection = connect_database(app.config['DATABASE'])
        try:
            model_usage.ensure_table(connection)
            model_usage.resolve_pending(connection, request_id, reviewed_platform)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None
        finally:
            connection.close()
        click.echo('调用记录已标记为人工核对、结果未知；原调用仍计入次数，不会自动重试。')

    @app.get('/health')
    def health():
        return jsonify(status='ok', stage='business_pages', business_ready=True)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5005, debug=False)
