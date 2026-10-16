// 一覧のコピーの中身。python -m unittest から node で動かす(tests/test_copy_table.py)
import { buildTsv, buildHtml, HEADER } from "../../app/static/js/copytable.js";

const rows = [
  { doc_no: "6-1", title: "梱包手順書", modified: "2026/10/15 14:56", ext: "xlsx" },
  { doc_no: "007-1", title: "A&B <改>", modified: "2026/1/2 8:05", ext: "pdf" },
  { doc_no: "", title: "手順書一覧", modified: "2026/10/15 14:56", ext: "docx" },
  { doc_no: "x", title: "タブ\tと改行\nが入った名前", modified: "", ext: "" },
];
const out = {
  header: HEADER,
  tsv: buildTsv(rows),
  tsvNoHeader: buildTsv(rows, { header: false }),
  html: buildHtml(rows),
};
console.log(JSON.stringify(out));
