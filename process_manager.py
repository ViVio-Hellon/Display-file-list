"""安全な停止 (基盤仕様書 2.8)

1. まずアプリ自身に正常終了を頼む(`POST /api/shutdown`、トークンはロックから読む)
2. 応答しない・頼んでも終わらないときだけ、記録した PID を使う。**落とす前に、
   そのプロセスがこのアプリ(起動コマンドに start_app.py とこのフォルダ)か確かめる**
3. **止まったかは PID が居なくなったことで確かめる。** 確かめられなければ「止まらなかった」と言う
4. Python をプロセス名だけで一括終了することはしない

    python process_manager.py            止める
    python process_manager.py --force    リネームの途中でも止める
    python process_manager.py --status   動いているかだけ見る

戻り値: 0 = 止めた・動いていない / 1 = 止められなかった / 2 = 処理の途中なので止めなかった

■ このファイルは標準ライブラリだけで動く(VER1.4.1)
all-tools で、フォルダを消そうとして途中までしか消えなかった(動いている Python が
ファイルを掴んでいた)あと、止める入口そのものが部品の欠けで動かず、タスクマネージャーで
切るしかなかった。止める入口は、**ほかの部品(app\\・launch_guard.py・config\\)が
欠けていても動く**ようにしておく。ここでは app も launch_guard も読まない
(逆に launch_guard がここのプロセスの道具を使う)。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_NAME = "FileListTool"
ENV_LOCAL_DIR = "FILELIST_TOOL_LOCAL_DIR"

GRACEFUL_WAIT_SEC = 8.0      # 頼んでから待ち受けが閉じるまで
EXIT_WAIT_SEC = 8.0          # 待ち受けが閉じてから PID が居なくなるまで
KILL_WAIT_SEC = 8.0          # PID で止めてから居なくなるまで


# ------------------------------------------------------------------
# 置き場所(config/app.json が読めなくても決められるように)
# ------------------------------------------------------------------
def local_root() -> Path:
    override = os.environ.get(ENV_LOCAL_DIR)
    if override:
        return Path(override)
    name = DEFAULT_LOCAL_NAME
    try:
        data = json.loads((BASE_DIR / "config" / "app.json").read_text(encoding="utf-8"))
        name = str(data.get("local_dir_name") or DEFAULT_LOCAL_NAME)
    except (OSError, ValueError):
        pass                                   # 設定が欠けても既定の名前で探す
    if sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / name
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / name


def lock_path() -> Path:
    return local_root() / "runtime" / "instance.lock"


def read_lock() -> Optional[dict]:
    try:
        data = json.loads(lock_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def remove_lock(pid: Optional[int] = None) -> None:
    """`pid` を渡すと、そのプロセスのロックのときだけ消す。"""
    if pid is not None:
        info = read_lock()
        if info is not None and int(info.get("pid") or 0) != pid:
            return
    try:
        lock_path().unlink()
    except OSError:
        pass


def write_launcher_log(message: str, source: str = "launcher.stop", level: str = "INFO") -> None:
    """launcher.log へ書く(logging を使わない。部品が欠けていても書ける)。start_app も使う。"""
    try:
        folder = local_root() / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        with (folder / "launcher.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {level:<7} [{os.getpid()}] {source}: {message}\n")
    except OSError:
        pass


# ------------------------------------------------------------------
# プロセス(launch_guard もこれを使う)
# ------------------------------------------------------------------
def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes
        kernel32 = ctypes.windll.kernel32                     # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259                          # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_command_line(pid: int) -> str:
    """そのプロセスの起動コマンド。取れなければ空文字。"""
    if sys.platform.startswith("win"):
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def kill_process(pid: int) -> None:
    """PID で止める。Windows は子ごと(/T)。"""
    if sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        os.kill(pid, signal.SIGTERM)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_request(url: str, *, timeout: float, data: Optional[bytes] = None,
                  headers: Optional[dict] = None, method: Optional[str] = None):
    """社内PCのプロキシ設定に 127.0.0.1 の除外が無くても、自分自身へ届くようにする。"""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    return _OPENER.open(req, timeout=timeout)


def probe_health(port: int, *, timeout: float = 1.5) -> Optional[dict]:
    if not port:
        return None
    try:
        with local_request(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _answers(info: dict) -> bool:
    """ロックの相手が待ち受けていて、同じアプリだと名乗るか。"""
    health = probe_health(int(info.get("port") or 0))
    return bool(health) and health.get("app_id") == info.get("app_id")


def _request_shutdown(info: dict, force: bool) -> dict:
    body = json.dumps({"force": force}).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Tool-Token": str(info.get("token") or "")}
    try:
        with local_request(f"http://127.0.0.1:{int(info.get('port') or 0)}/api/shutdown",
                           timeout=5, data=body, headers=headers, method="POST") as res:
            return {"ok": bool(json.loads(res.read().decode("utf-8")).get("stopped"))}
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            try:
                running = json.loads(exc.read().decode("utf-8")).get("running", [])
            except Exception:                                  # noqa: BLE001
                running = []
            return {"ok": False, "busy": True, "running": running}
        return {"ok": False, "refused": exc.code}
    except (urllib.error.URLError, OSError):
        return {"ok": False}


def looks_like_ours(info: dict) -> bool:
    cmd = process_command_line(int(info.get("pid") or 0)).lower()
    if not cmd:
        return False
    roots = {str(BASE_DIR).lower(), str(info.get("app_root") or "").lower()} - {""}
    return "start_app.py" in cmd and any(root in cmd for root in roots)


def _wait(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.3)
    return predicate()


# ------------------------------------------------------------------
# 止める
# ------------------------------------------------------------------
def stop(force: bool = False) -> tuple:
    """(戻り値, 文言)。**PID が居なくなったのを確かめてから**「終わった」と言う。"""
    info = read_lock()
    if info is None:
        return 0, "起動していません"
    pid = int(info.get("pid") or 0)

    if _answers(info):
        asked = _request_shutdown(info, force)
        if asked.get("busy"):
            return 2, ("処理の途中なので止めませんでした: " + "、".join(asked.get("running", [])) +
                       "\n    中断してよければ --force を付けてください")
        if asked.get("ok"):
            closed = _wait(lambda: not _answers(info), GRACEFUL_WAIT_SEC)
            # 待ち受けがまだ答えているなら、待っても終わらない。すぐ PID で止める
            if closed and _wait(lambda: not is_process_alive(pid), EXIT_WAIT_SEC):
                remove_lock(pid=pid)
                return 0, "正常に終了しました"
            write_launcher_log(f"停止を受け付けたが pid={pid} が残っています。PID で止めます")
        else:
            write_launcher_log(f"停止の要求が通りませんでした({asked})。PID で止めます")

    if not is_process_alive(pid):
        remove_lock(pid=pid)
        return 0, "動いていませんでした(残っていたロックを片付けました)"

    if not looks_like_ours(info):
        write_launcher_log(f"pid={pid} の照合に失敗したため止めません")
        return 1, (f"pid {pid} はこのアプリではないようなので止めません。\n"
                   f"    ロック: {lock_path()}")

    write_launcher_log(f"pid={pid} を止めます")
    try:
        kill_process(pid)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"止められませんでした: {exc}"
    if _wait(lambda: not is_process_alive(pid), KILL_WAIT_SEC):
        remove_lock(pid=pid)
        return 0, "応答が無かったので、プロセスを止めました"
    return 1, (f"止まりませんでした(pid {pid})。タスクマネージャーの「詳細」で、この番号の "
               "python / pythonw を終了してください")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ファイル名一覧取得を止めます")
    parser.add_argument("--force", action="store_true", help="処理の途中でも止める")
    parser.add_argument("--status", action="store_true", help="動いているかだけ見る")
    args = parser.parse_args(argv)

    if args.status:
        info = read_lock()
        if info and _answers(info):
            health = probe_health(int(info.get("port") or 0)) or {}
            print(f"動いています: http://127.0.0.1:{info.get('port')}/ "
                  f"(pid {info.get('pid')}, 版 {health.get('version')})")
            return 0
        if info and is_process_alive(int(info.get("pid") or 0)):
            print(f"応答していませんが、pid {info.get('pid')} が残っています(stop.bat で止められます)")
            return 0
        print("動いていません")
        return 1

    code, message = stop(force=args.force)
    write_launcher_log(f"停止: {message}")
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
