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

import json
import secrets
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .core import config, event_log, event_rules, logging_setup
from .web import HttpError, Request, Response, Router, html_response, json_response

log = logging_setup.get("server.app")

APP_DIR = Path(__file__).resolve().parent

TOKEN_REQUIRED_PREFIXES = ("/api/", "/print")
TOKEN_EXEMPT_PATHS = frozenset({"/api/health", "/api/alive", "/api/bye"})
# 錠を取らない POST。止める・心拍は、長いリネームの最中でも届く必要がある
LOCK_EXEMPT_PATHS = frozenset({"/api/alive", "/api/bye", "/api/shutdown", "/api/log/client"})
# 準備が終わる前でも答えるもの
READY_EXEMPT_PATHS = frozenset({"/", "/loading", "/api/health", "/api/alive",
                                "/api/bye", "/api/shutdown"})


_current = threading.local()


def _summarize(req: Request) -> dict:
    """送られた中身の要約(伏せ字つき)。トークンは残さない。"""
    try:
        if req.method == "GET":
            args = {k: v for k, v in req.query.items() if k != "t"}
            return event_rules.summarize_input(args) if args else {}
        data = json.loads(req.body.decode("utf-8")) if req.body else None
        return event_rules.summarize_input(data) if data else {}
    except Exception:                                     # noqa: BLE001
        return {}


def _response_message(resp: Response) -> str:
    """断りの文言。画面に出たものと同じものを残す。"""
    try:
        if not resp.content_type.startswith("application/json"):
            return ""
        body = json.loads(resp.body.decode("utf-8"))
        info = body.get("error") if isinstance(body.get("error"), dict) else {}
        return str(info.get("message") or "")
    except Exception:                                     # noqa: BLE001
        return ""


def user_message(event_id: str) -> str:
    return (f"思わぬエラーが起きました(エラー番号 {event_id})。もう一度押しても同じなら、"
            "この番号を管理者に伝えてください。画面右上の「ログ」でこのときの様子を見られます。")


def _error_page(event_id: str, message: str) -> str:
    """画面(HTML)で起きたとき。部品に頼らずその場で書く(壊れていても出る)。"""
    from html import escape
    return ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>エラー</title><style>"
            ":root{--bg:#fff;--fg:#17232d;--line:#c9d0db;--accent:#982326}"
            "@media (prefers-color-scheme:dark){:root{--bg:#101820;--fg:#e2eaef;"
            "--line:#28343d;--accent:#e49093}}"
            "body{background:var(--bg);color:var(--fg);font-family:sans-serif;margin:0;"
            "padding:32px 16px}main{max-width:640px;margin:0 auto}"
            "h1{font-size:20px;color:var(--accent)}code{font-size:18px;font-weight:bold;"
            "border:1px solid var(--line);padding:2px 8px;border-radius:4px}a{color:inherit}"
            "</style></head><body><main>"
            f"<h1>思わぬエラーが起きました</h1><p>エラー番号 <code>{escape(event_id)}</code></p>"
            f"<p>{escape(message)}</p>"
            f"<p><a href='/'>はじめの画面へ</a> ・ <a href='/logs?id={escape(event_id)}'>ログを見る</a></p>"
            "</main></body></html>")


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
        event_log.set_context_provider(self.request_context)
        from .routes import register_all
        register_all(self)

    # ------------------------------------------------------------------
    def allowed_hosts(self) -> set:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def handle(self, req: Request) -> Response:
        """要求1つ。**出来事の記録**(何をした・断り・予期しないエラーに番号)もここで残す。"""
        started = time.monotonic()
        _current.req = req
        _current.request_id = uuid.uuid4().hex[:8]
        try:
            resp = self._handle(req)
        except HttpError as exc:
            resp = exc.to_response()
        except Exception as exc:                          # noqa: BLE001 - 最後の受け
            resp = self._unexpected(req, exc, started)
            _current.done = True
        try:
            if not getattr(_current, "done", False):
                self._record(req, resp, started)
        except Exception:                                 # noqa: BLE001 - 記録で落とさない
            pass
        finally:
            _current.req = None
            _current.done = False
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    # ------------------------------------------------------------------
    # 出来事の記録(日報管理ツールの app/event_capture.py と同じ役目)
    # ------------------------------------------------------------------
    @staticmethod
    def request_context() -> dict:
        """いまの要求の様子。要求の外(裏の処理)なら空。"""
        req = getattr(_current, "req", None)
        if req is None:
            return {}
        return {"screen": req.headers.get("x-screen", "")
                          or ("" if req.path.startswith("/api/") else req.path),
                "tab": req.headers.get("x-tab", ""),
                "request": getattr(_current, "request_id", ""),
                "action": f"{req.method} {req.path}",
                "input": _summarize(req)}

    def _fields(self, req: Request, status: int, started: float) -> dict:
        fields = self.request_context()
        fields.update({"terminal": event_log.terminal_name(), "version": config.version(),
                       "status": status, "ms": int((time.monotonic() - started) * 1000),
                       "label": event_rules.label_of(req.method, req.path)})
        return fields

    def _record(self, req: Request, resp: Response, started: float) -> None:
        quiet = req.headers.get("x-quiet") == "1"
        if not event_rules.should_record(req.method, req.path, resp.status, quiet=quiet):
            return
        kind = event_rules.kind_of_status(resp.status)
        fields = self._fields(req, resp.status, started)
        if kind != event_rules.KIND_OP:
            fields["message"] = _response_message(resp)
        event_log.record(event_rules.make(kind, at=datetime.now(), **fields))

    def _unexpected(self, req: Request, exc: Exception, started: float) -> Response:
        """予期しないエラー。**番号**を付けて記録し、画面にも同じ番号を出す。"""
        now = datetime.now()
        event_id = event_rules.new_id(event_rules.KIND_ERROR, now)
        message = user_message(event_id)
        try:
            fields = self._fields(req, 500, started)
            fields.update(event_log.describe_exception(exc))
            event_log.record(event_rules.make(event_rules.KIND_ERROR, at=now, id=event_id,
                                              message=message, **fields))
        except Exception:                                 # noqa: BLE001
            pass
        # 文字のログにも番号つきで。出来事にはもう残したので、拾う口には二重に残させない
        log.error("[%s] 予期しないエラー: %s %s", event_id, req.method, req.path,
                  exc_info=exc, extra={"event_id": event_id})
        if req.path.startswith("/api/"):
            return HttpError(500, "internal", message, {"event_id": event_id}).to_response()
        return html_response(_error_page(event_id, message), 500)

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
