"""7.5.7：发出请求前持久化预占额度，异常时不退还次数。"""
from datetime import datetime, timedelta, timezone
import uuid
from .db import transaction

DAILY_LIMIT = 20
MINUTE_LIMIT = 5


class UsageBlocked(Exception):
    pass


def ensure_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS model_calls (
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        started_at TEXT NOT NULL, finished_at TEXT, day TEXT NOT NULL,
        endpoint TEXT NOT NULL, peer TEXT NOT NULL, model TEXT NOT NULL,
        status TEXT NOT NULL, reason TEXT, elapsed_ms INTEGER,
        prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
        provider_id TEXT
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS model_calls_day ON model_calls(day)')


def reserve(db, user_id, peer, model, now=None, endpoint='/api/knowledge/model-answer'):
    ensure_table(db)
    if endpoint not in ('/api/knowledge/model-answer', '/api/assistant/tasks/suggest', 'cli:evaluate_suite'):
        raise ValueError('未知的模型调用来源')
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    cutoff = (now - timedelta(minutes=1)).isoformat()
    request_id = str(uuid.uuid4())
    with transaction(db):
        if db.execute("SELECT 1 FROM model_calls WHERE status='pending' LIMIT 1").fetchone():
            raise UsageBlocked('已有模型请求处理中或结果未确认，请先检查调用记录；不自动重复调用。')
        if db.execute('SELECT count(*) FROM model_calls WHERE day=?', (day,)).fetchone()[0] >= DAILY_LIMIT:
            raise UsageBlocked('本项目今日已达到20次模型请求上限（北京时间），请先核对记录。')
        if db.execute('SELECT count(*) FROM model_calls WHERE started_at>=?', (cutoff,)).fetchone()[0] >= MINUTE_LIMIT:
            raise UsageBlocked('本项目每分钟最多5次模型请求，请稍后再试。')
        db.execute('''INSERT INTO model_calls
            (id,user_id,started_at,day,endpoint,peer,model,status)
            VALUES (?,?,?,?,?,?,?,'pending')''',
            (request_id,user_id,now.isoformat(),day,endpoint,peer,model))
    return request_id


def finish(db, request_id, result):
    usage = result.get('usage') or {}
    with transaction(db):
        cursor = db.execute('''UPDATE model_calls SET finished_at=?,status=?,reason=?,elapsed_ms=?,
            prompt_tokens=?,completion_tokens=?,total_tokens=?,provider_id=? WHERE id=? AND status='pending' ''',
            (datetime.now(timezone.utc).isoformat(),result['status'],result['reason'],result.get('elapsed_ms'),
             usage.get('prompt_tokens'),usage.get('completion_tokens'),usage.get('total_tokens'),result.get('provider_id'),request_id))
        return cursor.rowcount == 1


def resolve_pending(db, request_id, reviewed=False):
    """Release one interrupted call only after the operator reviewed provider usage.

    The attempt remains in all quota counts and its billing outcome stays unknown.
    """
    if not reviewed:
        raise ValueError('必须先核对平台用量，再明确确认解除')
    try:
        request_id = str(uuid.UUID(request_id))
    except (ValueError, AttributeError):
        raise ValueError('本地请求编号必须是UUID') from None
    with transaction(db):
        row = db.execute('SELECT status FROM model_calls WHERE id=?', (request_id,)).fetchone()
        if row is None:
            raise ValueError('未找到该调用记录')
        if row['status'] != 'pending':
            raise ValueError('该调用记录不是处理中状态')
        db.execute("""UPDATE model_calls SET finished_at=?,status='unavailable',
            reason='manually_reconciled_unknown' WHERE id=? AND status='pending'""",
            (datetime.now(timezone.utc).isoformat(), request_id))


def recent(db, user):
    ensure_table(db)
    if user['role'] == 'staff':
        rows = db.execute('SELECT * FROM model_calls ORDER BY started_at DESC LIMIT 100').fetchall()
    else:
        rows = db.execute('SELECT * FROM model_calls WHERE user_id=? ORDER BY started_at DESC LIMIT 100', (user['id'],)).fetchall()
    return [dict(r) for r in rows]
