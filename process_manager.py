"""安全な停止 (基盤仕様書 2.8)

1. まずアプリ自身に正常終了を頼む(`POST /api/shutdown`、トークンはロックから読む)
2. 応答しないときだけ、記録した PID を使う。**落とす前に、そのプロセスが
   このアプリ(起動コマンドに start_app.py とこのフォルダが入っている)か確かめる**
3. Python をプロセス名だけで一括終了することはしない

    python process_manager.py            止める
    python process_manager.py --force    リネームの途中でも止める
    python process_manager.py --status   動いているかだけ見る

戻り値: 0 = 止めた・動いていない / 1 = 止められなかった / 2 = 処理の途中なので止めなかった
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

import launch_guard
from app.core import config, logging_setup

log = logging_setup.get("launcher.stop")

GRACEFUL_WAIT_SEC = 8.0


def _request_shutdown(info: launch_guard.LockInfo, force: bool) -> dict:
    body = json.dumps({"force": force}).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Tool-Token": info.token}
    try:
        with launch_guard.local_request(f"http://127.0.0.1:{info.port}/api/shutdown",
                                        timeout=5, data=body, headers=headers,
                                        method="POST") as res:
            return {"ok": bool(json.loads(res.read().decode("utf-8")).get("stopped"))}
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            try:
                running = json.loads(exc.read().decode("utf-8")).get("running", [])
            except Exception:                                  # noqa: BLE001
                running = []
            return {"ok": False, "busy": True, "running": running}
        return {"ok": False}
    except (urllib.error.URLError, OSError):
        return {"ok": False}


def _looks_like_ours(info: launch_guard.LockInfo) -> bool:
    cmd = launch_guard.process_command_line(info.pid).lower()
    if not cmd:
        return False
    roots = {str(config.BASE_DIR).lower(), (info.app_root or "").lower()} - {""}
    return "start_app.py" in cmd and any(root in cmd for root in roots)


def _wait(predicate, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.3)
    return predicate()


def stop(force: bool = False) -> tuple:
    """(戻り値, 文言)"""
    info = launch_guard.read_lock()
    if info is None:
        return 0, "起動していません"

    health = launch_guard.probe_health(info.port)
    if launch_guard.is_our_app(health):
        asked = _request_shutdown(info, force)
        if asked.get("busy"):
            return 2, ("処理の途中なので止めませんでした: " + "、".join(asked.get("running", [])) +
                       "\n    中断してよければ --force を付けてください")
        if asked.get("ok") and _wait(lambda: not launch_guard.is_our_app(
                launch_guard.probe_health(info.port, timeout=0.5)), GRACEFUL_WAIT_SEC):
            _wait(lambda: not launch_guard.is_process_alive(info.pid), 5)
            launch_guard.remove_lock(pid=info.pid)
            return 0, "正常に終了しました"

    if not launch_guard.is_process_alive(info.pid):
        launch_guard.remove_lock(pid=info.pid)
        return 0, "動いていませんでした(残っていたロックを片付けました)"

    if not _looks_like_ours(info):
        log.warning("pid=%s の照合に失敗したため止めません", info.pid)
        return 1, (f"pid {info.pid} はこのアプリではないようなので止めません。\n"
                   f"    ロック: {launch_guard.lock_path()}")

    log.info("応答が無いので pid=%s を止めます", info.pid)
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(info.pid), "/F"], capture_output=True,
                           timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.kill(info.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"止められませんでした: {exc}"
    if _wait(lambda: not launch_guard.is_process_alive(info.pid), 8):
        launch_guard.remove_lock(pid=info.pid)
        return 0, "応答が無かったので、プロセスを止めました"
    return 1, "止められませんでした"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ファイル名一覧取得を止めます")
    parser.add_argument("--force", action="store_true", help="処理の途中でも止める")
    parser.add_argument("--status", action="store_true", help="動いているかだけ見る")
    args = parser.parse_args(argv)
    logging_setup.setup()

    if args.status:
        info = launch_guard.read_lock()
        health = launch_guard.probe_health(info.port) if info else None
        if launch_guard.is_our_app(health):
            print(f"動いています: {info.url} (pid {info.pid}, 版 {health.get('version')})")
            return 0
        print("動いていません")
        return 1

    code, message = stop(force=args.force)
    log.info("停止: %s", message)
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
