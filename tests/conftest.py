"""Shared test setup: the plugin package under a stable name, a local HTTP source and a fake Bilibili SDK."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).parents[1]
# Load the repository root as a package, as the host does, so modules keep their relative imports.
if "bilibili_plugin" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("bilibili_plugin", ROOT / "__init__.py",
                                                   submodule_search_locations=[str(ROOT)])
    _package = importlib.util.module_from_spec(_spec)
    sys.modules["bilibili_plugin"] = _package
    _spec.loader.exec_module(_package)
sys.path.insert(0, str(Path(__file__).parent))

from fake_sdk import FakeSdk, PICTURE  # noqa: E402


@pytest.fixture(autouse=True)
def sdk(monkeypatch):
    """Every test runs against the fake SDK, so no test reaches the real Bilibili site."""
    fake = FakeSdk()
    monkeypatch.setitem(sys.modules, "bilibili_api", fake.module)
    return fake


class Source:
    def __init__(self, url: str) -> None:
        self.url = url
        self.routes: dict[str, tuple[int, str, bytes]] = {}
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

    def json(self, path: str, value: object, status: int = 200) -> None:
        self.routes[path] = (status, "application/json", json.dumps(value, ensure_ascii=False).encode())

    def text(self, path: str, value: str, content_type: str = "text/calendar") -> None:
        self.routes[path] = (200, content_type, value.encode())

    def route(self, path: str) -> tuple[int, str, bytes]:
        if path.startswith("/img/"):
            return 200, "image/png", PICTURE
        return self.routes.get(path, (404, "text/plain", b"missing"))


@pytest.fixture
def source():
    holder: dict[str, Source] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            holder["source"].requests.append((url.path, parse_qs(url.query)))
            status, content_type, body = holder["source"].route(url.path)
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
