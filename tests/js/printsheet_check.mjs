// 一覧の印刷の紙面。python -m unittest から node で動かす(tests/test_print_sheet.py)
import { buildPrintHtml } from "../../app/static/js/printsheet.js";

const list = {
  folder: "C:\\現場\\A班", title: "A班", fetched_at: "2026/10/16 9:12", count: 3, sorted_rows: 3,
  message: "3 件",
  rows: [
    { file_name: "6-1_梱包手順書.xlsx", doc_no: "6-1", title: "梱包手順書", modified: "2026/10/15 14:56", ext: "xlsx", note: "" },
    { file_name: "007-1_A&B <改>.pdf", doc_no: "007-1", title: "A&B <改>", modified: "2026/1/2 8:05", ext: "pdf", note: "" },
    { file_name: "abc_", doc_no: "abc", title: "", modified: "2026/1/2 8:05", ext: "", note: "名前が _ で終わっている" },
  ],
};
const over = { ...list, count: 301, sorted_rows: 300, message: "301 件(先頭 300 件だけ並べ替えています。)" };
console.log(JSON.stringify({
  normal: buildPrintHtml(list, { printedAt: "2026/10/16 9:30" }),
  stale: buildPrintHtml(list, { stale: true }),
  over: buildPrintHtml(over),
  empty: buildPrintHtml(null),
  zero: buildPrintHtml({ ...list, rows: [], count: 0 }),
}));
