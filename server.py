"""Webサーバーだけを起動する (基盤仕様書 4.2)

起動の判断(多重起動・ブラウザ・ロック)は start_app.py / launch_guard.py が持つ。
ここは「127.0.0.1 で待ち受けて、要求を App に渡す」ことだけをする。

標準ライブラリの `http.server.ThreadingHTTPServer` を使う
(ラインPCの Python に Flask や waitress を入れられないため)。
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from app.core import logging_setup
from app.web import Request

log = logging_setup.get("server.http")

MAX_BODY = 1_000_000


class _Handler(BaseHTTPRequestHandler):
    server_version = "FileListTool"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self.send_error(413)
            return
        body = self.rfile.read(length) if length else b""
        req = Request.build(self.command, self.path, dict(self.headers.items()), body)
        resp = self.server.app.handle(req)                      # type: ignore[attr-defined]
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        for key, value in resp.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.body)

    do_GET = do_POST = do_HEAD = _serve

    def log_request(self, code="-", size="-") -> None:
        # 心拍などで埋まらないよう、断ったものだけ残す
        if str(code)[:1] in ("4", "5"):
            log.info("%s %s → %s", self.command, self.path.split("?")[0], code)

    def log_message(self, fmt: str, *args) -> None:              # 標準エラーに出さない
        log.debug(fmt, *args)


class AppServer:
    """待ち受け1つ。`stop()` で残った接続も含めて確実に閉じる。"""

    def __init__(self, app, host: str, port: int) -> None:
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.app = app                                    # type: ignore[attr-defined]
        self.host, self.port = host, self.httpd.server_address[1]
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        kwargs={"poll_interval": 0.3},
                                        name="http", daemon=True)
        self._thread.start()
        log.info("待ち受けを始めました: http://%s:%s/", self.host, self.port)

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        log.info("待ち受けを閉じました")
