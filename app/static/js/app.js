/*
  画面の操作。**判断はすべてサーバ**(一覧の分け方・並べ替え・リネームの可否)。
  ここは返ってきたものを表に写すだけ。
*/
import { ApiError, get, post } from "./api.js";
import { startHeartbeat } from "./health.js";
import { startErrorReport } from "./errors.js";
import { copyRows } from "./copytable.js";
import { fillPrintSheet } from "./printsheet.js";
import { showLogCount } from "./logcount.js";

const $ = (id) => document.getElementById(id);
const state = { listFolder: "", listRows: [], list: null, listStale: false, plan: null, planKey: "" };

function text(el, value) { el.textContent = value == null ? "" : String(value); }

function td(value, cls) {
  const cell = document.createElement("td");
  if (cls) cell.className = cls;
  text(cell, value);
  return cell;
}

function setStatus(id, message, kind) {
  const el = $(id);
  el.className = "status" + (kind ? " " + kind : "");
  text(el, message);
}

function notice(containerId, items) {
  const box = $(containerId);
  box.replaceChildren();
  for (const [kind, message] of items) {
    const p = document.createElement("div");
    p.className = "notice " + kind;
    text(p, message);
    box.appendChild(p);
  }
}

let toastTimer = 0;
function toast(message) {
  const el = $("toast");
  text(el, message);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

function showTab(name) {
  for (const key of ["list", "rename"]) {
    const on = key === name;
    $("tab-" + key).setAttribute("aria-selected", String(on));
    $("view-" + key).style.display = on ? "flex" : "none";
  }
}

function errorText(e) {
  return e instanceof ApiError ? e.message : "うまくいきませんでした。";
}

function busy(button, on) {
  button.disabled = on;
  button.setAttribute("aria-busy", String(on));
}

// ------------------------------------------------------------------
// 状態
// ------------------------------------------------------------------
async function loadState() {
  // 最後に使えたパスを入れておく(毎日同じフォルダを打たなくて済むように)
  const s = await get("/api/state");
  if (!$("list-folder").value) $("list-folder").value = s.list_dir;
  if (!$("rename-folder").value) $("rename-folder").value = s.rename_dir;
}

// 断りに「読んだパス」を添える。" が残っていた・別の場所を見ていた、が見て分かるように
function failText(e) {
  const folder = e && e.body && e.body.folder;
  return errorText(e) + (folder ? `\n読んだパス: ${folder}` : "");
}

// ------------------------------------------------------------------
// 1. 一覧
// ------------------------------------------------------------------
async function loadList() {
  const button = $("btn-list");
  busy(button, true);
  setStatus("list-status", "読んでいます…");
  showTab("list");
  try {
    const data = await get("/api/filelist?folder=" + encodeURIComponent($("list-folder").value));
    state.listFolder = data.folder;
    state.listRows = data.rows;
    state.list = data;
    state.listStale = false;
    renderList(data);
    $("btn-copy").disabled = data.count === 0;
    $("btn-print").disabled = data.count === 0;
    setStatus("list-status", `${data.count} 件を読みました(${data.fetched_at})。`, "ok");
  } catch (e) {
    $("list-table").hidden = true;
    $("list-head").hidden = true;
    $("list-empty").hidden = false;
    state.listFolder = "";
    state.listRows = [];
    state.list = null;
    state.listStale = false;
    $("btn-copy").disabled = true;
    $("btn-print").disabled = true;
    text($("list-empty"), failText(e));
    notice("list-notice", []);
    setStatus("list-status", errorText(e), "error");
  } finally {
    busy(button, false);
  }
}

function renderList(data) {
  $("list-head").hidden = false;
  text($("list-title"), `${data.title} の一覧`);
  text($("list-meta"), `${data.folder} ／ 取得 ${data.fetched_at} ／ ${data.count} 件`);
  const notes = [];
  if (data.count > data.sorted_rows) notes.push(["warn", data.message]);
  notice("list-notice", notes);

  const body = $("list-body");
  body.replaceChildren();
  data.rows.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.title = r.file_name;
    tr.append(td(i + 1, "num"), td(r.doc_no, "mono"));
    const title = td(r.title);
    if (r.note) {
      const n = document.createElement("span");
      n.className = "note";
      text(n, `${r.file_name} … ${r.note}`);
      title.appendChild(n);
    }
    tr.append(title, td(r.modified, "date"), td(r.ext, "mono"));
    body.appendChild(tr);
  });
  $("list-table").hidden = data.count === 0;
  $("list-empty").hidden = data.count !== 0;
  if (data.count === 0) text($("list-empty"), "このフォルダにファイルはありません。");
}


