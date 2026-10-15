"""利用者ごとの設定 (VBA では `ThisWorkbook.Path` が担っていたもの)

VBA は「ブックが置いてある場所」を基準に班のフォルダを探していた。Web 版には
ブックが無いので、**基準フォルダ**を設定として持つ。

置き場所はローカル領域の `cache/settings.json`(利用者ごと)。
DB は使わない ── 持つのはこの1項目だけで、複数のPCが同じ値を書き合う必要も無い。

書くときは一時ファイルに書いてから置き換える(書きかけで落ちても壊れない)。
前の内容は `backup/` に1世代残す。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..core import config, logging_setup

log = logging_setup.get("app.settings")

KEY_BASE_DIR = "base_dir"


def path() -> Path:
    return config.local_dir("cache") / "settings.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("設定を読めませんでした(既定値で続けます): %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def save(key: str, value: Any) -> None:
    data = load()
    data[key] = value
    target = path()
    if target.exists():
        try:
            backup = config.local_dir("backup") / "settings.json.bak"
            backup.write_bytes(target.read_bytes())
        except OSError as exc:
            log.warning("設定の控えを残せませんでした: %s", exc)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    log.info("設定を保存しました: %s=%s", key, value)


def base_dir() -> Path:
    """基準フォルダ。未設定ならアプリのフォルダ(VBA でブックを置いていた場所に当たる)。"""
    text = str(get(KEY_BASE_DIR, "") or "").strip()
    return Path(text) if text else config.BASE_DIR


def base_dir_is_default() -> bool:
    return not str(get(KEY_BASE_DIR, "") or "").strip()
