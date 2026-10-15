"""VBA の「一覧」と Python の一覧を突き合わせる(移植計画 手順10)

手順:
  1. Excel 版で班を選んで「一覧取得」を押す
  2. `vba/照合用_一覧をCSVで書き出す.bas` をブックに取り込み、`ExportListToCsv` を実行する
     → ブックと同じフォルダに `一覧_照合用.csv` ができる
  3. 同じPCで:
       python scripts/compare_with_vba.py --csv "…\\一覧_照合用.csv" --folder "…\\A班"

Python 側は **VBA 互換モード**(直す前の VBA と同じ動き)で一覧を作って、行ごとに比べる。
そのうえで、直した版(Q2・Q3)との違いを「意図した違い」として別に出す。

戻り値: 0 = すべて一致 / 1 = 違いあり / 2 = 読めない
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import file_list_service as fls  # noqa: E402

DATE_FORMATS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S")


def read_vba_csv(path: Path) -> list:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [{"doc_no": r.get("文書番号", ""), "title": r.get("名称", ""),
             "modified": r.get("更新日時", ""), "ext": r.get("拡張子", "")} for r in rows]


def _parse_date(text: str):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


def _hint(field: str, vba: str, py: str) -> str:
    if field == "title" and (re.fullmatch(r"[0-9.]+", py) or re.fullmatch(r"\d{1,4}-\d{1,2}(-\d{1,2})?", py)):
        return "K7: Excel がセルを数値か日付に変えた可能性(Python は文字のまま)"
    if field == "modified":
        return "時刻の違い。共有フォルダでは秒が丸められることがある"
    return ""


def compare(vba_rows: list, py_rows: list) -> list:
    """違いの一覧 [(行番号, 項目, VBA, Python, 手がかり)]"""
    diffs = []
    for i in range(max(len(vba_rows), len(py_rows))):
        v = vba_rows[i] if i < len(vba_rows) else None
        p = py_rows[i] if i < len(py_rows) else None
        if v is None or p is None:
            diffs.append((i + 1, "行", "(無い)" if v is None else "あり",
                          "(無い)" if p is None else p.file_name, "行の数が違う"))
            continue
        blank = p.parsed.blank_row
        py = {"doc_no": p.parsed.doc_no, "title": p.parsed.title, "ext": p.parsed.ext}
        for field in ("doc_no", "title", "ext"):
            if v[field] != py[field]:
                diffs.append((i + 1, field, v[field], py[field], _hint(field, v[field], py[field])))
        if blank:
            if v["modified"].strip():
                diffs.append((i + 1, "modified", v["modified"], "", "空行のはず(_ が2つ以上)"))
            continue
        vd = _parse_date(v["modified"])
        if vd is None or abs((vd - p.modified).total_seconds()) > 1:
            diffs.append((i + 1, "modified", v["modified"], p.modified.strftime("%Y/%m/%d %H:%M:%S"),
                          _hint("modified", "", "")))
    return diffs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", required=True, type=Path, help="VBA から書き出した 一覧_照合用.csv")
    ap.add_argument("--folder", required=True, type=Path, help="VBA で一覧を取ったフォルダ")
    args = ap.parse_args(argv)

    try:
        vba_rows = read_vba_csv(args.csv)
        entries = fls.scan_files(args.folder)
    except OSError as exc:
        print(f"読めません: {exc}")
        return 2
    # VBA は最後の行を消さない限り、空行の後ろにも何も書かない。末尾の空行はそろえて落とす
    while vba_rows and not any(vba_rows[-1].values()):
        vba_rows.pop()

    try:
        strict = fls.build_rows(entries, strict_vba=True)
    except fls.VbaWouldStop as exc:
        print(f"このフォルダでは VBA は途中で止まります(実行時エラー9): {exc.file_name}")
        print("Python の直した版は止まらずに一覧を作ります(移植計画 Q3)。")
        return 1
    py_rows = list(strict)
    while py_rows and py_rows[-1].parsed.blank_row:
        py_rows.pop()

    diffs = compare(vba_rows, py_rows)
    print(f"VBA {len(vba_rows)} 行 / Python(VBA 互換){len(py_rows)} 行")
    if diffs:
        print(f"違い {len(diffs)} か所:")
        for row, field, v, p, hint in diffs:
            print(f"  {row} 行目 {field}: VBA「{v}」 / Python「{p}」 {hint}")
    else:
        print("VBA 互換モードの結果は、VBA の一覧とすべて一致しました。")

    fixed = {r.file_name: r for r in fls.build_rows(entries)}
    changed = [r for r in strict if r.parsed.blank_row]
    if changed:
        print(f"\n意図した違い(Q2: _ が2つ以上。VBA では空行、直した版では一覧に出る) {len(changed)} 件:")
        for r in changed:
            f = fixed[r.file_name].parsed
            print(f"  {r.file_name} → 文書番号「{f.doc_no}」 名称「{f.title}」 拡張子「{f.ext}」")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
