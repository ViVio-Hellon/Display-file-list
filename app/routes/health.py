"""起動確認・心拍・停止 (基盤仕様書 2.3 / 2.8 / 2.9)"""
from __future__ import annotations

from ..core import logging_setup
from ..web import HttpError, Request, json_response

log = logging_setup.get("server.health")


def register(app) -> None:
    r = app.router

    @r.get("/api/health")
    def health(req: Request):
        # まだトークンを知らない相手(多重起動の判定・待機画面)が問い合わせる。
        # 返すのは識別情報と状態だけで、業務データは含めない
        return json_response(app.health())

    @r.post("/api/alive")
    def alive(req: Request):
        app.state.alive()
        return json_response({"ok": True})

    @r.post("/api/bye")
    def bye(req: Request):
        # 画面を閉じた合図(sendBeacon)。再読込でも飛ぶので、すぐには止めない
        app.state.bye()
        return json_response({"ok": True})

    @r.post("/api/shutdown")
    def shutdown(req: Request):
        data = req.json()
        running = app.state.busy_labels()
        if running and not data.get("force"):
            raise HttpError(409, "busy", "処理の途中なので止めませんでした。",
                            {"running": running})
        log.info("停止の要求を受けました(force=%s)", bool(data.get("force")))
        app.request_shutdown()
        return json_response({"stopped": True})
