/*
  表示中の一覧を印刷する(VER1.6.0)

  画面に出ている一覧(サーバが返したもの)を、並べ替えずに印刷用の紙面へ写して
  ブラウザの印刷を開く。取り直さないので、画面で見たものと紙が同じになる。
  紙面は A4 縦・見出し行はページごとに繰り返す(app.css の @media print)。
  ここは写すだけで、判断は持たない。
*/
import { HEADER } from "./copytable.js";

function esc(value) {
  return String(value ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/**
 * 紙面の中身(HTML の文字列)。list は /api/filelist の答え、無ければ null。
 * stale … 一覧を取ったあとでファイル名を直した(紙にもそう書く)
 */
export function buildPrintHtml(list, { stale = false, printedAt = "" } = {}) {
  if (!list || !list.rows || !list.rows.length) {
    return `<p class="p-empty">印刷する一覧がありません。「ファイル名取得」で一覧を出してから印刷してください。</p>`;
  }
  const notes = [];
  if (list.count > list.sorted_rows) notes.push(list.message);
  if (stale) notes.push("※ この一覧を取ったあとでファイル名を直しました。いまのフォルダとは違います。");
  const head = `<tr>${HEADER.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>`;
  const body = list.rows.map((r) => {
    const note = r.note ? `<span class="p-note">${esc(r.file_name)} … ${esc(r.note)}</span>` : "";
    return `<tr><td>${esc(r.doc_no)}</td><td>${esc(r.title)}${note}</td>`
      + `<td class="p-date">${esc(r.modified)}</td><td>${esc(r.ext)}</td></tr>`;
  }).join("");
  return `<h1>${esc(list.title)} の一覧</h1>`
    + `<p class="p-meta">フォルダ: ${esc(list.folder)} ／ 取得: ${esc(list.fetched_at)} ／ ${esc(list.count)} 件`
    + (printedAt ? ` ／ 印刷: ${esc(printedAt)}` : "") + `</p>`
    + notes.map((n) => `<p class="p-warn">${esc(n)}</p>`).join("")
    + `<table><colgroup><col class="c-no"><col class="c-title"><col class="c-date"><col class="c-ext"></colgroup>`
    + `<thead>${head}</thead><tbody>${body}</tbody></table>`;
}

function now() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${pad(d.getMinutes())}`;
}

/** 紙面を埋める。Ctrl+P で印刷したときも同じ紙面になるよう、beforeprint からも呼ぶ。 */
export function fillPrintSheet(sheet, list, options = {}) {
  sheet.innerHTML = buildPrintHtml(list, { ...options, printedAt: now() });
}
