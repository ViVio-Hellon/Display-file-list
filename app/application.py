"""アプリの組み立てと、要求ごとの守り

■ 守り(python-web-tools `app/__init__.py` と同じ考え方)

| 対策 | 内容 |
|---|---|
| バインド先 | 127.0.0.1 のみ(server.py) |
| 起動トークン | 起動ごとに作る。`/api/*` と `/print` に必須(ヘッダ `X-Tool-Token` か `?t=`) |
| Host 検証 | `127.0.0.1:<port>` / `localhost:<port>` 以外は 400(DNS リバインディング対策) |
| 同一オリジン | `Sec-Fetch-Site` が same-origin / none 以外なら 403。CORS ヘッダは返さない |

■ 書く要求は1つずつ通す

POST(心拍・停止を除く)は錠で直列化する。同じ画面を2つのタブで開いて
同時にリネームを押しても、2つ目は1つ目が終わってから計画を作り直す。
"""
from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .core import config, logging_setup
from .web import HttpError, Request, Response, Router, html_response, json_response

log = logging_setup.get("server.app")

APP_DIR = Path(__file__).resolve().parent

TOKEN_REQUIRED_PREFIXES = ("/api/", "/print")
TOKEN_EXEMPT_PATHS = frozenset({"/api/health", "/api/alive", "/api/bye"})
# 錠を取らない POST。止める・心拍は、長いリネームの最中でも届く必要がある
LOCK_EXEMPT_PATHS = frozenset({"/api/alive", "/api/bye", "/api/shutdown"})
# 準備が終わる前でも答えるもの
READY_EXEMPT_PATHS = frozenset({"/", "/loading", "/api/health", "/api/alive",
                                "/api/bye", "/api/shutdown"})


class AppState:
    """プロセスに1つ。保存しない(落ちたら消える)。"""

    def __init__(self) -> None:
        self.ready = False
        self.stage = "アプリを準備中"
        self.started_at = time.time()
        self.startup_error = ""
        self._busy: dict = {}
        self._lock = threading.Lock()
        self.last_alive = 0.0
        self.ever_alive = False
        self.bye_at = 0.0

    # --- 実行中の処理(停止・自動終了の判断に使う) ---
    def begin(self, label: str) -> None:
        with self._lock:
            self._busy[label] = self._busy.get(label, 0) + 1

    def end(self, label: str) -> None:
        with self._lock:
            n = self._busy.get(label, 0) - 1
            if n <= 0:
                self._busy.pop(label, None)
            else:
                self._busy[label] = n

    def busy_labels(self) -> list:
        with self._lock:
            return sorted(self._busy)

    # --- 画面の心拍 ---
    def alive(self) -> None:
        self.last_alive = time.time()
        self.ever_alive = True
        self.bye_at = 0.0

    def bye(self) -> None:
        self.bye_at = time.time()


class App:
    def __init__(self, *, port: int, token: Optional[str] = None,
                 on_shutdown: Optional[Callable[[], None]] = None) -> None:
        self.port = port
        self.token = token or secrets.token_urlsafe(32)
        self.state = AppState()
        self.on_shutdown = on_shutdown
        self.write_lock = threading.RLock()
        self.router = Router()
        from .routes import register_all
        register_all(self)

    # ------------------------------------------------------------------
    def allowed_hosts(self) -> set:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def handle(self, req: Request) -> Response:
        try:
            resp = self._handle(req)
        except HttpError as exc:
            resp = exc.to_response()
        except Exception as exc:                          # noqa: BLE001 - 最後の受け
            log.exception("要求の処理で失敗しました: %s %s", req.method, req.path)
            resp = HttpError(500, "internal",
                             f"思わぬ失敗がありました({type(exc).__name__})。"
                             "ログ(server.log)を確かめてください。").to_response()
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    def _handle(self, req: Request) -> Response:
        if req.headers.get("host", "") not in self.allowed_hosts():
            raise HttpError(400, "bad_host", "このアドレスからは使えません。")

        if req.path.startswith(TOKEN_REQUIRED_PREFIXES) and req.path not in TOKEN_EXEMPT_PATHS:
            site = req.headers.get("sec-fetch-site", "")
            if site and site not in ("same-origin", "none"):
                raise HttpError(403, "cross_site", "ほかのページからは使えません。")
            given = req.headers.get("x-tool-token") or req.query.get("t", "")
            # bytes で比べる(str のままだと ASCII 以外の字で TypeError になる)
            if not secrets.compare_digest(given.encode("utf-8", "replace"),
                                          self.token.encode("utf-8")):
                raise HttpError(403, "bad_token",
                                "画面が古くなっています。画面を開き直してください。")

        if not self.state.ready and req.path not in READY_EXEMPT_PATHS \
                and not req.path.startswith("/static/"):
            raise HttpError(503, "starting", "起動しています。少し待ってください。")

        if req.path.startswith("/static/") and req.method == "GET":
            from .routes import pages
            return pages.static_file(req)

        handler = self.router.find(req.method, req.path)
        if handler is None:
            if self.router.allows(req.path):
                raise HttpError(405, "method", "この操作はできません。")
            if req.path.startswith("/api/"):
                raise HttpError(404, "not_found", "そのような操作はありません。")
            return html_response("<!doctype html><meta charset=utf-8><p>ページがありません。"
                                 "<a href=\"/\">はじめの画面へ</a></p>", 404)

        if req.method == "POST" and req.path not in LOCK_EXEMPT_PATHS:
            with self.write_lock:
                return handler(req)
        return handler(req)

    # ------------------------------------------------------------------
    def health(self) -> dict:
        import os
        return {"app_id": config.app_id(), "display_name": config.display_name(),
                "version": config.version(), "ready": self.state.ready,
                "stage": self.state.stage, "error": self.state.startup_error,
                "pid": os.getpid(), "port": self.port,
                "started_at": self.state.started_at,
                "running": self.state.busy_labels()}

    def request_shutdown(self) -> None:
        if self.on_shutdown:
            threading.Thread(target=self.on_shutdown, name="shutdown", daemon=True).start()


def ok(data: Optional[dict] = None) -> Response:
    return json_response(data if data is not None else {"ok": True})
