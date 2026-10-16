"""画面(HTML)と静的ファイル"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from ..core import config
from ..services import file_list_service, folder_input, report_service
from ..web import HttpError, Request, Response, html_response

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = APP_DIR / "templates"
STATIC = APP_DIR / "static"
LOADING_HTML = config.BASE_DIR / "loading.html"

CONTENT_TYPES = {".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}


def _fill(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def register(app) -> None:
    r = app.router

    def page_values() -> dict:
        return {"TOKEN": app.token, "VERSION": config.version(), "APP_ID": config.app_id(),
                "APP_NAME": config.display_name(),
                "HEARTBEAT": int(config.monitoring("heartbeat_seconds", 20))}

    @r.get("/")
    def index(req: Request):
        if not app.state.ready:
            return loading(req)
        return html_response(_fill((TEMPLATES / "index.html").read_text(encoding="utf-8"),
                                   page_values()))

    @r.get("/loading")
    def loading(req: Request):
        return html_response(_fill(LOADING_HTML.read_text(encoding="utf-8"), page_values()))

    @r.get("/print")
    def print_view(req: Request):
        try:
            folder = folder_input.parse(req.query.get("folder", ""))
            listing = file_list_service.list_folder(folder)
        except folder_input.FolderInputError as exc:
            return html_response(report_service.render_error(
                exc.message + (f"({exc.folder})" if exc.folder else "")), 422)
        except OSError as exc:
            return html_response(report_service.render_error(
                f"フォルダを読めません({exc.strerror or exc})。"), 422)
        return html_response(report_service.render(file_list_service.to_dict(listing)))


def static_file(req: Request) -> Response:
    rel = req.path[len("/static/"):]
    target = (STATIC / rel).resolve()
    try:
        target.relative_to(STATIC.resolve())        # ../ で外へ出させない
    except ValueError:
        raise HttpError(404, "not_found", "ありません。")
    if not target.is_file():
        raise HttpError(404, "not_found", "ありません。")
    ctype = CONTENT_TYPES.get(target.suffix.lower()) or \
        (mimetypes.guess_type(str(target))[0] or "application/octet-stream")
    # 版を ?v= で付けて読むので、控えを使い回させてよい。版が上がれば URL が変わる
    return Response(status=200, body=target.read_bytes(), content_type=ctype,
                    headers={"Cache-Control": "no-cache"})
