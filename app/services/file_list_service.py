"""ファイル名一覧 (VBA `Get_FileName` の移植)

指定したフォルダにある**全ファイル**(隠し・システムファイルも含む。サブフォルダは
見ない)の名前を `文書番号_名称.拡張子` として分け、文書番号の先頭の数字で並べる。

VBA は班のオプションボタン(A/B/C/D/昼)でブックの場所の下の班フォルダを選んでいた。
Web 版では**フォルダのパスを直接打つ**(2026-10-16 の指示。VER1.2.0)。

    VBA のシート「一覧」          この関数の結果
    A 並べ替えキー(最後に消える)  ParsedName.sort_key
    B 文書番号                     ParsedName.doc_no
    C 名称                         ParsedName.title
    D 更新日時                     FileRow.modified
    E 拡張子                       ParsedName.ext

■ 分け方(`_` の数で変わる)

  `_` が1個:
    文書番号 = `_` より前
    並べ替えキー = Val(文書番号の最初の `-` より前)。0 なら空欄。文書番号が空なら空欄
    `_` より後ろを `.` で分け、先頭が空でなければ 名称 = 先頭・拡張子 = 最後
      → `12-1_手順書.v2.xlsx` は名称「手順書」(間の v2 は出ない。VBA どおり)
      → `6-1_手順書` は拡張子にも「手順書」が入る(VBA どおり)
  `_` が無い:
    拡張子 = 最後の `.` より後ろ(`.` が無ければ名前全体)
    名称 = 名前から「. + 拡張子」を**すべて**取り除いた残り(`a.txt.txt` → `a`)
    文書番号・並べ替えキーは空欄

■ VBA から直したところ(2026-10-15 に確認済み。移植計画 Q2・Q3)

  - `_` が2個以上: VBA は何も書かず空行にしていた(一覧に出ない)。**最初の `_` で
    分け**、残りの `_` は名称に含める(`6-4_手順_改.pdf` → 文書番号 6-4・名称 手順_改)
  - `_` で終わる名前(`abc_`): VBA は実行時エラー9で止まっていた。止めずに、
    名称・拡張子を空欄にして理由を添える(`abc_.pdf` と同じ扱い)

  `strict_vba=True` にすると直す前の VBA と同じに戻る(VBA の結果と突き合わせる
  `scripts/compare_with_vba.py` が使う)。

■ 並べ替え(VBA `Range("A1:E300").Sort Key1:=A, xlAscending`)

  - **先頭 300 行だけ**を並べる。301 行目以降は読んだ順のまま(VBA どおり。移植計画 Q4)
  - 数値の昇順。空欄は後ろへ回り、空欄どうしは読んだ順を保つ(Excel の並べ替えは安定)
  - 読んだ順 = `os.scandir` の順。Windows では FileSystemObject と同じ
    FindFirstFile の順になる
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from ..models.file_list import FileList, FileRow, ParsedName
from . import vba_compat

# VBA `WS.Range("A1:E300").Sort`
SORT_LIMIT_ROWS = 300

NOTE_TAIL_EMPTY = "「_」の後ろに名前がないため、名称と拡張子は空欄です"


class VbaWouldStop(Exception):
    """`strict_vba=True` のときだけ。VBA が実行時エラー9で止まる名前。"""

    def __init__(self, file_name: str) -> None:
        super().__init__(file_name)
        self.file_name = file_name


# ------------------------------------------------------------------
# ファイル名 → 1行
# ------------------------------------------------------------------
def parse_name(file_name: str, *, strict_vba: bool = False) -> ParsedName:
    parts = file_name.split("_")
    if len(parts) == 1:
        return _parse_without_underscore(file_name)
    if len(parts) > 2 and strict_vba:
        return ParsedName(blank_row=True)            # VBA: どの分岐にも入らない
    head, tail = file_name.split("_", 1)
    if tail == "" and strict_vba:
        raise VbaWouldStop(file_name)                # VBA: Split("", ".") の Buf(0)
    return _parse_with_underscore(head, tail)


def _parse_with_underscore(head: str, tail: str) -> ParsedName:
    parsed = ParsedName(doc_no=head)
    if head != "":
        key = vba_compat.val(head.split("-")[0])
        parsed.sort_key = None if key == 0 else key  # VBA: `If Cells(GYO,1) = 0 Then ""`
    buf = tail.split(".")
    if buf[0] != "":
        parsed.title = buf[0]
        parsed.ext = buf[-1]
    else:
        parsed.note = NOTE_TAIL_EMPTY
    return parsed


def _parse_without_underscore(file_name: str) -> ParsedName:
    pos = file_name.rfind(".")                       # VBA InStrRev(…, ".")。無ければ 0
    ext = file_name[pos + 1:] if pos >= 0 else file_name
    # VBA Replace は既定で大文字小文字を区別し、すべての出現を置き換える
    title = file_name.replace("." + ext, "")
    return ParsedName(title=title, ext=ext)


# ------------------------------------------------------------------
# 並べ替え
# ------------------------------------------------------------------
def sort_rows(rows: list, limit: int = SORT_LIMIT_ROWS) -> list:
    """先頭 `limit` 行を並べ替え、残りはそのまま後ろに付ける。"""
    head = sorted(rows[:limit], key=lambda r: (r.parsed.sort_key is None,
                                               r.parsed.sort_key or 0))
    return head + list(rows[limit:])


def build_rows(entries: Iterable, *, strict_vba: bool = False) -> list:
    """`(ファイル名, 更新日時)` を読んだ順に受け取り、並べ替えた行を返す。"""
    rows = [FileRow(file_name=name, modified=modified,
                    parsed=parse_name(name, strict_vba=strict_vba))
            for name, modified in entries]
    return sort_rows(rows)


# ------------------------------------------------------------------
# フォルダを読む
# ------------------------------------------------------------------
def scan_files(folder: Path) -> list:
    """フォルダ直下のファイル(読んだ順)。`[(名前, 更新日時)]`"""
    entries = []
    with os.scandir(folder) as it:                   # 開いたままにしない
        for entry in it:
            try:
                if not entry.is_file():
                    continue
                mtime = entry.stat().st_mtime
            except OSError:
                continue                             # 読む途中で消えたなど
            # FSO の DateLastModified は秒まで。端数は切り捨てる
            entries.append((entry.name, datetime.fromtimestamp(int(mtime))))
    return entries


def list_folder(folder: Path, *, strict_vba: bool = False,
                now: Optional[datetime] = None) -> FileList:
    """フォルダは呼ぶ側で確かめておく(`folder_input.parse`)。"""
    rows = build_rows(scan_files(folder), strict_vba=strict_vba)
    return FileList(folder=str(folder), title=folder.name or str(folder),
                    fetched_at=now or datetime.now().replace(microsecond=0),
                    rows=rows, sorted_rows=min(len(rows), SORT_LIMIT_ROWS))


# ------------------------------------------------------------------
# 表示
# ------------------------------------------------------------------
def format_modified(value: datetime) -> str:
    """Excel 既定の日付時刻の見え方 `yyyy/m/d h:mm`(移植計画 Q11)。"""
    return f"{value.year}/{value.month}/{value.day} {value.hour}:{value.minute:02d}"


def to_dict(result: FileList) -> dict:
    rows = []
    for row in result.rows:
        p = row.parsed
        rows.append({
            "file_name": row.file_name,
            "doc_no": p.doc_no,
            "title": p.title,
            "modified": format_modified(row.modified),
            "modified_iso": row.modified.isoformat(),
            "ext": p.ext,
            "note": p.note,
        })
    total = len(rows)
    unsorted = total - result.sorted_rows
    message = f"{total} 件"
    if unsorted > 0:
        message += (f"(先頭 {SORT_LIMIT_ROWS} 件だけ並べ替えています。"
                    f"残りの {unsorted} 件は読んだ順です)")
    return {
        "folder": result.folder,
        "title": result.title,
        "fetched_at": result.fetched_at.strftime("%Y/%m/%d %H:%M:%S"),
        "count": total,
        "sorted_rows": result.sorted_rows,
        "message": message,
        "rows": rows,
    }
