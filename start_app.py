"""Python 側の起動開始点 (基盤仕様書 2.1〜2.5)

    Start.vbs ─▶ start_app.py ─▶ launch_guard(多重起動)─▶ server.py(待ち受け)
    (通常)        (環境確認)                                   ├─ 待機画面 /loading
    start.bat ─▶ 同じ道(コンソール表示)                        └─ 準備ができたら業務画面 /
    stop.bat  ─▶ process_manager.py ─▶ POST /api/shutdown → 応答が無ければ PID で停止

    python start_app.py               ふだんの起動(ブラウザを開く)
    python start_app.py --check       環境の確認だけして終わる
    python start_app.py --no-browser  ブラウザを開かない
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser

MIN_PYTHON = (3, 8)


def _early_pycache() -> None:
    """Python のキャッシュをローカル領域へ(基盤仕様書 2.7)。

    アプリ本体を共有フォルダに置いても、共有側に __pycache__ を撒かない。
    **アプリのモジュールを読む前に**決める必要があるので、ここだけは
    config.py を通さずに app.json を直接読む。
    """
    if getattr(sys, "pycache_prefix", None):
        return                                             # PYTHONPYCACHEPREFIX で指定済み
    try:
        import json
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "config", "app.json"), encoding="utf-8") as fh:
            name = json.load(fh).get("local_dir_name", "FileListTool")
        override = os.environ.get("FILELIST_TOOL_LOCAL_DIR")
        if override:
            root = override
        elif sys.platform.startswith("win"):
            root = os.path.join(os.environ.get("LOCALAPPDATA")
                                or os.path.expanduser(r"~\AppData\Local"), name)
        else:
            root = os.path.join(os.environ.get("XDG_STATE_HOME")
                                or os.path.expanduser("~/.local/state"), name)
        sys.pycache_prefix = os.path.join(root, "pycache")
    except Exception:                                      # noqa: BLE001 - 起動は止めない
        pass


_early_pycache()


def _console_available() -> bool:
    return sys.stdout is not None and sys.stderr is not None


def _notify(message: str, title: str = "ファイル名一覧取得") -> None:
    """コンソールが無い(pythonw)ときも、失敗を利用者に伝える。"""
    if _console_available():
        print(message, file=sys.stderr)
        return
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)  # type: ignore[attr-defined]
        except Exception:                                  # noqa: BLE001
            pass


def check_environment() -> list:
    """(項目, 良し悪し, 中身) の一覧。"""
    from app.core import config
    results = []
    ok_py = sys.version_info >= MIN_PYTHON
    results.append(("Python", ok_py, f"{sys.version.split()[0]} ({sys.executable})"
                    + ("" if ok_py else f" … {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上が要ります")))
    for rel in ("config/app.json", "loading.html", "app/templates/index.html"):
        path = config.BASE_DIR / rel
        results.append((rel, path.is_file(), str(path)))
    try:
        logs = config.local_dir("logs")
        probe = logs / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        results.append(("ローカル領域", True, str(config.local_root())))
    except OSError as exc:
        results.append(("ローカル領域", False, f"{config.local_root()} に書けません: {exc}"))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ファイル名一覧取得を起動します")
    parser.add_argument("--check", action="store_true", help="環境の確認だけして終わる")
    parser.add_argument("--no-browser", action="store_true", help="ブラウザを開かない")
    args = parser.parse_args(argv)

    if sys.version_info < MIN_PYTHON:
        _notify(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上が要ります(いま {sys.version.split()[0]})。")
        return 1

    from app.core import config, logging_setup
    logging_setup.setup(console=_console_available())
    log = logging_setup.get("launcher.start")
    t0 = time.time()
    log.info("起動: 版 %s / Python %s (%s) / 置き場所 %s / pid %s",
             config.version(), sys.version.split()[0], sys.executable, config.BASE_DIR, os.getpid())

    checks = check_environment()
    for name, good, detail in checks:
        log.info("確認 %s: %s %s", name, "OK" if good else "NG", detail)
    if args.check:
        for name, good, detail in checks:
            print(f"[{'OK' if good else 'NG'}] {name}: {detail}")
        return 0 if all(g for _, g, _ in checks) else 1
    if not all(g for _, g, _ in checks):
        bad = "\n".join(f"・{n}: {d}" for n, g, d in checks if not g)
        _notify(f"起動できません。\n{bad}\n\nログ: {config.local_root() / 'logs'}")
        return 1

    import launch_guard
    guard = launch_guard.check_existing()
    if guard.running:
        log.info("%s。新しく起動せず画面を開きます(%s)", guard.message, guard.url)
        if guard.url and not args.no_browser:
            webbrowser.open(guard.url)
        elif not guard.url:
            _notify(guard.message)
        return 0
    if not launch_guard.try_acquire():
        # 判定とロックのあいだに別の起動が入った
        guard = launch_guard.check_existing()
        log.info("ほかの起動が先にロックを取りました: %s", guard.message)
        if guard.url and not args.no_browser:
            webbrowser.open(guard.url)
        return 0

    try:
        return _serve(args, log, t0)
    finally:
        launch_guard.remove_lock(pid=os.getpid())


def _serve(args, log, t0: float) -> int:
    import launch_guard
    from app.application import App
    from app.core import config
    from app.core.idle_exit import IdleMonitor
    from server import AppServer

    port = launch_guard.pick_port()
    if port is None:
        msg = (f"使えるポートがありません({config.base_port()}〜"
               f"{config.base_port() + config.port_retry()})。ほかのアプリを閉じてから起動してください。")
        log.error(msg)
        _notify(f"{msg}\n\nログ: {config.local_root() / 'logs'}")
        return 1

    stop_event = threading.Event()
    stop_reason = {"why": "停止の要求"}
    app = App(port=port, on_shutdown=stop_event.set)
    server = AppServer(app, config.host(), port)
    server.start()
    launch_guard.write_lock(launch_guard.build_lock_info(port, app.token))
    log.info("待ち受けまで %.2f 秒(port %s)", time.time() - t0, port)

    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{port}/loading")

    # 重い初期化は無いが、段階は残す(どこで止まったかをログで追えるように)
    app.state.stage = "接続を確認中"
    if not launch_guard.is_our_app(launch_guard.probe_health(port, timeout=5)):
        app.state.startup_error = "自分自身に接続できません(セキュリティ製品やプロキシの設定を確かめてください)"
        log.error(app.state.startup_error)
    else:
        app.state.ready = True
        app.state.stage = "起動完了"
        log.info("準備完了まで %.2f 秒", time.time() - t0)

    def on_idle(why: str) -> None:
        stop_reason["why"] = why
        stop_event.set()

    idle = IdleMonitor(app.state,
                       idle_seconds=config.monitoring("idle_exit_seconds", 90),
                       bye_grace=config.monitoring("bye_grace_seconds", 8),
                       on_idle=on_idle)
    idle.start()
    try:
        while not stop_event.wait(0.5):
            pass
    except KeyboardInterrupt:
        stop_reason["why"] = "Ctrl+C"
    idle.stop()
    server.stop()
    log.info("終了: %s(動いていた時間 %.0f 秒)", stop_reason["why"], time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
