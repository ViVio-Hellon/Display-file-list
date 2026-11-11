#!/usr/bin/env python3
"""デスクトップ版(exe)を本当に起動して確かめる(開発機の Linux・GitHub Actions の Windows)

    python scripts/desktop_smoke.py --exe src-tauri/target/release/FileListTool.exe
    xvfb-run -a python scripts/desktop_smoke.py --exe src-tauri/target/debug/FileListTool   # Linux

WebDriver を使わない(WebDriver の検査口は待ち受けるので、「ポートを使わない」を確かめられない)。
置き場所は使い捨てのフォルダに分ける(ふだんの設定・ログに触らない)。標準ライブラリだけ。

【確かめること】
1. 窓が出て、画面(/)が Python から届く(出来事のログに「画面を開いた」が残る)
2. exe・Python・WebView の**どのプロセスもポートで待ち受けていない**
3. 2つ目の exe は起動せずに終わる(1つ目はそのまま)
4. デスクトップ版が動いているあいだ、ブラウザ版(start_app.py)は起動しない
5. stop.bat(process_manager.py)で閉じる。exe も Python も居なくなり、印も消える
   (Windows では窓に WM_CLOSE = 窓の × と同じ道。画面の「終了」と同じく Python に終了を頼む)
6. ブラウザ版が動いているときにデスクトップ版を開くと、Python は起動を断る(窓に理由が出る)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading  # noqa: F401
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"
results: list = []


def check(name: str, good: bool, detail: str = "") -> bool:
    results.append((name, good, detail))
    print(f"[{'OK' if good else 'NG'}] {name}" + (f": {detail}" if detail else ""), flush=True)
    return good


def wait_for(predicate, timeout: float, interval: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


# ------------------------------------------------------------------
# プロセスと待ち受け(OS ごと)
# ------------------------------------------------------------------
def processes() -> dict:
    """pid → 親の pid。"""
    out = {}
    if WINDOWS:
        text = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }"],
            capture_output=True, text=True, timeout=60).stdout
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                out[int(parts[0])] = int(parts[1])
        return out
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                stat = (entry / "stat").read_text()
                out[int(entry.name)] = int(stat[stat.rindex(")") + 2:].split()[1])
            except (OSError, ValueError, IndexError):
                pass
    return out


def tree(root_pid: int) -> set:
    """そのプロセスと子孫(WebView のプロセスも入る)。"""
    table = processes()
    found, todo = {root_pid}, [root_pid]
    while todo:
        parent = todo.pop()
        for pid, ppid in table.items():
            if ppid == parent and pid not in found:
                found.add(pid)
                todo.append(pid)
    return found


def listening_pids() -> dict:
    """待ち受けているソケットの持ち主: pid → [ポート]。"""
    out: dict = {}
    if WINDOWS:
        text = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=60).stdout
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] in ("TCP", "UDP") and "LISTEN" in line.upper():
                out.setdefault(int(parts[-1]), []).append(parts[1])
        return out
    inodes = {}
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in Path(name).read_text().splitlines()[1:]:
                parts = line.split()
                if parts[3] == "0A":                                  # LISTEN
                    inodes[parts[9]] = int(parts[1].rsplit(":", 1)[1], 16)
        except OSError:
            pass
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            for fd in (entry / "fd").iterdir():
                link = os.readlink(fd)
                if link.startswith("socket:[") and link[8:-1] in inodes:
                    out.setdefault(int(entry.name), []).append(inodes[link[8:-1]])
        except OSError:
            pass
    return out


def alive(pid: int) -> bool:
    sys.path.insert(0, str(ROOT))
    from process_manager import is_process_alive
    return is_process_alive(pid)


def kill_tree(pid: int) -> None:
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        for p in sorted(tree(pid), reverse=True):
            try:
                os.kill(p, 9)
            except OSError:
                pass


# ------------------------------------------------------------------
# 置き場所
# ------------------------------------------------------------------
def isolated_env(work: Path) -> dict:
    env = dict(os.environ)
    env["FILELIST_TOOL_ROOT"] = str(ROOT)
    env["FILELIST_TOOL_LOCAL_DIR"] = str(work / "local")
    if WINDOWS:
        env["LOCALAPPDATA"] = str(work / "localappdata")
    return env


def marker(work: Path) -> dict:
    try:
        return json.loads((work / "local" / "runtime" / "desktop.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def opened_page(work: Path) -> bool:
    """出来事のログに「画面を開いた」(GET /)があるか。"""
    for path in (work / "local" / "logs").glob("出来事_*.jsonl"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"action": "GET /"' in line and '"status": 200' in line:
                return True
    return False


def launcher_log(work: Path) -> str:
    try:
        return (work / "local" / "logs" / "launcher.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def run_py(env: dict, *args: str, timeout: float = 90) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


# ------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--keep", help="使い捨てのフォルダを消さずにここへ作る")
    args = parser.parse_args()
    exe = str(Path(args.exe).resolve())
    work = Path(args.keep or tempfile.mkdtemp(prefix="flt_smoke_"))
    work.mkdir(parents=True, exist_ok=True)
    env = isolated_env(work)

    # ---- 1. 起動して画面が届く
    t0 = time.time()
    first = subprocess.Popen([exe], cwd=ROOT, env=env)
    got = wait_for(lambda: marker(work).get("pid"), 90)
    check("Python(bridge.py)が起動して印を置く", bool(got), f"{time.time() - t0:.1f} 秒")
    check("画面(/)が Python から届く", bool(wait_for(lambda: opened_page(work), 60)))
    info = marker(work)

    # ---- 2. ポートで待ち受けない
    time.sleep(1.0)
    ours = tree(first.pid)
    busy = {pid: ports for pid, ports in listening_pids().items() if pid in ours}
    check("exe・Python・WebView のどれもポートで待ち受けない", not busy,
          f"見たプロセス {len(ours)} 個" + (f" / 待ち受け {busy}" if busy else ""))

    # ---- 3. 2つ目の exe
    second = subprocess.Popen([exe], cwd=ROOT, env=env)
    try:
        code = second.wait(timeout=30)
        check("2つ目の exe は起動せずに終わる", True, f"終了コード {code}")
    except subprocess.TimeoutExpired:
        kill_tree(second.pid)
        check("2つ目の exe は起動せずに終わる", False, "30 秒たっても終わらない")
    check("1つ目はそのまま動いている", first.poll() is None and alive(int(info.get("pid") or 0)))

    # ---- 4. ブラウザ版は起動しない
    res = run_py(env, "start_app.py", "--no-browser")
    check("デスクトップ版が動いているとブラウザ版は起動しない", res.returncode == 1
          and "デスクトップ版のファイル名一覧取得が動いています" in res.stderr, f"終了コード {res.returncode}")
    check("ブラウザ版のロックは残らない", not (work / "local" / "runtime" / "instance.lock").exists())

    # ---- 5. stop.bat で閉じる
    res = run_py(env, "process_manager.py")
    check("stop.bat(process_manager.py)で閉じる", res.returncode == 0, res.stdout.strip())
    gone = wait_for(lambda: first.poll() is not None and not alive(int(info.get("pid") or 0)), 20)
    check("exe も Python も居なくなる", bool(gone))
    check("デスクトップ版の印が消える", not marker(work))
    if first.poll() is None:
        kill_tree(first.pid)

    # ---- 6. ブラウザ版が先に動いているとき
    browser = subprocess.Popen([sys.executable, "start_app.py", "--no-browser"], cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # この試験の子なので、終わったら受け取る(受け取らないと Linux では「居る」ままに見える)
    import threading
    threading.Thread(target=browser.wait, daemon=True).start()
    lock = work / "local" / "runtime" / "instance.lock"

    def browser_ready():
        try:
            return json.loads(lock.read_text(encoding="utf-8")).get("port", 0) > 0
        except (OSError, ValueError):
            return False
    check("ブラウザ版が起動する", bool(wait_for(browser_ready, 60)))
    third = subprocess.Popen([exe], cwd=ROOT, env=env)
    refused = wait_for(lambda: "ブラウザ版のファイル名一覧取得が動いています" in launcher_log(work), 60)
    check("ブラウザ版が動いているとデスクトップ版の Python は起動を断る", bool(refused))
    check("窓は残って理由を出している(exe は動いている)", third.poll() is None)
    check("デスクトップ版の印は置かない", not marker(work))
    kill_tree(third.pid)
    res = run_py(env, "process_manager.py")
    check("ブラウザ版は stop.bat で止まる", res.returncode == 0, res.stdout.strip())
    try:
        browser.wait(timeout=20)
    except subprocess.TimeoutExpired:
        kill_tree(browser.pid)

    bad = [name for name, good, _ in results if not good]
    print(f"\n{len(results) - len(bad)} / {len(results)} OK" + (f"  だめ: {bad}" if bad else ""))
    if bad:
        print("--- launcher.log ---\n" + launcher_log(work)[-4000:])
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
