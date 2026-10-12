"""2.2：连接、非破坏性初始化与显式事务。"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3


def connect_database(path):
    connection = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


def initialize_database(path):
    """只创建缺失表；不清空数据，也不代替后续数据库迁移。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = connect_database(path)
    try:
        connection.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
    finally:
        connection.close()


@contextmanager
def transaction(connection):
    """短写事务；任意一步失败，撤回整组写入。"""
    if connection.in_transaction:
        raise RuntimeError('不支持嵌套事务')
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
