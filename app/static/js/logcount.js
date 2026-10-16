/*
  上の帯の「ログ」に、この2日のまだ対策済にしていないエラーの数を出す。
  出力先に書けていないときも、ここで気づけるように印を付ける。
*/
import { get } from "./api.js";

export async function showLogCount() {
  const badge = document.getElementById("log-count");
  const link = document.getElementById("link-logs");
  if (!badge || !link) return;
  try {
    const s = await get("/api/log/summary");
    badge.hidden = !s.open_errors && !s.problem;
    badge.textContent = s.open_errors ? `エラー${s.open_errors}件` : "出力先に書けません";
    link.title = s.problem || (s.open_errors ? "まだ対策済にしていないエラーがあります" : "");
  } catch (e) {
    badge.hidden = true;
  }
}
