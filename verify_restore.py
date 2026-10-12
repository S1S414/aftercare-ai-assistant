"""10.2.2: verify a real database snapshot without replacing the original."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from app import create_app
from backup_database import snapshot


def inspect(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        tables = [row[1] for row in schema if row[0] == 'table']
        counts, digests = {}, {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = db.execute('SELECT * FROM ' + quoted).fetchall()
            encoded = sorted(repr(row) for row in rows)
            counts[table] = len(rows)
            digests[table] = hashlib.sha256(repr(encoded).encode()).hexdigest()
        return {'schema_digest': hashlib.sha256(repr(schema).encode()).hexdigest(),
                'counts': counts, 'table_digests': digests,
                'integrity': db.execute('PRAGMA integrity_check').fetchall(),
                'foreign_key_errors': db.execute('PRAGMA foreign_key_check').fetchall()}


def main():
    root = Path(__file__).resolve().parent
    source = root / 'instance' / 'aftercare.sqlite3'
    folder = root / 'instance' / 'restore-checks' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    before = inspect(source)
    backup = snapshot(source, folder / 'backup.sqlite3')
    restored = snapshot(backup, folder / 'restored.sqlite3')
    after, saved, recovered = inspect(source), inspect(backup), inspect(restored)
    assert before == after == saved == recovered, 'Data changed or snapshot differs; do not accept this run'
    assert recovered['integrity'] == [('ok',)] and not recovered['foreign_key_errors']
    app = create_app({'TESTING': True, 'DATABASE': str(restored),
                      'DEEPSEEK_API_KEY': '', 'SECRET_KEY': 'restore-check-only'})
    client = app.test_client()
    checks = {}
    with closing(sqlite3.connect(restored)) as db:
        for role, route in [('customer', '/orders'), ('staff', '/staff/analytics')]:
            user = db.execute('SELECT id FROM users WHERE role=? ORDER BY id LIMIT 1', (role,)).fetchone()
            assert user, 'Missing demo role'
            with client.session_transaction() as session:
                session['user_id'] = user[0]
            response = client.get(route)
            assert response.status_code == 200, route
            checks[role + ':' + route] = response.status_code
    assert inspect(restored) == recovered, 'Read checks changed recovered database'
    report = {'source': str(source), 'backup': str(backup), 'restored': str(restored),
              'all_table_contents_and_schema_equal': True, 'source_unchanged_during_snapshot': True,
              'counts': recovered['counts'], 'integrity': 'ok', 'foreign_key_errors': 0,
              'page_reads': checks, 'model_calls': 0,
              'limitations': 'Same-machine restore; injected test sessions, not password-login or full browser acceptance. Same-disk backups are not disaster recovery.'}
    report_path = folder / 'report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('Report:', report_path)


if __name__ == '__main__':
    main()
