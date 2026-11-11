#!/usr/bin/env python3
"""配布用のフォルダを作る(VER2.0.0)。標準ライブラリだけ。

    python scripts/make_dist.py                       # FileListTool.exe をフォルダの直下に置いてから
    python scripts/make_dist.py --exe <exe の場所> --out <作る場所>

入れるもの: 動かすのに要るもの(Start.vbs・start.bat・stop.bat・*.py・app\\・config\\・loading.html)と
README・docs。デスクトップ版の exe は **「ファイル名一覧取得.exe」** の名前で入れる。
入れないもの: src-tauri(外枠のソース)・tests・tools・scripts・.github・vba(移植元の控え)。

exe は GitHub Actions(デスクトップ版(Windows))が作る。成果物 FileListTool-windows から取る。
exe が無ければ、ブラウザ版だけの配布フォルダを作る(そう言う)。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE_NAME = "ファイル名一覧取得.exe"
FILES = ("Start.vbs", "start.bat", "stop.bat", "start_app.py", "bridge.py", "launch_guard.py",
         "process_manager.py", "server.py", "loading.html", "README.md")
FOLDERS = ("app", "config", "docs")
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", default=str(ROOT / "FileListTool.exe"), help="デスクトップ版の exe")
    parser.add_argument("--out", default=str(ROOT / "dist" / "ファイル名一覧取得"), help="作る場所")
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name in FILES:
        shutil.copy2(ROOT / name, out / name)
    for name in FOLDERS:
        shutil.copytree(ROOT / name, out / name, ignore=SKIP)
    exe = Path(args.exe)
    if exe.is_file():
        shutil.copy2(exe, out / EXE_NAME)
        print(f"デスクトップ版: {out / EXE_NAME}")
    else:
        print(f"デスクトップ版の exe がありません({exe})。ブラウザ版だけの配布フォルダを作りました", file=sys.stderr)
    print(f"作りました: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
