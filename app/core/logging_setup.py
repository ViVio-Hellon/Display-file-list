"""文字のログ (基盤仕様書 2.6)

目的別に3つへ分ける。「起動前に失敗したのか」「Webサーバーが失敗したのか」
「業務処理で失敗したのか」をファイル名だけで切り分けられるようにする。

    launcher.log  起動入口(start_app)・多重起動の判断・停止
    server.log    Webサーバーの起動・終了・断った要求
    app.log       業務処理(一覧・リネーム・ログの出力先の変更)

■ 出力先(VER1.3.0)
`server.log` と `app.log` は、ログの面で決めた**ログの出力先**へ書く
(出来事の記録 `出来事_….jsonl` と同じ場所)。共有のフォルダを指したときは、
ほかの端末と混ざらないよう名前に端末を入れる(`app_PC-L1.log`)。
書けなければこの端末の logs へ書き、理由を覚えておく(画面に出す)。

`launcher.log` は**いつもこの端末の logs**。起動できないときに読むものなので、
共有に届かないと読めない場所には置かない(日報管理ツールと同じ決まり)。

1ファイル 1MB × 5 世代で回す。
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

from . import config

FORMAT = "%(asctime)s %(levelname)-7s [%(process)d] %(name)s: %(message)s"

LOCAL_CHANNELS = {"launcher": "launcher.log"}
MOVABLE_CHANNELS = {"server": "server", "app": "app"}

_configured = False
_state: dict = {"dir": None, "problem": ""}


def local_dir() -> Path:
    return config.local_dir("logs")


def _wanted_dir() -> Path:
    from ..repositories import settings_repository
    return settings_repository.log_dir() or local_dir()


def _usable(wanted: Path) -> Path:
    """書けるフォルダ。書けなければこの端末の logs(理由を覚えておく)。"""
    try:
        wanted.mkdir(parents=True, exist_ok=True)
        probe = wanted / ".filelist_write_check"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        _state["problem"] = ""
        return wanted
    except OSError as exc:
        _state["problem"] = f"{wanted} に書けません({exc.strerror or exc})"
        return local_dir()


def _file_name(stem: str, folder: Path) -> str:
    if folder == local_dir():
        return f"{stem}.log"
    from .event_log import safe_name, terminal_name
    return f"{stem}_{safe_name(terminal_name())}.log"


def _file_handler(path: Path) -> Optional[logging.Handler]:
    try:
        handler = logging.handlers.RotatingFileHandler(
            str(path), maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter(FORMAT))
    handler._filelist_path = str(path)            # type: ignore[attr-defined]
    return handler


def setup(*, console: bool = False, level: int = logging.INFO) -> None:
    """一度だけ呼ぶ。2回目以降は何もしない(出力先を移すのは `apply_log_dir`)。"""
    global _configured
    if _configured:
        return
    _configured = True
    try:
        local = local_dir()
    except OSError:
        local = None
    for channel, filename in LOCAL_CHANNELS.items():
        logger = logging.getLogger(channel)
        logger.setLevel(level)
        logger.propagate = False
        if local is not None:
            handler = _file_handler(local / filename)
            if handler:
                logger.addHandler(handler)
    for channel in MOVABLE_CHANNELS:
        logger = logging.getLogger(channel)
        logger.setLevel(level)
        logger.propagate = False
    if console and getattr(sys, "stderr", None) is not None:
        for channel in (*LOCAL_CHANNELS, *MOVABLE_CHANNELS):
            stream = logging.StreamHandler(sys.stderr)
            stream.setFormatter(logging.Formatter(FORMAT))
            logging.getLogger(channel).addHandler(stream)
    if local is not None:
        apply_log_dir()


def apply_log_dir() -> dict:
    """server.log / app.log の書き先を、いまのログの出力先へ移す。移した先と理由を返す。"""
    try:
        folder = _usable(_wanted_dir())
    except OSError:
        return status()
    if folder == _state["dir"]:
        return status()
    for channel, stem in MOVABLE_CHANNELS.items():
        logger = logging.getLogger(channel)
        for old in [h for h in logger.handlers if hasattr(h, "_filelist_path")]:
            logger.removeHandler(old)
            old.close()
        handler = _file_handler(folder / _file_name(stem, folder))
        if handler:
            logger.addHandler(handler)
    _state["dir"] = folder
    return status()


def status() -> dict:
    folder = _state["dir"]
    return {"dir": str(folder) if folder else "", "problem": str(_state["problem"] or "")}


def get(name: str) -> logging.Logger:
    """`launcher.*` / `server.*` / `app.*` のどれかで呼ぶ。"""
    return logging.getLogger(name)
