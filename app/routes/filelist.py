"""一覧 (VBA CommandButton1 → `Get_FileName`)。フォルダはパスで受け取る。"""
from __future__ import annotations

from ..core import config, logging_setup
from ..repositories import settings_repository
from ..services import file_list_service, folder_input
from ..web import HttpError, Request, json_response

log = logging_setup.get("app.filelist")


def folder_or_error(text: str):
    """打たれたパス → フォルダ。読めなければ 422 と、読んだパスを返す。"""
    try:
        return folder_input.parse(text)
    except folder_input.FolderInputError as exc:
        log.info("フォルダを読めません(%s): 入力 %r → %r", exc.code, text, exc.folder)
        raise HttpError(422, exc.code, exc.message, {"folder": exc.folder})


def register(app) -> None:
    r = app.router

    @r.get("/api/state")
    def state(req: Request):
        return json_response({"app_name": config.display_name(), "version": config.version(),
                              **settings_repository.last_dirs()})

    @r.get("/api/filelist")
    def filelist(req: Request):
        # 一覧にするもの(画面の選択ボタン)。無ければファイル(VBA どおり)
        target = req.query.get("target", "") or file_list_service.TARGET_FILES
        if target not in file_list_service.TARGETS:
            raise HttpError(422, "bad_target", "一覧にするもの(ファイル / フォルダ)を選んでください。")
        folder = folder_or_error(req.query.get("folder", ""))
        try:
            result = file_list_service.list_folder(folder, target=target)
        except OSError as exc:
            raise HttpError(422, "folder_unreadable",
                            f"フォルダを読めません({exc.strerror or exc})。", {"folder": str(folder)})
        settings_repository.save(settings_repository.KEY_LIST_DIR, str(folder))
        settings_repository.save(settings_repository.KEY_LIST_TARGET, target)
        log.info("一覧(%s): %s %d 件", target, result.folder, len(result.rows))
        return json_response(file_list_service.to_dict(result))
