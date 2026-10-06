"""A local HTTP source; tests change its routes instead of reaching the real site."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlsplit

import pytest


class Source:
    def __init__(self, url: str) -> None:
        self.url = url
        self.routes: dict[str, tuple[int, str, bytes]] = {}
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

    def json(self, path: str, value: object, status: int = 200) -> None:
        self.routes[path] = (status, "application/json", json.dumps(value, ensure_ascii=False).encode())

    def text(self, path: str, value: str, content_type: str = "text/calendar") -> None:
        self.routes[path] = (200, content_type, value.encode())


@pytest.fixture
def source():
    holder: dict[str, Source] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            holder["source"].requests.append((url.path, parse_qs(url.query)))
            status, content_type, body = holder["source"].routes.get(url.path, (404, "text/plain", b"missing"))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    holder["source"] = Source(f"http://127.0.0.1:{server.server_address[1]}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield holder["source"]
    server.shutdown()
    server.server_close()