// ------------------------------------------------------------------
// 2. 全角→半角
// ------------------------------------------------------------------
function renameRequest() {
  return { folder: $("rename-folder").value, rename_folders: $("rename-folders").checked };
}

function requestKey(req) { return JSON.stringify(req); }

function clearPlan() {
  state.plan = null;
  state.planKey = "";
  $("btn-run").disabled = true;
  text($("btn-run"), "この内容で直す");
}

async function preview() {
  const req = renameRequest();
  const button = $("btn-preview");
  busy(button, true);
  clearPlan();
  showTab("rename");
  setStatus("rename-status", "フォルダを読んでいます…");
  try {
    const plan = await post("/api/rename/preview", req);
    renderPlan(plan);
    state.plan = plan;
    state.planKey = requestKey(req);
    const will = plan.counts.rename;
    $("btn-run").disabled = will === 0;
    text($("btn-run"), will ? `この内容で直す(${will} 件)` : "直すものはありません");
    setStatus("rename-status", will ? "左の一覧を確かめてから「この内容で直す」を押してください。" : "", "");
  } catch (e) {
    renderRenameError(e);
  } finally {
    busy(button, false);
  }
}

function renderRenameError(e) {
  $("rename-table").hidden = true;
  $("rename-head").hidden = true;
  $("rename-empty").hidden = false;
  text($("rename-empty"), failText(e));
  notice("rename-notice", []);
  setStatus("rename-status", errorText(e), "error");
}

const STATUS_LABEL = { rename: "直す", numbered: "番号を付けて直す", fail: "直せない" };
const KIND_LABEL = { file: "ファイル", folder: "フォルダ" };

function renderPlan(plan) {
  $("rename-head").hidden = false;
  text($("rename-title"), "変わる名前(まだ変えていません)");
  const c = plan.counts;
  text($("rename-meta"), `${plan.folder} ／ 直す ${c.rename} 件(うち番号付き ${c.numbered} 件)／ 直せない ${c.fail} 件`);
  const notes = [];
  if (c.total === 0) notes.push(["info", "全角の英数字・記号を含む名前はありません。"]);
  if (c.fail) notes.push(["warn", `直せない ${c.fail} 件は、そのまま残します(理由は「扱い」の欄)。`]);
  notice("rename-notice", notes);
  fillRenameTable(plan.items.map((i) => ({
    kind: i.kind, old: i.old, shown: i.status === "fail" ? i.converted : i.new,
    pill: i.status, label: STATUS_LABEL[i.status], reason: i.reason,
  })));
}

function fillRenameTable(rows) {
  const body = $("rename-body");
  body.replaceChildren();
  rows.forEach((r, idx) => {
    const tr = document.createElement("tr");
    const arrow = td("→", "arrow");
    const status = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = "pill " + r.pill;
    text(pill, r.label);
    status.appendChild(pill);
    if (r.reason) {
      const n = document.createElement("span");
      n.className = "note";
      text(n, r.reason);
      status.appendChild(n);
    }
    tr.append(td(idx + 1, "num"), td(KIND_LABEL[r.kind], "kind"), td(r.old, "mono"), arrow, td(r.shown, "mono"), status);
    body.appendChild(tr);
  });
  $("rename-table").hidden = rows.length === 0;
  $("rename-empty").hidden = rows.length !== 0;
  if (rows.length === 0) text($("rename-empty"), "直すものはありません。");
}

