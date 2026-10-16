/*
  logs.js — ログの面(日報管理ツールの views/logs.js を写したもの)

  並べるだけ。何を一覧に出すか・経過をどこまで拾うか・シートの形はサーバ
  (app/core/event_rules.py)が決める。ここは受け取って描く。
*/
import { ApiError, get, post } from "./api.js";
import { startHeartbeat } from "./health.js";
import { startErrorReport } from "./errors.js";

const $ = (id) => document.getElementById(id);
let openId = "";

function el(tag, attrs = {}, text = "") {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  if (text) node.textContent = text;
  return node;
}

let toastTimer = 0;
function toast(message) {
  const t = $("toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
}

function setMsg(id, text, kind) {
  const box = $(id);
  box.className = "status" + (kind ? " " + kind : "");
  box.textContent = text || "";
}

function errText(e) {
  const folder = e && e.body && e.body.folder;
  return (e instanceof ApiError ? e.message : "うまくいきませんでした。") + (folder ? `\n読んだパス: ${folder}` : "");
}

function isoDay(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function kv(box, items) {
  box.replaceChildren(...items.flatMap((item) => [el("dt", {}, item.label), el("dd", {}, item.value)]));
}

function fillSelect(select, items, keep) {
  const before = keep ?? select.value;
  select.replaceChildren(...items.map(([value, label]) => {
    const opt = el("option", { value }, label);
    if (value === before) opt.selected = true;
    return opt;
  }));
}

// ------------------------------------------------------------------
// 出力先
// ------------------------------------------------------------------
function paintStatus(s) {
  kv($("dir-status"), [
    { label: "出力先", value: s.is_default ? `${s.dir}(この端末の logs)` : s.dir },
    { label: "いま書いている所", value: s.writing_to },
    { label: "文字のログ", value: s.text_dir },
    { label: "この端末", value: s.terminal },
    { label: "残す日数", value: `${s.keep_days} 日(古いぶんは起動のたびに、この端末のものだけ消します)` },
  ]);
  const problem = s.fallback || s.text_problem;
  $("dir-problem").hidden = !problem;
  $("dir-problem").textContent = problem
    ? `${problem} ── いまはこの端末の ${s.default_dir} へ書いています。5分ごとに出力先を試し、届けば元の先へ戻ります。` : "";
  if (document.activeElement !== $("log-dir")) $("log-dir").value = s.setting || "";
}

async function saveDir(value) {
  setMsg("dir-msg", "保存しています…");
  try {
    const s = await post("/api/log/settings", { log_dir: value });
    paintStatus(s);
    $("log-dir").value = s.setting || "";
    setMsg("dir-msg", s.message, "ok");
    loadList();
  } catch (e) {
    setMsg("dir-msg", errText(e), "error");
  }
}

// ------------------------------------------------------------------
// 一覧
// ------------------------------------------------------------------
function filters() {
  return { start: $("log-start").value, end: $("log-end").value,
           scope: $("log-scope").value || "errors", terminal: $("log-terminal").value,
           q: $("log-q").value.trim() };
}

function kindBadge(row) {
  const cls = { error: "alert", client: "alert", warn: "todo", refused: "todo" }[row.kind] || "";
  return el("span", { class: `badge ${cls}`.trim() }, row.kind_label);
}

function statusBadge(row) {
  if (!row.status_label) {
    return (row.kind === "error" || row.kind === "client") ? el("span", { class: "badge todo" }, "未") : el("span");
  }
  return el("span", { class: `badge ${row.status === "done" ? "done" : "todo"}` }, row.status_label);
}

function paintList(body) {
  paintStatus(body.status || {});
  fillSelect($("log-scope"), (body.scopes || []).map((s) => [s.key, s.label]), body.filters?.scope);
  fillSelect($("log-terminal"), [["", "全部"], ...(body.terminals || []).map((t) => [t, t])], body.filters?.terminal);
  if (!$("log-start").value) $("log-start").value = body.start;
  if (!$("log-end").value) $("log-end").value = body.end;
  const c = body.counts || {};
  $("log-counts").textContent = `${body.start} 〜 ${body.end}: エラー ${c.errors ?? 0} 件 / `
    + `エラー・警告・断り ${c.problems ?? 0} 件 / 操作も全部 ${c.all ?? 0} 件 ── ${(body.rows || []).length} 件を表示`;
  const rows = body.rows || [];
  const tbody = $("log-rows");
  if (!rows.length) {
    const tr = el("tr");
    tr.append(el("td", { colspan: "7", class: "empty" }, "この期間・この絞り込みでは記録がありません"));
    tbody.replaceChildren(tr);
    return;
  }
  tbody.replaceChildren(...rows.map((row) => {
    const tr = el("tr", { class: "log-row", tabindex: "0", dataset: { id: row.id }, "aria-label": `${row.id} を開く` });
    if (row.id === openId) tr.classList.add("is-open");
    const idCell = el("td");
    idCell.append(el("code", {}, row.id));
    const kindCell = el("td");
    kindCell.append(kindBadge(row));
    if (row.count) kindCell.append(el("span", { title: row.count }, " ＋"));
    const statusCell = el("td");
    statusCell.append(statusBadge(row));
    tr.append(el("td", { class: "date" }, row.at), idCell, kindCell, el("td", {}, row.terminal),
              el("td", {}, row.label), el("td", { class: "msg", title: row.message }, row.message), statusCell);
    return tr;
  }));
}

async function loadList() {
  const query = new URLSearchParams(Object.entries(filters()).filter(([, v]) => v)).toString();
  try {
    paintList(await get(`/api/log/events?${query}`));
    setMsg("log-msg", "");
  } catch (e) {
    setMsg("log-msg", errText(e), "error");
  }
}

async function exportCsv() {
  try {
    const body = await post("/api/log/csv", filters());
    setMsg("log-msg", body.message, "ok");
  } catch (e) {
    setMsg("log-msg", errText(e), "error");
  }
}

// ------------------------------------------------------------------
// なぜなぜシート
// ------------------------------------------------------------------
function paintSheet(sheet, body = {}) {
  openId = sheet.id;
  $("log-sheet").hidden = false;
  $("ls-id").textContent = sheet.id;
  kv($("ls-facts"), sheet.facts || []);
  kv($("ls-cause"), sheet.cause?.length ? sheet.cause : [{ label: "記録", value: "例外はありません(断り・警告・記録)" }]);
  kv($("ls-state"), sheet.state || []);
  $("ls-steps").replaceChildren(...(sheet.steps || []).map((step) => {
    const li = el("li", {}, step.text);
    if (step.is_target) li.classList.add("is-target");
    return li;
  }));
  const input = Object.entries(sheet.input || {});
  $("ls-input-box").hidden = !input.length;
  kv($("ls-input"), input.map(([label, value]) => ({ label, value })));
  const crumbs = sheet.crumbs || [];
  $("ls-crumbs-box").hidden = !crumbs.length;
  $("ls-crumbs").replaceChildren(...crumbs.map((c) => el("li", {}, c)));
  $("ls-trace-box").hidden = !sheet.trace;
  $("ls-trace").textContent = sheet.trace || "";
  $("ls-hint").textContent = sheet.hint ? `手がかり(記録から): ${sheet.hint}` : "";

  const a = sheet.analysis || {};
  const count = body.why_count || (a.whys || []).length || 5;
  $("ls-whys").replaceChildren(...Array.from({ length: count }, (_, i) => {
    const li = el("li", { class: "field" });
    const id = `ls-why-${i}`;
    li.append(el("label", { for: id }, i === 0 ? "なぜ1 ── なぜそれが起きたか" : `なぜ${i + 1} ── なぜ${i}の答えは、なぜそうなったか`));
    const area = el("textarea", { id, rows: "2", maxlength: "400", "data-why": String(i) });
    area.value = (a.whys || [])[i] || "";
    li.append(area);
    return li;
  }));
  $("ls-measure").value = a.measure || "";
  if (body.statuses) fillSelect($("ls-status"), body.statuses.map((s) => [s.key, s.label]), a.status || "open");
  $("ls-status").value = a.status || "open";
  $("ls-by").value = a.by || "";
  $("ls-saved").textContent = a.at ? `前に残したもの: ${a.at.replace("T", " ")}(${a.terminal || ""})` : "まだ書いていません";
  for (const tr of document.querySelectorAll(".log-row")) tr.classList.toggle("is-open", tr.dataset.id === openId);
}

async function openSheet(id) {
  try {
    const body = await get(`/api/log/event?id=${encodeURIComponent(id)}`);
    paintSheet(body.sheet, body);
    $("log-sheet").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    toast(errText(e));
  }
}

async function saveSheet() {
  if (!openId) return;
  const whys = [...document.querySelectorAll("#ls-whys [data-why]")].map((t) => t.value);
  try {
    const body = await post("/api/log/event/analysis", {
      id: openId, whys, measure: $("ls-measure").value, status: $("ls-status").value, by: $("ls-by").value,
    });
    paintSheet(body.sheet);
    toast(body.message);
    loadList();
  } catch (e) {
    toast(errText(e));
  }
}

function start() {
  const today = new Date();
  const from = new Date(today);
  from.setDate(today.getDate() - 6);
  $("log-start").value = isoDay(from);
  $("log-end").value = isoDay(today);

  $("btn-dir-save").onclick = () => saveDir($("log-dir").value);
  $("btn-dir-local").onclick = () => saveDir("");
  $("log-dir").addEventListener("keydown", (ev) => { if (ev.key === "Enter") saveDir($("log-dir").value); });
  $("log-reload").onclick = loadList;
  for (const id of ["log-scope", "log-terminal", "log-start", "log-end"]) $(id).addEventListener("change", loadList);
  $("log-q").addEventListener("keydown", (ev) => { if (ev.key === "Enter") loadList(); });
  $("log-csv").onclick = exportCsv;
  $("log-rows").addEventListener("click", (ev) => {
    const tr = ev.target.closest(".log-row");
    if (tr) openSheet(tr.dataset.id);
  });
  $("log-rows").addEventListener("keydown", (ev) => {
    const tr = ev.target.closest(".log-row");
    if (tr && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      openSheet(tr.dataset.id);
    }
  });
  $("ls-close").onclick = () => {
    $("log-sheet").hidden = true;
    openId = "";
    for (const tr of document.querySelectorAll(".log-row")) tr.classList.remove("is-open");
  };
  $("ls-save").onclick = saveSheet;
  $("btn-reload").onclick = () => location.reload();

  // 番号を添えて開かれたとき(/logs?id=E1016-…。エラーの頁のリンク)は、その1件を出す
  const wanted = new URLSearchParams(location.search).get("id");
  if (wanted) {
    $("log-q").value = wanted;
    fillSelect($("log-scope"), [["all", "操作も全部"]], "all");   // 番号の1件は種類を問わず出す
    openSheet(wanted);
  }
  loadList();
}

startErrorReport(toast);
startHeartbeat((online) => { $("offline").hidden = online; });
start();
