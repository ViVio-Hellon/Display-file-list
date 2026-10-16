"""ログ ── エラーの一覧・なぜなぜシート・CSV・画面のエラーの受け口・ログの出力先

日報管理ツールの `app/routes/logs.py` を写したもの。判断(何を一覧に出すか・経過を
どこまで拾うか・シートの形)は `core/event_rules.py`、読み書きは `core/event_log.py`。
ここは受け取って渡すだけ。
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from ..core import event_log, event_rules as rule, logging_setup
from ..repositories import settings_repository
from ..services import folder_input
from ..web import HttpError, Request, json_response, require_text

log = logging_setup.get("app.logs")

DEFAULT_DAYS = 7
MAX_DAYS = 93

# 壊れた画面が同じエラーを毎秒送ってくることがある。1分に30件まで
_client_lock = threading.Lock()
_client_window: dict = {"start": 0.0, "count": 0}
CLIENT_PER_MINUTE = 30


def _period(source: dict) -> tuple:
    today = date.today()
    try:
        end = date.fromisoformat(str(source.get("end", "") or today.isoformat()))
    except ValueError:
        end = today
    try:
        start = date.fromisoformat(str(source.get("start", "")
                                       or (end - timedelta(days=DEFAULT_DAYS - 1)).isoformat()))
    except ValueError:
        start = end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        start, end = end, start
    if (end - start).days >= MAX_DAYS:
        start = end - timedelta(days=MAX_DAYS - 1)
    return start, end


def _filters(source: dict) -> dict:
    scope = source.get("scope", rule.DEFAULT_SCOPE)
    return {"scope": scope if scope in rule.SCOPES else rule.DEFAULT_SCOPE,
            "terminal": str(source.get("terminal", "") or ""),
            "text": str(source.get("q", "") or "")}


def log_status() -> dict:
    """いまの出力先と、書けていないならその理由(出来事と文字のログの両方)。"""
    out = event_log.status()
    text = logging_setup.status()
    out["setting"] = str(settings_repository.get(settings_repository.KEY_LOG_DIR, "") or "")
    out["text_dir"] = text["dir"]
    out["text_problem"] = text["problem"]
    return out


def register(app) -> None:
    r = app.router

    @r.get("/api/log/events")
    def events(req: Request):
        start, end = _period(req.query)
        filters = _filters(req.query)
        records = event_log.load(start, end)
        picked = rule.select(records, **filters)
        notes = event_log.analyses()
        counts = {key: sum(1 for x in records if x.get("kind") in kinds)
                  for key, kinds in rule.SCOPES.items()}
        return json_response({
            "rows": [rule.list_row(x, notes.get(str(x.get("id", "")))) for x in picked],
            "start": start.isoformat(), "end": end.isoformat(), "filters": filters,
            "counts": counts, "terminals": event_log.terminals(records),
            "status": log_status(),
            "scopes": [{"key": k, "label": v} for k, v in rule.SCOPE_LABELS.items()],
        })

    @r.get("/api/log/summary")
    def summary(req: Request):
        """画面右上の「ログ」に出す数(この2日のまだ対策済にしていないエラー)。"""
        return json_response({"open_errors": event_log.open_errors(),
                              "problem": log_status()["fallback"]})

    @r.get("/api/log/event")
    def event(req: Request):
        event_id = req.query.get("id", "").strip()
        target, records = event_log.find(event_id)
        if target is None:
            raise HttpError(404, "not_found", f"番号 {event_id} の記録が見つかりません"
                            "(番号の打ち間違いか、出力先を変える前の記録です)。")
        note = event_log.analyses().get(event_id)
        return json_response({"sheet": rule.sheet(target, rule.timeline(records, target), note),
                              "why_count": rule.WHY_COUNT,
                              "statuses": [{"key": k, "label": v}
                                           for k, v in rule.STATUS_LABELS.items()]})

    @r.post("/api/log/event/analysis")
    def save_analysis(req: Request):
        """なぜなぜを残す。ログの出力先に書く(共有なら全端末から見える)。"""
        body = req.json()
        event_id = require_text(body, "id").strip()
        target, records = event_log.find(event_id)
        if target is None:
            raise HttpError(404, "not_found", f"番号 {event_id} の記録が見つかりません。")
        note = event_log.save_analysis(event_id, body)
        log.info("なぜなぜを残しました: %s (%s)", event_id, rule.STATUS_LABELS.get(note["status"], ""))
        return json_response({"sheet": rule.sheet(target, rule.timeline(records, target), note),
                              "message": f"{event_id} のなぜなぜを残しました"})

    @r.post("/api/log/csv")
    def export_csv(req: Request):
        """いまの絞り込みのまま CSV へ。出した先のパスを返す(ダウンロードはしない)。"""
        body = req.json()
        start, end = _period(body)
        records = rule.select(event_log.load(start, end), limit=100_000, **_filters(body))
        if not records:
            raise HttpError(422, "empty", "この絞り込みでは1件もありません。")
        try:
            path = event_log.export_csv(records, event_log.analyses())
        except OSError as exc:
            raise HttpError(422, "write_failed", f"CSV を書けませんでした({exc})。")
        return json_response({"path": str(path),
                              "message": f"{len(records)} 件を CSV に出しました: {path}"})

    @r.post("/api/log/client")
    def client_error(req: Request):
        """画面(ブラウザ)で起きたエラー。番号を返す(画面に出してもらう)。"""
        with _client_lock:
            if time.monotonic() - _client_window["start"] > 60:
                _client_window.update(start=time.monotonic(), count=0)
            _client_window["count"] += 1
            if _client_window["count"] > CLIENT_PER_MINUTE:
                return json_response({"id": "", "skipped": True})
        body = req.json()
        fields = app.request_context()
        fields.pop("action", None)
        fields.pop("input", None)
        fields.update({
            "terminal": event_log.terminal_name(),
            "screen": str(body.get("screen") or fields.get("screen") or ""),
            "label": "画面のエラー",
            "message": rule.clip(body.get("message"), rule.MESSAGE_MAX),
            "where": rule.clip(body.get("where"), 200),
            "cause": rule.clip(body.get("kind") or "error", 40),
            "trace": rule.clip(body.get("stack"), rule.TRACE_MAX),
            "crumbs": [rule.clip(c, 120) for c in list(body.get("crumbs") or [])[-20:]],
            "version": str(body.get("version") or ""),
        })
        record = rule.make(rule.KIND_CLIENT, at=datetime.now(), **fields)
        event_log.record(record)
        log.warning("[%s] 画面のエラー: %s (%s)", record["id"], record["message"],
                    record["screen"], extra={"event_id": record["id"]})
        return json_response({"id": record["id"]})

    @r.get("/api/log/settings")
    def settings(req: Request):
        return json_response(log_status())

    @r.post("/api/log/settings")
    def save_settings(req: Request):
        """ログの出力先を変える。空ならこの端末の logs。**その場で書き先が移る。**"""
        text = folder_input.clean(require_text(req.json(), "log_dir"))
        if text:
            path = Path(text)
            if not path.is_absolute():
                raise HttpError(422, "folder_relative", folder_input.MESSAGE_RELATIVE,
                                {"folder": text})
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".filelist_write_check"
                probe.write_text("", encoding="utf-8")
                probe.unlink()
            except OSError as exc:
                raise HttpError(422, "log_dir_unwritable",
                                f"このフォルダに書けません({exc.strerror or exc})。"
                                "共有フォルダなら、つながっているか・書く権限があるかを確かめてください。",
                                {"folder": text})
        before = log_status()["dir"]
        settings_repository.save(settings_repository.KEY_LOG_DIR, text)
        event_log.reset()
        logging_setup.apply_log_dir()
        after = log_status()["dir"]
        if before != after:
            log.info("ログの出力先を変えました: %s → %s", before, after)
            event_log.note(f"ログの出力先を変えました: {before} → {after}",
                           label="ログの出力先を変えた")
        return json_response({**log_status(), "message": f"ログの出力先: {after}"})
