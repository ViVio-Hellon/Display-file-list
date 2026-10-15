"""サーバ側のフォルダ参照 (python-web-tools `presenters/fs_browse.py` と同じ考え方)

ブラウザのファイル選択はクライアント側のパスしか返さないので、
**このPCから見えるフォルダ**を一覧して選ばせる。

返すのは**フォルダの名前だけ**。ファイルの中身は返さない。件数にも上限を置く。
守りは 127.0.0.1 バインド・起動トークン・Host 確認・同一オリジン確認が担う。
"""
from __future__ import annotations

import string
import sys
from pathlib import Path

MAX_ENTRIES = 300


def roots() -> list:
    if sys.platform.startswith("win"):
        found = []
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            try:
                if drive.exists():
                    found.append({"name": f"{letter}:", "path": str(drive)})
            except OSError:
                continue
        return found
    return [{"name": "/", "path": "/"}, {"name": str(Path.home()), "path": str(Path.home())}]


def browse(text: str) -> dict:
    view = {"path": "", "parent": "", "exists": False, "readable": False,
            "message": "", "dirs": [], "truncated": False, "roots": roots()}
    value = (text or "").strip()
    if not value:
        view["message"] = "フォルダを選んでください。"
        return view
    path = Path(value)
    view["path"] = str(path)
    view["parent"] = str(path.parent) if path.parent != path else ""
    try:
        if not path.is_dir():
            view["message"] = "そのフォルダはこのPCから見えません。"
            return view
        view["exists"] = True
        names = sorted((p for p in path.iterdir() if _is_dir(p)), key=lambda p: p.name.lower())
    except OSError as exc:
        view["message"] = f"このフォルダを読めません({exc.strerror or exc})。"
        return view
    view["readable"] = True
    if len(names) > MAX_ENTRIES:
        view["truncated"] = True
        names = names[:MAX_ENTRIES]
    view["dirs"] = [{"name": p.name, "path": str(p)} for p in names]
    if not names:
        view["message"] = "この下にフォルダはありません。"
    elif view["truncated"]:
        view["message"] = f"先頭 {MAX_ENTRIES} 件まで表示しています。"
    return view


def _is_dir(p: Path) -> bool:
    try:
        return p.is_dir()
    except OSError:
        return False
