"""画面の URL と API の受付。入力の形だけ見て services へ渡す。"""
from __future__ import annotations


def register_all(app) -> None:
    from . import filelist, health, logs, pages, rename
    for module in (pages, health, filelist, rename, logs):
        module.register(app)
