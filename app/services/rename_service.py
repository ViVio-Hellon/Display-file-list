"""全角→半角リネーム (VBA `ExecuteRenameBasicErrorHandling` 一式の移植)

■ VBA と同じところ

  - 対象は指定フォルダの**直下**だけ(画面からは `recursive=False` 固定だった)
  - 先にファイル、次に(チェックしたときだけ)直下のフォルダ
  - ファイル: 変換後の名前が既にあれば `名前_1.拡張子`、それも有れば `_2`…
    (`fso.GetBaseName` / `GetExtensionName` と同じく、最後の `.` で分ける)
  - フォルダ: 変換後の名前が既にあれば変えずに失敗として数える
  - 名前が変わらないものは触らない
  - 1件ずつ順に処理するので、前の件で付けた名前は後の件の「既にある」に入る

■ VBA から変えたところ(2026-10-15 に確認済み。移植計画 Q14)

  - **実行の前に「変わる名前の一覧」を見せる**(`plan`)。VBA は押すとすぐ変えていた
  - 結果を画面に出す。VBA はイミディエイトウィンドウ(Debug.Print)にしか出さなかった

■ 変える前に失敗とするもの(VBA では移動を試して失敗していたもの)

  - 変換後に Windows の名前に使えない字が入る(`＼／：＊？＂＜＞｜` → `\\ / : * ? " < > |`)。
    特に `/` と `\\` は Python ではフォルダの区切りになり、**別の場所へ動いてしまう**ので、
    試す前に止める
  - 変換後の名前が空白か `.` で終わる(Windows が黙って削るので、思った名前にならない)
  - 変換後が Windows の予約名(CON・PRN・AUX・NUL・COM1〜9・LPT1〜9)

■ 複数のPCが同時に同じフォルダを触るとき

  `run` は**実行の瞬間にフォルダを読み直して**計画を作り直し、下見のときの計画と
  違えば何も変えずに断る(`PlanChanged`)。変える直前にも行き先を確かめ、
  あれば上書きせずにその件を失敗にする(Windows の `os.rename` も行き先が
  あれば失敗する)。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import halfwidth

KIND_FILE = "file"
KIND_FOLDER = "folder"

STATUS_RENAME = "rename"          # 変換後の名前で変える
STATUS_NUMBERED = "numbered"      # 同名があるので _1 などを付けて変える
STATUS_FAIL = "fail"              # 変えない(理由つき)

INVALID_CHARS = set('\\/:*?"<>|')
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL",
                  *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

REASON_INVALID = "半角にすると Windows の名前に使えない字({chars})が入ります"
REASON_TRAILING = "半角にすると名前の終わりが空白か「.」になります"
REASON_RESERVED = "半角にすると Windows の予約名({name})になります"
REASON_FOLDER_EXISTS = "同じ名前のフォルダが既にあります"
REASON_OTHER_KIND_FILE = "同じ名前のフォルダが既にあります"
REASON_OTHER_KIND_FOLDER = "同じ名前のファイルが既にあります"
REASON_APPEARED = "直前に同じ名前ができていました"


class FolderNotFound(Exception):
    message = "フォルダが見つかりません。"


class PlanChanged(Exception):
    """下見のあとにフォルダの中身が変わった。新しい計画を持たせて返す。"""

    message = ("下見のあとでフォルダの中身が変わりました。"
               "新しい一覧を確かめてから、もう一度実行してください。")

    def __init__(self, plan: "RenamePlan") -> None:
        super().__init__("plan changed")
        self.plan = plan


@dataclass
class RenameItem:
    kind: str
    old: str
    converted: str                # 半角にしただけの名前
    new: str = ""                 # 実際に付ける名前(_1 などを付けたあと)。失敗なら空
    status: str = STATUS_RENAME
    reason: str = ""


@dataclass
class RenamePlan:
    folder: str
    rename_folders: bool
    items: list = field(default_factory=list)       # list[RenameItem]
    plan_id: str = ""

    def counts(self) -> dict:
        will = sum(1 for i in self.items if i.status != STATUS_FAIL)
        return {"total": len(self.items), "rename": will,
                "fail": len(self.items) - will,
                "numbered": sum(1 for i in self.items if i.status == STATUS_NUMBERED)}


@dataclass
class RenameOutcome:
    kind: str
    old: str
    new: str
    ok: bool
    reason: str = ""


@dataclass
class RunResult:
    folder: str
    outcomes: list = field(default_factory=list)    # list[RenameOutcome]

    def counts(self) -> dict:
        ok = sum(1 for o in self.outcomes if o.ok)
        return {"total": len(self.outcomes), "ok": ok, "fail": len(self.outcomes) - ok}


def _default_fold() -> Callable[[str], str]:
    """Windows の名前は大文字小文字を区別しない(FSO の FileExists もそう)。"""
    return str.casefold if os.name == "nt" else (lambda s: s)


# ------------------------------------------------------------------
# 名前の決まり
# ------------------------------------------------------------------
def name_problem(name: str) -> str:
    bad = sorted({c for c in name if c in INVALID_CHARS})
    if bad:
        return REASON_INVALID.format(chars=" ".join(bad))
    if name.endswith((" ", ".")):
        return REASON_TRAILING
    stem = name.split(".")[0].upper()
    if stem in RESERVED_NAMES:
        return REASON_RESERVED.format(name=stem)
    return ""


def split_base_ext(name: str) -> tuple:
    """`fso.GetBaseName` / `GetExtensionName`: 最後の `.` で分ける。"""
    pos = name.rfind(".")
    return (name, "") if pos < 0 else (name[:pos], name[pos + 1:])


def numbered_name(name: str, taken: set, fold: Callable[[str], str]) -> str:
    """VBA `RenameFile`: `基本名_1.拡張子` から空きを探す。"""
    base, ext = split_base_ext(name)
    counter = 1
    while True:
        candidate = f"{base}_{counter}.{ext}" if ext != "" else f"{base}_{counter}"
        counter += 1
        if fold(candidate) not in taken:
            return candidate


# ------------------------------------------------------------------
# 計画(下見)
# ------------------------------------------------------------------
def _listing(folder: Path) -> tuple:
    """直下の (ファイル名の一覧, フォルダ名の一覧)。読んだ順。"""
    files, dirs = [], []
    with os.scandir(folder) as it:
        for entry in it:
            try:
                if entry.is_dir(follow_symlinks=False):
                    dirs.append(entry.name)
                elif entry.is_file():
                    files.append(entry.name)
            except OSError:
                continue
    return files, dirs


def plan(folder: Path, *, rename_folders: bool,
         fold: Optional[Callable[[str], str]] = None) -> RenamePlan:
    fold = fold or _default_fold()
    if not folder.is_dir():
        raise FolderNotFound(str(folder))
    files, dirs = _listing(folder)
    file_names = {fold(n) for n in files}
    dir_names = {fold(n) for n in dirs}

    result = RenamePlan(folder=str(folder), rename_folders=rename_folders)

    for name in files:
        converted = halfwidth.to_halfwidth(name)
        if converted == name:
            continue
        item = RenameItem(kind=KIND_FILE, old=name, converted=converted)
        problem = name_problem(converted)
        if problem:
            item.status, item.reason = STATUS_FAIL, problem
        elif fold(converted) in dir_names:
            item.status, item.reason = STATUS_FAIL, REASON_OTHER_KIND_FILE
        else:
            target = converted
            if fold(converted) in file_names:
                target = numbered_name(converted, file_names | dir_names, fold)
                item.status = STATUS_NUMBERED
            item.new = target
            file_names.discard(fold(name))
            file_names.add(fold(target))
        result.items.append(item)

    if rename_folders:
        for name in dirs:
            converted = halfwidth.to_halfwidth(name)
            if converted == name:
                continue
            item = RenameItem(kind=KIND_FOLDER, old=name, converted=converted)
            problem = name_problem(converted)
            if problem:
                item.status, item.reason = STATUS_FAIL, problem
            elif fold(converted) in dir_names:
                item.status, item.reason = STATUS_FAIL, REASON_FOLDER_EXISTS
            elif fold(converted) in file_names:
                item.status, item.reason = STATUS_FAIL, REASON_OTHER_KIND_FOLDER
            else:
                item.new = converted
                dir_names.discard(fold(name))
                dir_names.add(fold(converted))
            result.items.append(item)

    result.plan_id = _plan_id(result)
    return result


def _plan_id(p: RenamePlan) -> str:
    body = json.dumps([p.folder, p.rename_folders,
                       [[i.kind, i.old, i.new, i.status] for i in p.items]],
                      ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------
# 実行
# ------------------------------------------------------------------
def run(folder: Path, *, rename_folders: bool, plan_id: str,
        fold: Optional[Callable[[str], str]] = None,
        log: Optional[Callable[[str], None]] = None) -> RunResult:
    current = plan(folder, rename_folders=rename_folders, fold=fold)
    if current.plan_id != plan_id:
        raise PlanChanged(current)

    result = RunResult(folder=str(folder))
    for item in current.items:
        if item.status == STATUS_FAIL:
            result.outcomes.append(RenameOutcome(item.kind, item.old, item.converted, False,
                                                 item.reason))
            continue
        src, dst = folder / item.old, folder / item.new
        # 行き先を直前にもう一度確かめる(POSIX の os.rename は上書きしてしまう)
        if os.path.lexists(dst):
            outcome = RenameOutcome(item.kind, item.old, item.new, False, REASON_APPEARED)
        else:
            try:
                os.rename(src, dst)
                outcome = RenameOutcome(item.kind, item.old, item.new, True)
            except OSError as exc:
                # 開かれている・権限が無い・消えた など。VBA もここで失敗として数えた
                outcome = RenameOutcome(item.kind, item.old, item.new, False,
                                        exc.strerror or str(exc))
        result.outcomes.append(outcome)
        if log:
            state = "成功" if outcome.ok else f"失敗({outcome.reason})"
            log(f"リネーム{state}: {folder} / {item.old} → {item.new}")
    return result


def plan_to_dict(p: RenamePlan) -> dict:
    return {"folder": p.folder, "rename_folders": p.rename_folders,
            "plan_id": p.plan_id, "counts": p.counts(),
            "items": [asdict(i) for i in p.items]}


def result_to_dict(r: RunResult) -> dict:
    return {"folder": r.folder, "counts": r.counts(),
            "outcomes": [asdict(o) for o in r.outcomes]}
