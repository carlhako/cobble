from __future__ import annotations

import io
import json
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def make_bedrock_zip(version: str, *, truncated: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bedrock_server", b"#!/bin/true\n" + b"x" * 4096)
        zf.writestr("server.properties", f"# BDS {version}\nlevel-name=Bedrock level\n")
        zf.writestr("permissions.json", "[]")
        zf.writestr("allowlist.json", "[]")
    data = buf.getvalue()
    if truncated:
        data = data[: len(data) // 2]
    return data


@dataclass
class FakeVendor:
    host: str
    port: int
    version: str = "1.26.45.1"
    zip_bytes: bytes = b""
    require_user_agent: bool = True
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    reachable: bool = True

    @property
    def links_url(self) -> str:
        return f"http://{self.host}:{self.port}/api/v1.0/download/links"

    @property
    def download_url(self) -> str:
        return f"http://{self.host}:{self.port}/bin-linux/bedrock-server-{self.version}.zip"


@pytest.fixture
def fake_vendor() -> Iterator[FakeVendor]:
    state = FakeVendor(host="127.0.0.1", port=0)
    state.zip_bytes = make_bedrock_zip(state.version)

    handler_state = state

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _record(self):
            handler_state.requests.append((self.path, dict(self.headers)))

        def do_GET(self):
            self._record()
            if not handler_state.reachable:
                self.close_connection = True
                return
            if handler_state.require_user_agent and "User-Agent" not in self.headers:
                self.send_error(403, "no user agent")
                return
            if self.path.endswith("/download/links"):
                body = json.dumps(
                    {
                        "result": {
                            "links": [
                                {
                                    "downloadType": "serverBedrockWindows",
                                    "downloadUrl": f"http://x/bedrock-server-{handler_state.version}.zip",
                                },
                                {
                                    "downloadType": "serverBedrockLinux",
                                    "downloadUrl": handler_state.download_url,
                                },
                            ]
                        }
                    }
                ).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.endswith(".zip"):
                self.send_response(200)
                self.send_header("content-type", "application/zip")
                self.send_header("content-length", str(len(handler_state.zip_bytes)))
                self.end_headers()
                self.wfile.write(handler_state.zip_bytes)
            else:
                self.send_error(404)

    server = ThreadingHTTPServer((state.host, 0), Handler)
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
