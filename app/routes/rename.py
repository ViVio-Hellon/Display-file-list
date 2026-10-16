"""全角→半角リネーム (VBA CommandButton3)。下見 → 実行の2段。"""
from __future__ import annotations

from pathlib import Path

from ..core import event_log, event_rules, logging_setup
from ..repositories import settings_repository
from ..services import rename_service
from ..web import HttpError, Request, json_response, require_bool, require_text
from .filelist import folder_or_error

log = logging_setup.get("app.rename")

LABEL = "全角→半角リネーム"


def _folder(data: dict) -> Path:
    folder = folder_or_error(require_text(data, "folder"))
    settings_repository.save(settings_repository.KEY_RENAME_DIR, str(folder))
    return folder


def register(app) -> None:
    r = app.router

    @r.post("/api/rename/preview")
    def preview(req: Request):
        data = req.json()
        folder = _folder(data)
        try:
            plan = rename_service.plan(folder, rename_folders=require_bool(data, "rename_folders"))
        except OSError as exc:
            raise HttpError(422, "folder_unreadable", f"フォルダを読めません({exc.strerror or exc})。")
        return json_response(rename_service.plan_to_dict(plan))

    @r.post("/api/rename/run")
    def run(req: Request):
        data = req.json()
        folder = _folder(data)
        plan_id = require_text(data, "plan_id")
        if not plan_id:
            raise HttpError(400, "no_plan", "先に「変わる名前を見る」を押してください。")
        app.state.begin(LABEL)
        try:
            result = rename_service.run(folder,
                                        rename_folders=require_bool(data, "rename_folders"),
                                        plan_id=plan_id, log=log.info)
        except rename_service.PlanChanged as exc:
            raise HttpError(409, "plan_changed", exc.message,
                            {"plan": rename_service.plan_to_dict(exc.plan)})
        except OSError as exc:
            raise HttpError(422, "folder_unreadable", f"フォルダを読めません({exc.strerror or exc})。")
        finally:
            app.state.end(LABEL)
        c = result.counts()
        log.info("リネーム完了: %s 成功 %d 件 / 失敗 %d 件", folder, c["ok"], c["fail"])
        failed = [f"{o.old}({o.reason})" for o in result.outcomes if not o.ok]
        event_log.note(f"リネームの結果: 成功 {c['ok']} 件 / 失敗 {c['fail']} 件"
                       + (f"。失敗: {'、'.join(failed[:10])}" if failed else ""),
                       kind=event_rules.KIND_WARN if failed else event_rules.KIND_INFO,
                       label="ファイル名変換の結果", folder=str(folder))
        return json_response(rename_service.result_to_dict(result))
