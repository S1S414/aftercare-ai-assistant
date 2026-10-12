"""10.2 SQLite snapshot/restore into a NEW file; never overwrite a database."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3


def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist')
    if source == destination:
        raise ValueError('Source and destination must differ')
    # Exclusive creation protects existing business data, including concurrent runs.
    with destination.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('Integrity check failed')
                if dst.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('Foreign key check failed')
    except BaseException:
        destination.unlink(missing_ok=True)  # Only the file exclusively created above.
        raise
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('destination', help='New file in an existing directory')
    args = parser.parse_args()
    try:
        print('Verified database:', snapshot(args.source, args.destination))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f'Backup/restore failed: {exc}\n')
