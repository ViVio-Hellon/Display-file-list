/*
  画面の操作。**判断はすべてサーバ**(一覧の分け方・並べ替え・リネームの可否)。
  ここは返ってきたものを表に写すだけ。
*/
import { ApiError, get, post, token } from "./api.js";
import { startHeartbeat } from "./health.js";

const $ = (id) => document.getElementById(id);
const state = { groups: [], baseDir: "", plan: null, planKey: "" };

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
  const s = await get("/api/state");
  state.groups = s.groups;
  applyBase(s);
  const box = $("groups");
  box.replaceChildren();
  s.groups.forEach((g, i) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "group";
    input.value = g.key;
    input.id = "group-" + (g.key || "base");
    // VBA: どのオプションボタンも選ばなければ基準フォルダ。既定は基準フォルダにしておく
    if (g.key === "") input.checked = true;
    label.append(input, document.createTextNode(g.label));
    box.appendChild(label);
  });
}

function applyBase(s) {
  // VBA の T2 は初めから「ThisWorkbook.Path」が入っていた。直すフォルダが空なら基準フォルダを入れる
  const renameInput = $("rename-folder");
  if (!renameInput.value || renameInput.value === state.baseDir) renameInput.value = s.base_dir;
  state.baseDir = s.base_dir;
  const fact = $("fact-base");
  text($("fact-base-text"), s.base_dir + (s.base_dir_default ? "(アプリのフォルダ)" : ""));
  fact.classList.toggle("alert", !s.base_dir_ok);
  fact.title = s.base_dir_ok ? s.base_dir : "このフォルダはこのPCから見えません";
  $("base-dir").value = s.base_dir_default ? "" : s.base_dir;
  $("base-dir").placeholder = s.base_dir_default ? s.base_dir : "";
}

function selectedGroup() {
  const checked = document.querySelector('input[name="group"]:checked');
  return checked ? checked.value : "";
}

function groupLabel(key) {
  const g = state.groups.find((x) => x.key === key);
  return g ? g.label : "";
}

function joinPath(base, name) {
  if (!name) return base;
  const sep = base.includes("\\") || /^[A-Za-z]:/.test(base) ? "\\" : "/";
  return base.replace(/[\\/]+$/, "") + sep + name;
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
    const data = await get("/api/filelist?group=" + encodeURIComponent(selectedGroup()));
    renderList(data);
    setStatus("list-status", `${data.count} 件を読みました(${data.fetched_at})。`, "ok");
    $("btn-print").disabled = false;
  } catch (e) {
    $("btn-print").disabled = true;
    $("list-table").hidden = true;
    $("list-head").hidden = true;
    $("list-empty").hidden = false;
    text($("list-empty"), errorText(e) + (e.body && e.body.folder ? `\n${e.body.folder}` : ""));
    notice("list-notice", []);
    setStatus("list-status", errorText(e), "error");
  } finally {
    busy(button, false);
  }
}

function renderList(data) {
  $("list-head").hidden = false;
  text($("list-title"), `${data.group_label} の一覧`);
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

function openPrint() {
  const url = "/print?group=" + encodeURIComponent(selectedGroup()) + "&t=" + encodeURIComponent(token());
  const w = window.open(url, "_blank");
  if (!w) toast("別の窓を開けませんでした。ブラウザのポップアップの設定を確かめてください。");
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
  text($("rename-empty"), errorText(e) + (e.body && e.body.folder ? `\n${e.body.folder}` : ""));
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
      // 名前が変わったので、出ている一覧は古い。黙って古いものを見せない
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
// 3. 基準フォルダ
// ------------------------------------------------------------------
async function saveBase() {
  const button = $("btn-base-save");
  busy(button, true);
  try {
    const s = await post("/api/settings", { base_dir: $("base-dir").value });
    applyBase(s);
    setStatus("base-status", "保存しました。", "ok");
  } catch (e) {
    setStatus("base-status", errorText(e), "error");
  } finally {
    busy(button, false);
  }
}

// ------------------------------------------------------------------
// フォルダ参照
// ------------------------------------------------------------------
let browseTarget = null;
let browseCurrent = "";

async function openBrowse(inputId) {
  browseTarget = $(inputId);
  $("browse").showModal();
  await browseTo(browseTarget.value || browseTarget.placeholder || state.baseDir);
}

async function browseTo(path) {
  try {
    const v = await get("/api/fs/list?path=" + encodeURIComponent(path || ""));
    browseCurrent = v.exists ? v.path : "";
    text($("browse-path"), v.path || "(未選択)");
    text($("browse-msg"), v.message || "");
    $("browse-up").disabled = !v.parent;
    $("browse-up").onclick = () => browseTo(v.parent);
    $("browse-ok").disabled = !v.exists;
    const roots = $("browse-roots");
    roots.replaceChildren();
    for (const r of v.roots) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn small";
      text(b, r.name);
      b.onclick = () => browseTo(r.path);
      roots.appendChild(b);
    }
    const list = $("browse-list");
    list.replaceChildren();
    for (const d of v.dirs) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      text(b, "📁 " + d.name);
      b.onclick = () => browseTo(d.path);
      li.appendChild(b);
      list.appendChild(li);
    }
  } catch (e) {
    text($("browse-msg"), errorText(e));
  }
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

function wire() {
  $("tab-list").onclick = () => showTab("list");
  $("tab-rename").onclick = () => showTab("rename");
  $("btn-list").onclick = loadList;
  $("btn-print").onclick = openPrint;
  $("groups").addEventListener("change", () => { $("btn-print").disabled = true; });
  $("btn-preview").onclick = preview;
  $("btn-run").onclick = runRename;
  $("rename-folder").addEventListener("input", clearPlan);
  $("rename-folders").addEventListener("change", clearPlan);
  $("btn-rename-base").onclick = () => { $("rename-folder").value = state.baseDir; clearPlan(); };
  $("btn-rename-group").onclick = () => {
    const key = selectedGroup();
    $("rename-folder").value = key ? joinPath(state.baseDir, groupLabel(key)) : state.baseDir;
    clearPlan();
  };
  $("btn-rename-browse").onclick = () => openBrowse("rename-folder");
  $("btn-base-browse").onclick = () => openBrowse("base-dir");
  $("btn-base-save").onclick = saveBase;
  $("browse-cancel").onclick = () => $("browse").close();
  $("browse-ok").onclick = () => {
    if (browseTarget && browseCurrent) {
      browseTarget.value = browseCurrent;
      browseTarget.dispatchEvent(new Event("input"));
    }
    $("browse").close();
  };
  $("btn-exit").onclick = exitApp;
  $("btn-reload").onclick = () => location.reload();
}

wire();
startHeartbeat((online) => { $("offline").hidden = online; });
loadState().catch((e) => setStatus("list-status", errorText(e), "error"));
