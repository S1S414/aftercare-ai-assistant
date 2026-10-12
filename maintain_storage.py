"""Offline storage maintenance. Preview by default; never calls model APIs."""
import argparse
from contextlib import contextmanager
import hashlib
from pathlib import Path
import socket
import sqlite3
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent


def old_calls(path):
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='model_calls'").fetchone():
            return []
        rows = []
        for row in db.execute("SELECT * FROM model_calls WHERE status IN ('answered','suggested','abstained','unavailable') ORDER BY started_at"):
            try:
                started = datetime.fromisoformat(row['started_at'].replace('Z','+00:00'))
                ended = datetime.fromisoformat(row['finished_at'].replace('Z','+00:00'))
                # Keep current quota periods even if timestamps are inconsistent.
                day = datetime.strptime(row['day'], '%Y-%m-%d').date()
                if started.tzinfo and ended.tzinfo and started <= ended < cutoff and day < cutoff.date():
                    rows.append(dict(row))
            except (ValueError, TypeError, AttributeError):
                continue
    db.close()
    return rows


def delete_calls(path, selected):
    if not selected or len({r['id'] for r in selected}) != len(selected):
        raise ValueError('请选择不重复的调用记录。')
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw', uri=True, timeout=0)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN IMMEDIATE')
        current = {r['id']:r for r in old_calls(path)}
        if any(current.get(r['id']) != r for r in selected):
            raise ValueError('记录已变化或未满足7天条件，请重新预览。')
        db.executemany('DELETE FROM model_calls WHERE id=?', [(r['id'],) for r in selected])
        db.commit()
        return len(selected)
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def size(path):
    return sum(p.stat().st_size for p in (path, Path(str(path)+'-wal'), Path(str(path)+'-shm')) if p.exists())


@contextmanager
def offline():
    # Keep the port reserved throughout maintenance so a normal server cannot start.
    with socket.socket() as guard:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        guard.bind(('127.0.0.1', 5005))
        guard.listen(1)
        yield


def compact(path):
    path = Path(path).resolve(strict=True)
    before = size(path)
    db = sqlite3.connect(path.as_uri()+'?mode=rw', uri=True, timeout=0)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        # Offline maintenance supports rollback-journal databases only.
        # Do not silently switch WAL mode or remove its files.
        if db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal':
            raise ValueError('检测到WAL模式，请先另行核对并关闭所有连接；本工具未执行整理。')
        db.execute('PRAGMA locking_mode=EXCLUSIVE')
        db.execute('BEGIN EXCLUSIVE')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('数据库检查未通过，停止整理。')
        db.commit()  # Exclusive locking mode retains the file lock across VACUUM.
        db.execute('VACUUM')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('整理后检查未通过，请停止使用并排查。')
    finally:
        db.close()
    after = size(path)
    return before, after, before-after


def backup_files(root):
    root = Path(root).resolve()
    instance = root/'instance'
    candidates = list((instance/'restore-checks').glob('*/backup.sqlite3'))
    candidates += list((instance/'restore-checks').glob('*/restored.sqlite3'))
    candidates += list((instance/'backups').glob('*.sqlite3'))
    rows = []
    for path in sorted(candidates):
        resolved = path.resolve(strict=True)
        if resolved != path.absolute() or not resolved.is_relative_to(instance) or not resolved.is_file():
            raise ValueError('备份路径包含链接或越界，停止。')
        rows.append((path, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()))
    return rows


def delete_backups(root, selected):
    # Revalidate the entire approved selection before touching any file.
    current = {str(row[0]): row for row in backup_files(root)}
    if not selected or len({str(r[0]) for r in selected}) != len(selected):
        raise ValueError('请选择不重复的备份编号。')
    for row in selected:
        if current.get(str(row[0])) != row:
            raise ValueError('备份已变化，请重新预览。')
        if any(Path(str(row[0])+suffix).exists() for suffix in ('-wal','-shm','-journal')):
            raise ValueError('备份存在数据库附属文件，可能正在使用；停止删除。')
    removed = 0
    for path, length, _ in selected:
        path.unlink()  # Exact validated file only; no recursive directory deletion.
        removed += length
        print('已删除：', path)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preview','compact','backups'], nargs='?', default='preview')
    args = parser.parse_args()
    database = ROOT/'instance'/'aftercare.sqlite3'
    try:
        print('数据库及WAL/SHM文件合计：', size(database), '字节')
        rows = backup_files(ROOT)
        for number, (path, length, _) in enumerate(rows, 1):
            print(f'{number}. {path.relative_to(ROOT)} — {length} 字节')
        print('项目管理的备份合计：', sum(r[1] for r in rows), '字节')
        if args.action == 'preview':
            print('仅预览，未修改。compact=释放数据库空闲空间；backups=选择备份永久删除。')
            return
        with offline():
            if args.action == 'compact':
                print('请关闭其他访问数据库的工具。整理不删除仍存在的业务记录；不会自动建立备份。')
                if input('输入 COMPACT 确认整理：') != 'COMPACT':
                    print('已取消。'); return
                before, after, released = compact(database)
                print(f'整理前：{before} 字节；整理后：{after} 字节；实际减少：{released} 字节')
            else:
                if not rows:
                    print('没有项目管理的备份。'); return
                ids = [int(v) for v in input('输入要删除的备份编号，用空格分隔；直接回车取消：').split()]
                if not ids:
                    print('已取消。'); return
                if any(i < 1 or i > len(rows) for i in ids):
                    raise ValueError('编号超出范围。')
                selected = [rows[i-1] for i in ids]
                for path, length, _ in selected:
                    print('将永久删除：', path, length, '字节')
                print('不进入回收站；删除全部备份会失去这些恢复副本。')
                if input('输入 DELETE 确认以上清单：') != 'DELETE':
                    print('已取消。'); return
                print('已删除备份文件共：', delete_backups(ROOT, selected), '字节')
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f'维护停止：{exc}。若端口被占用，请先关闭项目服务。\n')


if __name__ == '__main__':
    main()
