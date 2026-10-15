"""一覧の印刷 (VBA `PDFCREATE` の置き換え。移植計画 Q8 = (a))

VBA はシート「一覧」を `ExportAsFixedFormat` で PDF にしてブックの場所へ保存していた。
Web 版は**印刷用の HTML** を別の窓に出し、ブラウザの印刷から「PDF として保存」を選ぶ。
ダウンロードは使わない。

紙面の決めごと(python-web-tools `printing.py` と同じ):

- `@page { size: A4 portrait; margin: 6mm }` ── プリンターは紙の縁 4〜5mm に刷れない
- 見出し行はページごとに繰り返す(`thead { display: table-header-group }`)

【VBA との違い】
- VBA の PDF は **1ページ目だけ**(`From:=1, To:=1`)。ここでは全ページを出す。
  1ページ目だけにしたいときは、印刷画面の「ページ」で 1 を指定する
- VBA のシートには見出し行が無かった。紙で読めるように見出しとフォルダ・取得時刻を付ける
"""
from __future__ import annotations

import html

from ..core import config

CSS = """
@page { size: A4 portrait; margin: 6mm; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "BIZ UDPGothic", "Yu Gothic", "Meiryo", sans-serif;
       font-size: 10pt; color: #000; background: #fff; }
.bar { display: flex; gap: 8px; padding: 10px; background: #eef1f6; border-bottom: 1px solid #c9d0db; }
.bar button { font: inherit; padding: 6px 14px; border: 1px solid #8a94a6; border-radius: 4px;
              background: #fff; cursor: pointer; }
.bar button.primary { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.bar p { margin: 0 0 0 auto; align-self: center; color: #444; font-size: 9pt; }
.sheet { padding: 8mm 6mm; }
h1 { font-size: 13pt; margin: 0 0 2mm; }
.meta { font-size: 9pt; margin: 0 0 4mm; color: #222; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
thead { display: table-header-group; }
th, td { border: 0.3mm solid #555; padding: 1mm 1.5mm; text-align: left; vertical-align: top;
         overflow-wrap: anywhere; }
th { background: #e8e8e8; }
col.no { width: 22%; } col.title { width: 50%; } col.date { width: 18%; } col.ext { width: 10%; }
tr { break-inside: avoid; }
td.date { font-variant-numeric: tabular-nums; white-space: nowrap; }
@media print { .bar { display: none; } .sheet { padding: 0; } }
"""


def render(listing: dict) -> str:
    """`file_list_service.to_dict()` の結果から印刷用 HTML を作る。"""
    esc = html.escape
    rows = "\n".join(
        "<tr><td>{no}</td><td>{title}</td><td class=\"date\">{date}</td><td>{ext}</td></tr>".format(
            no=esc(r["doc_no"]), title=esc(r["title"]), date=esc(r["modified"]), ext=esc(r["ext"]))
        for r in listing["rows"])
    title = f"{listing['group_label']} 一覧"
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>{esc(title)} - {esc(config.display_name())}</title>
<style>{CSS}</style></head>
<body>
<div class="bar">
  <button type="button" class="primary" onclick="window.print()">印刷する</button>
  <button type="button" onclick="window.close()">閉じる</button>
  <p>PDF にするときは、印刷先で「PDF として保存」を選んでください。1ページ目だけにするときは、ページで 1 を指定します。</p>
</div>
<div class="sheet">
  <h1>{esc(title)}</h1>
  <p class="meta">フォルダ: {esc(listing['folder'])} ／ 取得: {esc(listing['fetched_at'])} ／ {esc(listing['message'])}</p>
  <table>
    <colgroup><col class="no"><col class="title"><col class="date"><col class="ext"></colgroup>
    <thead><tr><th>文書番号</th><th>名称</th><th>更新日時</th><th>拡張子</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
</div>
<script>window.addEventListener("load", function () {{ setTimeout(function () {{ window.print(); }}, 200); }});</script>
</body></html>"""


def render_error(message: str) -> str:
    """出せないときも HTML で返す(別窓が真っ白だと壊れているようにしか見えない)。"""
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>印刷できません</title><style>{CSS}</style></head>
<body><div class="sheet"><h1>印刷できません</h1><p>{html.escape(message)}</p>
<p><button type="button" onclick="window.close()">閉じる</button></p></div></body></html>"""
