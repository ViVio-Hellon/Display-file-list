/*
  表示中の一覧をクリップボードへ(Excel に貼ると列に分かれる)

  クリップボードには2つの形を入れる。
    text/html  … 表。Excel はこちらを読む。文書番号・名称・拡張子のセルに
                 「文字列」の印(mso-number-format:"\@")を付けるので、
                 6-1 が「6月1日」に、007 が 7 に化けない
    text/plain … タブ区切り。メモ帳などに貼るとき

  ここは一覧の行(サーバが返したもの)を並べ替えずに写すだけ。判断は持たない。
*/

export const HEADER = ["文書番号", "名称", "更新日時", "拡張子"];
// フォルダの一覧(VER1.7.0)には拡張子が無いので、その列を出さない
export const FOLDER_HEADER = ["文書番号", "名称", "更新日時"];

/** 一覧にしたもの(サーバの答えの target)で列が決まる。 */
export function headerFor(target) {
  return target === "folders" ? FOLDER_HEADER : HEADER;
}

function cells(row, target) {
  const all = [row.doc_no, row.title, row.modified, row.ext];
  return target === "folders" ? all.slice(0, 3) : all;
}

// タブと改行はセルの区切りになってしまうので空白に(Windows のファイル名には無いが念のため)
function plain(value) {
  return String(value ?? "").replace(/[\t\r\n]+/g, " ");
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

export function buildTsv(rows, { header = true, target = "files" } = {}) {
  const lines = header ? [headerFor(target).join("\t")] : [];
  for (const row of rows) lines.push(cells(row, target).map(plain).join("\t"));
  return lines.join("\r\n") + "\r\n";
}

const TEXT = ' style="mso-number-format:\'\\@\'"';             // Excel: 文字列
const DATE = ' style="mso-number-format:\'yyyy\\/m\\/d h:mm\'"';  // Excel: 日時

export function buildHtml(rows, { header = true, target = "files" } = {}) {
  const head = header ? `<tr>${headerFor(target).map((h) => `<th>${esc(h)}</th>`).join("")}</tr>` : "";
  const body = rows.map((row) => {
    const [no, title, modified, ext] = cells(row, target);
    return `<tr><td${TEXT}>${esc(no)}</td><td${TEXT}>${esc(title)}</td>`
      + `<td${DATE}>${esc(modified)}</td>`
      + (target === "folders" ? "" : `<td${TEXT}>${esc(ext)}</td>`) + `</tr>`;
  }).join("");
  return `<html><head><meta charset="utf-8"></head><body><table>${head}${body}</table></body></html>`;
}

/** クリップボードへ。押した操作の中で呼ぶ。成功すれば true。 */
export async function copyRows(rows, options) {
  const tsv = buildTsv(rows, options);
  const html = buildHtml(rows, options);
  // 1. copy イベントで2つの形を入れる(許可を求められず、Edge / Chrome で確実)
  let done = false;
  const onCopy = (event) => {
    event.clipboardData.setData("text/plain", tsv);
    event.clipboardData.setData("text/html", html);
    event.preventDefault();
    done = true;
  };
  document.addEventListener("copy", onCopy, { once: true });
  try {
    document.execCommand("copy");
  } catch (e) {
    done = false;
  } finally {
    document.removeEventListener("copy", onCopy);
  }
  if (done) return true;
  // 2. だめなら新しい口で
  try {
    if (window.ClipboardItem && navigator.clipboard?.write) {
      await navigator.clipboard.write([new ClipboardItem({
        "text/plain": new Blob([tsv], { type: "text/plain" }),
        "text/html": new Blob([html], { type: "text/html" }),
      })]);
      return true;
    }
    await navigator.clipboard.writeText(tsv);
    return true;
  } catch (e) {
    return false;
  }
}
