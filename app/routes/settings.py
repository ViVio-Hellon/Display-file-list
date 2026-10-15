"""設定(基準フォルダ)とサーバ側のフォルダ参照"""
from __future__ import annotations

from pathlib import Path

from ..repositories import settings_repository
from ..services import fs_browse
from ..web import HttpError, Request, json_response, require_text


def register(app) -> None:
    r = app.router

    @r.post("/api/settings")
    def save(req: Request):
        data = req.json()
        text = require_text(data, "base_dir").strip()
        if text:
            path = Path(text)
            if not path.is_absolute():
                raise HttpError(422, "not_absolute",
                                "基準フォルダは「C:\\…」や「\\\\サーバ\\…」のように、はじめから書いてください。")
            if not path.is_dir():
                raise HttpError(422, "folder_missing", "そのフォルダはこのPCから見えません。")
        try:
            settings_repository.save(settings_repository.KEY_BASE_DIR, text)
        except OSError as exc:
            raise HttpError(422, "save_failed", f"設定を保存できませんでした({exc.strerror or exc})。")
        base = settings_repository.base_dir()
        return json_response({"base_dir": str(base),
                              "base_dir_default": settings_repository.base_dir_is_default(),
                              "base_dir_ok": base.is_dir()})

    @r.get("/api/fs/list")
    def fs_list(req: Request):
        return json_response(fs_browse.browse(req.query.get("path", "")))
