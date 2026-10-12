"""10.2.1: temporary local HTTP startup check; no business DB or model calls."""
import json
import sys
import tempfile
import threading
from pathlib import Path
from urllib.request import build_opener, ProxyHandler
from werkzeug.serving import make_server
from app import create_app
from aftercare_app.db import initialize_database


def main():
    with tempfile.TemporaryDirectory() as folder:
        database = str(Path(folder) / 'startup.sqlite3')
        initialize_database(database)
        app = create_app({'DATABASE': database, 'DEEPSEEK_API_KEY': '',
                          'SECRET_KEY': 'temporary-startup-check'})
        server = make_server('127.0.0.1', 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        results = {}
        try:
            opener = build_opener(ProxyHandler({}))
            for route, marker in [('/health', b'"status":"ok"'),
                                  ('/login', b'<html'),
                                  ('/static/auth.js', b'')]:
                with opener.open(f'http://127.0.0.1:{server.server_port}{route}', timeout=5) as response:
                    body = response.read()
                    assert response.status == 200 and marker in body, route
                    results[route] = response.status
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
        print(json.dumps({'python': sys.version.split()[0],
                          'isolated_environment': sys.prefix != sys.base_prefix,
                          'http_checks': results, 'model_calls': 0}))


if __name__ == '__main__':
    main()
