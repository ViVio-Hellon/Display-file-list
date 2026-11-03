"""一覧の1行と一覧全体。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union

Number = Union[int, float]


@dataclass
class ParsedName:
    """ファイル名だけから決まる部分(VBA の A・B・C・E 列)。"""

    sort_key: Optional[Number] = None   # A 列。並べ替えのあと消える。None = 空欄
    doc_no: str = ""                    # B 列 → 最終形の「文書番号」
    title: str = ""                     # C 列 → 「名称」
    ext: str = ""                       # E 列 → 「拡張子」
    blank_row: bool = False             # VBA 互換モードで `_` が2つ以上 = 何も書かない行
    note: str = ""                      # 画面に添える説明(VBA には無い)


@dataclass
class FileRow:
    file_name: str
    modified: datetime                  # D 列 → 「更新日時」
    parsed: ParsedName


@dataclass
class FileList:
    folder: str
    title: str                          # 画面と紙面の見出し(フォルダの名前)
    fetched_at: datetime
    rows: list = field(default_factory=list)      # list[FileRow]
    # 並べ替えたのは先頭から何行か(VBA は A1:E300)。これより後ろは読んだ順のまま
    sorted_rows: int = 0
    target: str = "files"               # files = ファイルの一覧 / folders = 直下のフォルダの一覧
