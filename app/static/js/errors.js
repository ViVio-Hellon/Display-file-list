/*
  errors.js — 画面(ブラウザ)で起きたエラーを、サーバの記録へ届ける
  (日報管理ツールの app/static/js/errors.js を写したもの)

  画面の中で起きたエラーは、押した人の画面の奥でしか見えない。
    1. 直前に押したもの・選んだものを 15 件だけ覚えておく(パンくず)
    2. エラーが起きたら、パンくずを添えて /api/log/client へ送る
    3. 返ってきた番号を画面に出す

  送るのは押したボタンの名前だけ。打った値(フォルダのパス)は送らない。
*/
import { quietPost } from "./api.js";

const KEEP = 15;
const MAX_SEND = 20;
const HARMLESS = [/ResizeObserver loop/i, /^Script error\.?$/i];
const crumbs = [];
const recent = new Map();
let sent = 0;
let shown = false;
let notify = () => {};

function now() {
  return new Date().toTimeString().slice(0, 8);
}

function nameOf(el) {
  const text = (el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 30);
  return [text, el.id ? `#${el.id}` : ""].filter(Boolean).join(" ");
}

function remember(what) {
  crumbs.push(`${now()} ${what}`);
  if (crumbs.length > KEEP) crumbs.shift();
}

async function report(kind, message, where, stack) {
  if (sent >= MAX_SEND || HARMLESS.some((re) => re.test(message))) return;
  const key = `${message}@${where}`;
  if (Date.now() - (recent.get(key) || 0) < 10_000) return;
  recent.set(key, Date.now());
  sent += 1;
  const body = await quietPost("/api/log/client", {
    kind, message, where, stack: String(stack || "").slice(0, 6000),
    screen: location.pathname, crumbs: crumbs.slice(),
    version: document.querySelector('meta[name="app-version"]')?.content || "",
  });
  if (body && body.id && !shown) {
    shown = true;                       // 1回の読み込みで1度だけ知らせる
    notify(`画面でエラーが起きました(番号 ${body.id})。動きがおかしいときは、この番号を管理者に伝えてください。`);
  }
}

export function startErrorReport(onNotify) {
  if (onNotify) notify = onNotify;
  document.addEventListener("click", (event) => {
    const el = event.target.closest?.("button, a, [role=tab], input[type=checkbox]");
    if (el) remember(`押した: ${nameOf(el)}`);
  }, true);
  window.addEventListener("error", (event) => {
    const target = event.target;
    if (target && target !== window && (target.src || target.href)) {
      report("load", `読めなかった: ${target.src || target.href}`, "", "");
      return;
    }
    const where = event.filename
      ? `${event.filename.replace(location.origin, "")}:${event.lineno}:${event.colno}` : "";
    report("error", String(event.message || event.error || "エラー"), where, event.error && event.error.stack);
  }, true);
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    if (reason && reason.name === "ApiError") return;   // サーバがもう残している
    report("rejection", String((reason && reason.message) || reason || "失敗"), "", reason && reason.stack);
  });
}
