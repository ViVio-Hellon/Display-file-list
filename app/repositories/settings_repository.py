"""利用者ごとの覚え書き(最後に使ったフォルダのパス・ログの出力先)

VER1.2.0 で基準フォルダの設定をなくし、フォルダはパスを打つだけにした。
毎日同じフォルダを打たなくて済むよう、**最後に使えたパス**だけを覚えておき、
次に開いたときの入力欄に入れる。

置き場所はローカル領域の `cache/settings.json`(利用者ごと)。DB は使わない。
書くときは一時ファイルに書いてから置き換える(書きかけで落ちても壊れない)。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

from ..core import config, logging_setup

log = logging_setup.get("app.settings")

KEY_LIST_DIR = "list_dir"          # ファイル名取得のフォルダ
KEY_RENAME_DIR = "rename_dir"      # ファイル名変換のフォルダ
KEY_LOG_DIR = "log_dir"            # ログの出力先(空ならこの端末の logs)

_lock = threading.Lock()           # 一覧(GET)とリネーム(POST)が同時に書いても混ざらないように


def path() -> Path:
    return config.local_dir("cache") / "settings.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("覚え書きを読めませんでした(空で続けます): %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def save(key: str, value: Any) -> None:
    """書けなくても業務は止めない(覚えておけないだけ)。"""
    with _lock:
        data = load()
        if data.get(key) == value:
            return
        data[key] = value
        target = path()
        tmp = target.with_name(f"settings.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, target)
        except OSError as exc:
            log.warning("覚え書きを保存できませんでした: %s", exc)


def last_dirs() -> dict:
    data = load()
    return {"list_dir": str(data.get(KEY_LIST_DIR, "") or ""),
            "rename_dir": str(data.get(KEY_RENAME_DIR, "") or "")}


def log_dir() -> Optional[Path]:
    """ログの出力先。決めていなければ None(この端末の logs を使う)。"""
    text = str(get(KEY_LOG_DIR, "") or "").strip()
    return Path(text) if text else None
