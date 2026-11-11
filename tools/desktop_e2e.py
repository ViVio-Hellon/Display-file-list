#!/usr/bin/env python3
"""デスクトップ版(exe)を窓の中で操作する通し試験(開発機の Linux)

    xvfb-run -a python tools/desktop_e2e.py --exe src-tauri/target/debug/FileListTool

本物の exe を起動し、WebDriver(tauri-driver + WebKitWebDriver)で窓を操作する。
ブラウザ版の画面とまったく同じもの(Python が返す画面・同じ JS)が窓で動くことを確かめる。
置き場所は使い捨てのフォルダに分ける。標準ライブラリだけ(WebDriver は urllib で話す)。

【確かめること】
1. 一覧(ファイル / フォルダの選択)・一覧をコピー・一覧を印刷(紙面ができる)
2. 全角→半角(下見 → 実行で、ディスクの名前が本当に変わる)
3. 上の帯の「ログ」で画面が移り、戻れる。静的ファイル(CSS・JS)は外枠が返している
4. 画面の「終了」で exe も Python も終わる
5. 窓の ×(ウィンドウマネージャと同じ WM_DELETE_WINDOW)で exe も Python も終わる
6. ブラウザ版が動いているときは、窓に理由が出る

【要るもの】(現場の PC には要らない)
    tauri-driver(cargo install tauri-driver)・Xvfb・xdotool・WebKitWebDriver(webkit2gtk-driver)
WebDriver の検査口(127.0.0.1:4444)は試験の道具だけが使う(アプリは待ち受けない。
それは scripts/desktop_smoke.py が WebDriver なしで確かめる)。
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from desktop_smoke import alive, isolated_env, kill_tree, launcher_log, marker, wait_for  # noqa: E402

WD_PORT = 4444
TITLE = "ファイル名一覧取得"                    # src-tauri/src/main.rs の TITLE
ELEMENT = "element-6066-11e4-a52e-4f735466cecf"
results: list = []
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(name: str, good: bool, detail: str = "") -> bool:
    results.append((name, good, detail))
    print(f"[{'OK' if good else 'NG'}] {name}" + (f": {detail}" if detail else ""), flush=True)
    return good


def wd(method: str, path: str, body=None, timeout: float = 60):
    """WebDriver へ1件。tauri-driver が WebKitWebDriver へ渡す前に繋ぎ直しで落とした1件
    (tauri-driver の出力に「SendRequest … connection error」= まだ送っていない)は、送り直す。
    窓やアプリの不具合ではない(同じ操作を窓に直接しても起きない。12 回中 5 回、場所を選ばずに起きた)。"""
    import http.client
    data = None if body is None else json.dumps(body).encode()
    for attempt in range(3):
        req = urllib.request.Request(f"http://127.0.0.1:{WD_PORT}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with _opener.open(req, timeout=timeout) as res:
                return json.loads(res.read().decode() or "{}").get("value")
        except (http.client.RemoteDisconnected, ConnectionResetError):
            if attempt == 2:
                raise
            time.sleep(0.3)


class Window:
    """WebDriver の1セッション = exe 1つ。"""

    def __init__(self, exe: str) -> None:
        caps = {"capabilities": {"alwaysMatch": {"tauri:options": {"application": exe}}}}
        self.sid = wd("POST", "/session", caps, timeout=180)["sessionId"]

    def s(self, path: str) -> str:
        return f"/session/{self.sid}{path}"

    def find(self, css: str, timeout: float = 20) -> str:
        def look():
            try:
                return wd("POST", self.s("/element"), {"using": "css selector", "value": css})[ELEMENT]
            except Exception:                          # noqa: BLE001 - まだ無い
                return None
        found = wait_for(look, timeout, 0.2)
        if not found:
            raise AssertionError(f"見つかりません: {css}")
        return found

    def click(self, css: str) -> None:
        wd("POST", self.s(f"/element/{self.find(css)}/click"), {})

    def type(self, css: str, text: str) -> None:
        el = self.find(css)
        wd("POST", self.s(f"/element/{el}/clear"), {})
        wd("POST", self.s(f"/element/{el}/value"), {"text": text})

    def text(self, css: str) -> str:
        return wd("GET", self.s(f"/element/{self.find(css)}/text")) or ""

    def js(self, script: str, *args):
        return wd("POST", self.s("/execute/sync"), {"script": script, "args": list(args)})

    def wait_js(self, script: str, timeout: float = 20):
        return wait_for(lambda: self.js(script), timeout, 0.2)

    def url(self) -> str:
        return wd("GET", self.s("/url")) or ""

    def close(self) -> None:
        try:
            wd("DELETE", self.s(""), timeout=20)
        except Exception:                              # noqa: BLE001 - 窓はもう閉じている
            pass


def send_wm_delete(display: str) -> int:
    """窓の × と同じ ClientMessage(WM_DELETE_WINDOW)を送る(coil-packing-tools と同じ)。送った窓の数。"""
    found = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", f"^{TITLE}$"],
                           env=dict(os.environ, DISPLAY=display), capture_output=True, text=True).stdout.split()
    if not found:
        return 0

    class ClientMessage(ctypes.Structure):
        _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                    ("display", ctypes.c_void_p), ("window", ctypes.c_ulong),
                    ("message_type", ctypes.c_ulong), ("format", ctypes.c_int), ("l", ctypes.c_long * 5)]

    class XEvent(ctypes.Union):
        _fields_ = [("xclient", ClientMessage), ("pad", ctypes.c_long * 24)]

    x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.POINTER(XEvent)]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    dpy = x11.XOpenDisplay(display.encode())
    if not dpy:
        return 0
    try:
        protocols = x11.XInternAtom(dpy, b"WM_PROTOCOLS", 0)
        delete = x11.XInternAtom(dpy, b"WM_DELETE_WINDOW", 0)
        for wid in found:
            ev = XEvent()
            ev.xclient.type = 33                       # ClientMessage
            ev.xclient.window = int(wid)
            ev.xclient.message_type = protocols
            ev.xclient.format = 32
            ev.xclient.l[0] = delete
            x11.XSendEvent(dpy, int(wid), 0, 0, ctypes.byref(ev))
        x11.XFlush(dpy)
    finally:
        x11.XCloseDisplay(dpy)
    return len(found)


def make_folders(work: Path) -> tuple:
    files = work / "現場" / "A班"
    files.mkdir(parents=True)
    for name in ("6-1_梱包手順書.xlsx", "007-1_検査要領.pdf", "12-1_手順書.v2.xlsx", "手順書一覧.docx"):
        (files / name).write_text("x", encoding="utf-8")
    for name in ("3-1_写真", "99.生産管理課 土曜日出勤者"):
        (files / name).mkdir()
    rename = work / "現場" / "直す"
    rename.mkdir()
    (rename / "１２-３_ＡＢＣ.txt").write_text("x", encoding="utf-8")
    return files, rename


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--native-driver", default=shutil.which("WebKitWebDriver") or "/usr/bin/WebKitWebDriver")
    args = parser.parse_args()
    exe = str(Path(args.exe).resolve())
    display = os.environ.get("DISPLAY", "")
    work = Path(tempfile.mkdtemp(prefix="flt_e2e_"))
    env = isolated_env(work)
    files, rename = make_folders(work)
    # tauri-driver・WebKitWebDriver の出力は残す(窓を操作できなかったときの手がかり)
    driver_log = open(work / "driver.log", "wb")
    driver = subprocess.Popen(["tauri-driver", "--port", str(WD_PORT), "--native-driver", args.native_driver],
                              env=env, stdout=driver_log, stderr=subprocess.STDOUT)
    time.sleep(1.5)
    try:
        # ---- 1〜4: 画面の操作
        win = Window(exe)
        check("窓に業務画面が出る", bool(win.wait_js("return !!document.getElementById('btn-list')", 60)))
        served = wd("POST", win.s("/execute/async"), {"script": (
            "const done = arguments[arguments.length - 1];"
            "Promise.all(['/static/css/app.css', '/static/js/app.js'].map(u => fetch(u)"
            ".then(r => r.status + ':' + r.headers.get('X-Served-By'))))"
            ".then(done, e => done(String(e)));"), "args": []})
        check("CSS・JS は外枠(Rust)が返す", served == ["200:desktop", "200:desktop"], str(served))
        win.type("#list-folder", str(files))
        win.click("#btn-list")
        win.wait_js("return !document.getElementById('list-table').hidden")
        rows = win.js("return [...document.querySelectorAll('#list-body tr')].map(r => r.cells[1].textContent)")
        check("ファイルの一覧(VBA どおりの並び)", rows == ["6-1", "007-1", "12-1", ""], json.dumps(rows, ensure_ascii=False))

        # 本物のクリップボードには書かせず、コピーで入れる中身を画面の中で受け取る。仮想画面(Xvfb)では、
        # クリップボードに書くたびに WebKitWebDriver との繋がりが切れることがある(窓とアプリは無事。
        # 17 回目前後で起きた)。中身はこのツールのコピーの処理(copytable.js)が copy の合図で入れるものそのもの
        win.js("window.__clip = {}; document.execCommand = function (cmd) {"
               " if (cmd !== 'copy') return false; const ev = new Event('copy', {cancelable: true});"
               " ev.clipboardData = {setData: (t, v) => { window.__clip[t] = v; }};"
               " document.dispatchEvent(ev); return true; };")
        win.click("#btn-copy")
        status = win.wait_js("return document.querySelector('#list-status.ok, #list-status.error')"
                             " && document.getElementById('list-status').textContent")
        clip = win.js("return window.__clip") or {}
        plain = (clip.get("text/plain") or "").split("\r\n")
        check("一覧をコピー(Excel 用の表とタブ区切り)", "コピーしました" in (status or "")
              and plain[:2] == ["文書番号\t名称\t更新日時\t拡張子", plain[1]] and plain[1].startswith("6-1\t梱包手順書\t")
              and "mso-number-format" in (clip.get("text/html") or ""), status or "")

        win.js("window.__printed = 0; window.print = () => { window.__printed++; }")
        win.click("#btn-print")
        sheet = win.js("return {h1: document.querySelector('#print-sheet h1')?.textContent,"
                       " rows: document.querySelectorAll('#print-sheet tbody tr').length, printed: window.__printed}")
        check("一覧を印刷(紙面ができて印刷が呼ばれる)", sheet == {"h1": "A班 の一覧", "rows": 4, "printed": 1}, json.dumps(sheet, ensure_ascii=False))

        win.click("input[value='folders']")
        check("選択ボタンでボタンの名前が変わる", win.text("#btn-list") == "フォルダ名取得")
        win.click("#btn-list")
        win.wait_js("return document.getElementById('list-title').textContent.includes('フォルダ一覧')")
        rows = win.js("return [...document.querySelectorAll('#list-body tr')].map(r => r.cells[2].textContent)")
        check("フォルダの一覧", rows == ["写真", "99.生産管理課 土曜日出勤者"], json.dumps(rows, ensure_ascii=False))

        win.click("#tab-rename")
        win.type("#rename-folder", str(rename))
        win.click("#btn-preview")
        win.wait_js("return !document.getElementById('btn-run').disabled")
        win.click("#btn-run")
        done = wait_for(lambda: (rename / "12-3_ABC.txt").exists(), 20)
        check("全角→半角(下見 → 実行で名前が変わる)", bool(done), ", ".join(sorted(p.name for p in rename.iterdir())))

        win.click("#link-logs")
        check("「ログ」の画面へ移る", bool(wait_for(lambda: win.url().split("?")[0].endswith("/logs"), 20)), win.url())
        wd("POST", win.s("/back"), {})
        check("戻れる", bool(win.wait_js("return !!document.getElementById('btn-list')")))

        info = marker(work)
        win.js("window.confirm = () => true")
        win.click("#btn-exit")
        gone = wait_for(lambda: not alive(int(info.get("pid") or 0)) and not marker(work), 20)
        check("画面の「終了」で exe も Python も終わる", bool(gone))
        win.close()

        # ---- 5: 窓の ×
        win = Window(exe)
        win.wait_js("return !!document.getElementById('btn-list')", 60)
        info = marker(work)
        sent = send_wm_delete(display)
        gone = wait_for(lambda: not alive(int(info.get("pid") or 0)) and not marker(work), 20)
        check("窓の × で exe も Python も終わる", sent > 0 and bool(gone), f"送った窓 {sent}")
        win.close()

        # ---- 6: ブラウザ版が動いているとき
        browser = subprocess.Popen([sys.executable, "start_app.py", "--no-browser"], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threading.Thread(target=browser.wait, daemon=True).start()
        wait_for(lambda: (work / "local" / "runtime" / "instance.lock").exists(), 30)
        time.sleep(1.0)
        win = Window(exe)
        shown = win.wait_js("return document.body && document.body.innerText", 60) or ""
        shown = wait_for(lambda: "ブラウザ版" in (win.js("return document.body.innerText") or "")
                         and win.js("return document.body.innerText"), 30) or shown
        check("ブラウザ版が動いていると窓に理由が出る",
              "ブラウザ版のファイル名一覧取得が動いています" in shown and "stop.bat" in shown, shown[:80].replace("\n", " "))
        win.close()
        subprocess.run([sys.executable, "process_manager.py"], cwd=ROOT, env=env, capture_output=True, timeout=60)
    except Exception as exc:                           # noqa: BLE001 - 途中で止まっても結果を出す
        import traceback
        check("途中で止まらない", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        print("--- driver.log ---\n" + (work / "driver.log").read_text(errors="replace")[-3000:])
    finally:
        kill_tree(driver.pid)
        for line in launcher_log(work).splitlines()[-5:]:
            print("  launcher.log:", line)

    bad = [name for name, good, _ in results if not good]
    print(f"\n{len(results) - len(bad)} / {len(results)} OK" + (f"  だめ: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
