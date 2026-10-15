"""一覧 (VBA CommandButton1 → `Get_FileName`)"""
from __future__ import annotations

from ..core import config, logging_setup
from ..repositories import settings_repository
from ..services import file_list_service
from ..web import HttpError, Request, json_response

log = logging_setup.get("app.filelist")


def groups() -> list:
    items = [{"key": k, "label": file_list_service.group_button_label(k)}
             for k, _ in file_list_service.GROUPS]
    items.append({"key": file_list_service.BASE_GROUP[0],
                  "label": file_list_service.BASE_GROUP[1]})
    return items


def register(app) -> None:
    r = app.router

    @r.get("/api/state")
    def state(req: Request):
        base = settings_repository.base_dir()
        return json_response({
            "app_name": config.display_name(), "version": config.version(),
            "base_dir": str(base), "base_dir_default": settings_repository.base_dir_is_default(),
            "base_dir_ok": base.is_dir(), "groups": groups(),
        })

    @r.get("/api/filelist")
    def filelist(req: Request):
        group = req.query.get("group", "")
        try:
            file_list_service.group_label(group)
        except ValueError:
            raise HttpError(400, "bad_group", "班の指定が違います。")
        base = settings_repository.base_dir()
        try:
            result = file_list_service.list_folder(base, group)
        except file_list_service.FolderMissing as exc:
            raise HttpError(422, "folder_missing", exc.message, {"folder": exc.folder})
        except OSError as exc:
            raise HttpError(422, "folder_unreadable",
                            f"フォルダを読めません({exc.strerror or exc})。")
        log.info("一覧: %s %d 件", result.folder, len(result.rows))
        return json_response(file_list_service.to_dict(result))