async function runRename() {
  if (!state.plan) return;
  const req = renameRequest();
  if (requestKey(req) !== state.planKey) {
    clearPlan();
    setStatus("rename-status", "フォルダかチェックが下見のときと変わりました。もう一度「変わる名前を見る」を押してください。", "error");
    return;
  }
  const button = $("btn-run");
  busy(button, true);
  setStatus("rename-status", "直しています…");
  try {
    const result = await post("/api/rename/run", { ...req, plan_id: state.plan.plan_id });
    clearPlan();
    renderResult(result);
    if (result.counts.ok && !$("list-table").hidden) {
      // 名前が変わったので、出ている一覧は古い。黙って古いものを見せない(印刷にも書く)
      state.listStale = true;
      notice("list-notice", [["warn", "ファイル名を直したので、この一覧は古くなっています。「ファイル名取得」を押し直してください。"]]);
    }
    const c = result.counts;
    setStatus("rename-status", `直しました: 成功 ${c.ok} 件 / 失敗 ${c.fail} 件`, c.fail ? "error" : "ok");
    toast(`ファイル名を直しました(成功 ${c.ok} 件 / 失敗 ${c.fail} 件)`);
  } catch (e) {
    if (e.code === "plan_changed" && e.body.plan) {
      // 下見のあとで別のPCが変えた。新しい計画を見せて、押し直してもらう
      renderPlan(e.body.plan);
      state.plan = e.body.plan;
      state.planKey = requestKey(req);
      const will = e.body.plan.counts.rename;
      button.disabled = will === 0;
      text(button, will ? `この内容で直す(${will} 件)` : "直すものはありません");
      setStatus("rename-status", e.message, "error");
      return;
    }
    clearPlan();
    setStatus("rename-status", errorText(e), "error");
  } finally {
    button.setAttribute("aria-busy", "false");
  }
}

function renderResult(result) {
  $("rename-head").hidden = false;
  text($("rename-title"), "直した結果");
  const c = result.counts;
  text($("rename-meta"), `${result.folder} ／ 成功 ${c.ok} 件 ／ 失敗 ${c.fail} 件`);
  notice("rename-notice", c.fail ? [["warn", "失敗したものは元の名前のままです。理由は「扱い」の欄を見てください。"]]
    : [["ok", "すべて直しました。"]]);
  fillRenameTable(result.outcomes.map((o) => ({
    kind: o.kind, old: o.old, shown: o.new, pill: o.ok ? "ok" : "fail",
    label: o.ok ? "直した" : "失敗", reason: o.reason,
  })));
}

// ------------------------------------------------------------------
async function exitApp() {
  try {
    await post("/api/shutdown", {});
    document.body.replaceChildren();
    const p = document.createElement("p");
    p.style.padding = "40px";
    text(p, "終了しました。この画面は閉じてかまいません。");
    document.body.appendChild(p);
  } catch (e) {
    toast(errorText(e));
  }
}

async function copyList() {
  // 画面に出ている一覧そのもの(取り直さない)。並びも画面と同じ
  const rows = state.listRows;
  if (!rows.length) return;
  if (await copyRows(rows)) {
    setStatus("list-status", `${rows.length} 件をコピーしました。Excel に貼ると列に分かれます。`, "ok");
    toast(`一覧 ${rows.length} 件をコピーしました`);
  } else {
    setStatus("list-status", "コピーできませんでした。一覧を選んで Ctrl+C でコピーしてください。", "error");
  }
}

function fillPrint() {
  fillPrintSheet($("print-sheet"), state.list, { stale: state.listStale });
}

function printList() {
  // 画面に出ている一覧そのもの(取り直さない)。並びも画面と同じ
  if (!state.listRows.length) return;
  fillPrint();
  window.print();
  setStatus("list-status", `${state.listRows.length} 件の一覧を印刷に回しました。`, "ok");
}

function wire() {
  $("tab-list").onclick = () => showTab("list");
  $("tab-rename").onclick = () => showTab("rename");
  $("btn-list").onclick = loadList;
  $("btn-copy").onclick = copyList;
  $("btn-print").onclick = printList;
  // Ctrl+P で印刷しても同じ紙面に(一覧が無ければ理由を印刷する。真っ白な紙にしない)
  window.addEventListener("beforeprint", fillPrint);
  $("list-folder").addEventListener("keydown", (ev) => { if (ev.key === "Enter") loadList(); });
  $("btn-preview").onclick = preview;
  $("btn-run").onclick = runRename;
  $("rename-folder").addEventListener("input", clearPlan);
  $("rename-folder").addEventListener("keydown", (ev) => { if (ev.key === "Enter") preview(); });
  $("rename-folders").addEventListener("change", clearPlan);
  $("btn-exit").onclick = exitApp;
  $("btn-reload").onclick = () => location.reload();
}

wire();
startErrorReport(toast);
showLogCount();
startHeartbeat((online) => { $("offline").hidden = online; });
loadState().catch((e) => setStatus("list-status", errorText(e), "error"));
