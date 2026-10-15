/*
  画面の心拍と接続断の表示 (基盤仕様書 2.9)

  - 一定間隔で POST /api/alive。返事が無ければ帯を出す(黙って固まって見えるのを防ぐ)
  - 画面を閉じたら sendBeacon で /api/bye。アプリは少し待ってから終わる(再読込なら取り消される)
*/
const seconds = Number(document.querySelector('meta[name="heartbeat-seconds"]').content) || 20;

export function startHeartbeat(onState) {
  let online = true;
  async function beat() {
    let ok = false;
    try {
      const res = await fetch("/api/alive", { method: "POST" });
      ok = res.ok;
    } catch (e) { ok = false; }
    if (ok !== online) { online = ok; onState(ok); }
  }
  beat();
  setInterval(beat, seconds * 1000);
  // 裏に回っていたタブが戻ったときは、すぐに確かめる
  document.addEventListener("visibilitychange", () => { if (!document.hidden) beat(); });
  window.addEventListener("pagehide", () => {
    try { navigator.sendBeacon("/api/bye", new Blob(["{}"], { type: "application/json" })); } catch (e) { /* 何もしない */ }
  });
}
