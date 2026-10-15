"""ログ (基盤仕様書 2.6)

目的別に3つへ分ける。「起動前に失敗したのか」「Webサーバーが失敗したのか」
「業務処理で失敗したのか」をファイル名だけで切り分けられるようにする。

    launcher.log  起動入口(start_app)と多重起動の判断(launch_guard)
    server.log    Webサーバーの起動・終了・要求の失敗
    app.log       業務処理(一覧・リネーム・設定)

出力先はローカル領域の logs。1ファイル 1MB × 5 世代で回す。
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from typing import Optional

from . import config

FORMAT = "%(asctime)s %(levelname)-7s [%(process)d] %(name)s: %(message)s"

# ロガー名の先頭 → ファイル
CHANNELS = {"launcher": "launcher.log", "server": "server.log", "app": "app.log"}

_configured = False


def setup(*, console: bool = False, level: int = logging.INFO) -> None:
    """一度だけ呼ぶ。2回目以降は何もしない。"""
    global _configured
    if _configured:
        return
    _configured = True
    formatter = logging.Formatter(FORMAT)
    try:
        log_dir: Optional[object] = config.local_dir("logs")
    except OSError:
        log_dir = None                       # 書けなくても起動は止めない
    for channel, filename in CHANNELS.items():
        logger = logging.getLogger(channel)
        logger.setLevel(level)
        logger.propagate = False
        if log_dir is not None:
            try:
                handler = logging.handlers.RotatingFileHandler(
                    str(log_dir / filename), maxBytes=1_000_000, backupCount=5,
                    encoding="utf-8")
                handler.setFormatter(formatter)
                logger.addHandler(handler)
            except OSError:
                pass
        if console:
            stream = logging.StreamHandler(sys.stderr)
            stream.setFormatter(formatter)
            logger.addHandler(stream)


def get(name: str) -> logging.Logger:
    """`launcher.*` / `server.*` / `app.*` のどれかで呼ぶ。"""
    return logging.getLogger(name)
