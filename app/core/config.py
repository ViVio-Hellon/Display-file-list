"""アプリ固有値とローカル領域 (基盤仕様書 2.7 / 5.2)

アプリID・表示名・版・ポートは `config/app.json` ただ1つが出どころ。
複数のファイルへ書き散らさない。

実行中に変わるもの(ログ・ロック・設定・キャッシュ)は**利用者ごとの
ローカル領域**へ置く。アプリ本体を共有フォルダへ置いても、利用者ごとの
状態がぶつからず、共有側にログを撒かない。

    %LOCALAPPDATA%\\FileListTool\\runtime  起動中のPID・ポート・トークン
                                 \\logs     起動・アプリのログ
                                 \\pycache  Python のキャッシュ(Start.vbs が指定)
                                 \\cache / work / backup
"""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_JSON = BASE_DIR / "config" / "app.json"

LOCAL_SUBDIRS = ("runtime", "logs", "pycache", "cache", "work", "backup")

# 試験とローカル領域を差し替えたいときに使う
ENV_LOCAL_DIR = "FILELIST_TOOL_LOCAL_DIR"


@lru_cache(maxsize=1)
def app_json() -> dict[str, Any]:
    return json.loads(APP_JSON.read_text(encoding="utf-8"))


def app_id() -> str:
    return str(app_json()["app_id"])


def display_name() -> str:
    return str(app_json()["display_name"])


def version() -> str:
    return str(app_json()["version"])


def host() -> str:
    return str(app_json()["server"].get("host", "127.0.0.1"))


def base_port() -> int:
    return int(app_json()["server"]["port"])


def port_retry() -> int:
    return int(app_json()["server"].get("port_retry", 3))


def monitoring(key: str, default: float) -> float:
    return float(app_json().get("monitoring", {}).get(key, default))


def local_root() -> Path:
    override = os.environ.get(ENV_LOCAL_DIR)
    if override:
        return Path(override)
    name = str(app_json().get("local_dir_name", "FileListTool"))
    if sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / name
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / name


def local_dir(sub: str) -> Path:
    """ローカル領域の下のフォルダ。無ければ作る。"""
    if sub not in LOCAL_SUBDIRS:
        raise ValueError(f"未知のローカル領域: {sub!r}")
    path = local_root() / sub
    path.mkdir(parents=True, exist_ok=True)
    return path
