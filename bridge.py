"""デスクトップ版(Tauri)からの入口 ── **ポートを使わない**(VER2.0.0)

ブラウザ版(`Start.vbs` → `start_app.py`)は 127.0.0.1 のポートで待ち受けて、ブラウザから
繋いでもらう。デスクトップ版では、窓を持つ外枠(Rust/Tauri、`src-tauri/`)がこのプロセスを
子として起動し、**標準入出力**で要求を渡す。ソケットは1つも開かない。

    外枠(Rust) ──標準入力──▶ bridge.py ──▶ App.handle(ブラウザ版と同じ処理)
               ◀──標準出力──

python-web-tools・coil-packing-tools の bridge.py と同じ形。違うのは、あちらが Flask を
WSGI として呼ぶのに対して、こちらは初めから標準ライブラリだけで作ってあるので
`App.handle(Request)` をそのまま呼ぶこと(**追加のライブラリは要らない**)。

【やりとりの形】1件 = 見出し1行(JSON)+ 本文(見出しの `len` バイト)

    要求  {"id": 7, "method": "POST", "path": "/api/x", "query": "a=1",
           "headers": [["Content-Type", "application/json"], ...], "len": 12}\\n<本文>
    応答  {"id": 7, "status": 200, "headers": [[...], ...], "len": 345}\\n<本文>
    知らせ {"event": "started"}\\n                       (`len` なし。本文なし)

【知らせ】
    static   … 静的ファイルの経路の頭と置き場所。CSS・JS は外枠が直接返す(Python を通さない)
    started  … 受け付けを始めた
    quit     … 終了してよい(画面の「終了」・窓の ×)。外枠が標準入力を閉じて終わる
    fatal    … 起動できない(`message` `hint` `log_dir`)。外枠が理由を窓に出す

【標準出力を守る】
やりとりに使う標準出力へ、ほかの誰かが1文字でも書くと、以降すべてずれる。そこで**最初に**
本物の標準出力を別に取っておき、ファイル記述子 1 は標準エラーへ付け替える(`print` も標準エラーへ)。

【ブラウザ版とは同時に動かない】
ブラウザ版が動いていれば起動せず、理由を窓に出す(`launch_guard.BROWSER_RUNNING_MESSAGE`)。
動いているあいだは印(`runtime\\desktop.json`)を置き、ブラウザ版の起動はそれを見て断る。
判断は短い門(`launch_guard.startup_gate`)の中でするので、ほぼ同時に起動しても2つとも動かない。
"""
from __future__ import annotations

import json
import os
import sys

# **ツールのフォルダの中に __pycache__ を書かない**。start_app を読み込んだ時点でキャッシュの置き場所が
# ローカル領域へ移る(start_app._early_pycache)。それまでは書かない(start_app 自身が書かれてしまうため)
sys.dont_write_bytecode = True

import threading  # noqa: E402
import time
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, BinaryIO, Optional  # noqa: E402

APP_ROOT = Path(__file__).resolve().parent

# 同時に捌く要求の数。画面は「操作 + 心拍 + ログの数」を同時に投げる。書く要求は
# アプリ側の錠が1つずつ通す(`App.write_lock`)
WORKERS = 8

# 1件の本文の上限(壊れた見出しで巨大な読み込みをしないため)。ブラウザ版(server.MAX_BODY)より広め
MAX_BODY = 8 * 1024 * 1024

ENV_TOKEN = "FILELIST_TOOL_TOKEN"
ENV_EXE_PID = "FILELIST_TOOL_EXE_PID"


# ==================================================================
# やりとりの形
# ==================================================================
class FrameTooLarge(Exception):
    """本文が上限を超えた1件。**本文は読み捨ててある**ので、次の1件から続けて読める。"""

    def __init__(self, head: dict, size: int) -> None:
        super().__init__(f"本文が大きすぎます: {size}")
        self.head = head
        self.size = size


def read_frame(stream: BinaryIO) -> Optional[tuple]:
    """1件読む。終わり(相手が閉じた)なら `None`。"""
    line = stream.readline()
    if not line:
        return None
    head = json.loads(line.decode("utf-8"))
    size = int(head.get("len", 0) or 0)
    if size < 0:
        raise ValueError(f"本文の長さが不正です: {size}")
    if size > MAX_BODY:
        left = size
        while left > 0:                                  # 区切りを保つため読み捨てる
            chunk = stream.read(min(left, 1024 * 1024))
            if not chunk:
                raise EOFError("本文の途中で終わりました")
            left -= len(chunk)
        raise FrameTooLarge(head, size)
    body = b""
    while len(body) < size:
        chunk = stream.read(size - len(body))
        if not chunk:
            raise EOFError("本文の途中で終わりました")
        body += chunk
    return head, body


class FrameWriter:
    """応答と知らせを書く。**1件ずつ丸ごと**書く(複数のスレッドから来る)。"""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, head: dict, body: bytes = b"") -> None:
        head = dict(head)
        if body or "id" in head:
            head["len"] = len(body)
        data = json.dumps(head, ensure_ascii=False).encode("utf-8") + b"\n" + body
        with self._lock:
            self._stream.write(data)
            self._stream.flush()

    def event(self, name: str, **fields: Any) -> None:
        try:
            self.write({"event": name, **fields})
        except (BrokenPipeError, OSError):
            pass                                         # 外枠が先に終わった


def answer(app, head: dict, body: bytes) -> tuple:
    """要求1件を App に渡して、(状態, 見出し, 本文) を返す。ブラウザ版の server._Handler と同じ渡し方。"""
    from app.web import Request
    target = head.get("path") or "/"
    if head.get("query"):
        target += "?" + str(head["query"])
    headers = {str(k): str(v) for k, v in head.get("headers", [])}
    req = Request.build(head.get("method") or "GET", target, headers, body)
    resp = app.handle(req)
    out = [["Content-Type", resp.content_type]] + [[k, v] for k, v in resp.headers.items()]
    return resp.status, out, (b"" if req.method == "HEAD" else resp.body)


def static_map() -> list:
    """静的ファイルの経路の頭と置き場所: `[["/static/", "<フォルダ>"]]`(ブラウザ版の pages.static_file と同じ所)。"""
    from app.routes import pages
    return [["/static/", str(pages.STATIC.resolve())]]


def _protect_stdout() -> BinaryIO:
    """本物の標準出力を取っておき、記述子 1 は標準エラーへ向ける。"""
    proto = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    return proto


def exe_pid() -> int:
    """窓(exe)の番号。外枠が環境変数で渡す。無ければ親(stop.bat が窓か確かめてから頼む)。"""
    try:
        return int(os.environ.get(ENV_EXE_PID, "") or 0) or os.getppid()
    except ValueError:
        return os.getppid()


# ==================================================================
# 入口
# ==================================================================
class StartupError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def _log_dir() -> str:
    try:
        from app.core import config
        return str(config.local_dir("logs"))
    except Exception:                                    # noqa: BLE001 - 失敗の報告で失敗しない
        return ""


def prepare() -> None:
    """ブラウザ版の start_app.main と同じ確かめ(部品・設定・ログ・書ける場所)。だめなら StartupError。"""
    import start_app
    if sys.version_info < start_app.MIN_PYTHON:
        raise StartupError(f"Python {start_app.MIN_PYTHON[0]}.{start_app.MIN_PYTHON[1]} 以上が要ります"
                           f"(いま {sys.version.split()[0]})",
                           "https://www.python.org/downloads/ から新しい Python を入れてください。")
    lacking = start_app.missing_parts()
    if lacking:
        raise StartupError("このフォルダの部品が足りないので起動できません: " + "、".join(lacking),
                           f"フォルダ: {APP_ROOT}\n配布フォルダを丸ごと入れ直してください。")
    try:
        from app.core import config, event_log, logging_setup
        for read in (config.app_id, config.version, config.display_name):
            read()
        logging_setup.setup(console=True)                # 標準エラー → 外枠が末尾を覚える
        event_log.install()
    except Exception as exc:                             # noqa: BLE001
        raise StartupError(f"起動の準備ができませんでした({type(exc).__name__}: {exc})",
                           "設定ファイル(config\\app.json)が壊れていないか確かめてください。")
    bad = [f"{name}: {detail}" for name, good, detail in start_app.check_environment() if not good]
    if bad:
        raise StartupError("起動できません: " + " / ".join(bad), "")


def claim() -> dict:
    """ブラウザ版・ほかのデスクトップ版が動いていないか確かめ、印を置く(門の中で)。"""
    import launch_guard
    from app.core import config, logging_setup
    log = logging_setup.get("launcher.desktop")
    with launch_guard.startup_gate():
        alive, raw, _ = launch_guard.desktop_status()
        if alive and raw and int(raw.get("pid") or 0) != os.getpid():
            raise StartupError("デスクトップ版のファイル名一覧取得がもう動いています",
                               "開いている窓を使ってください。")
        if raw is not None and not alive:
            launch_guard.remove_desktop_marker(expect=raw)
        guard = launch_guard.check_existing()            # ブラウザ版のロック(残りものなら片付く)
        if guard.running:
            log.warning("ブラウザ版が動いているので、デスクトップ版は起動しません: %s", guard.message)
            raise StartupError(launch_guard.BROWSER_RUNNING_MESSAGE, launch_guard.BROWSER_RUNNING_HINT)
        return launch_guard.write_desktop_marker(config.app_id(), exe_pid())


def serve(writer: FrameWriter, reader: BinaryIO, token: str) -> int:
    """標準入力から要求を読み、別スレッドで答える。相手が閉じたら終わる。"""
    import start_app
    from app.application import App
    from app.core import config, logging_setup
    log = logging_setup.get("launcher.desktop")
    t0 = time.time()
    stop = {"why": "窓が閉じました"}

    def on_shutdown() -> None:
        # 画面の「終了」・窓の ×(外枠が /api/shutdown を呼ぶ)。外枠が標準入力を閉じて終わる
        stop["why"] = "終了の要求"
        writer.event("quit")

    app = App(port=0, token=token or None, on_shutdown=on_shutdown, desktop=True)
    app.state.ready = True
    app.state.stage = "起動完了"
    writer.event("static", static=static_map())
    writer.event("started")
    log.info("外枠からの要求を受け付けます(ポートは使いません)。pid %s / 窓 %s", os.getpid(), exe_pid())
    start_app._note_event(f"起動しました(デスクトップ版・版 {config.version()}・ポートなし)", "起動")

    pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="bridge")

    def reply(head: dict, body: bytes) -> None:
        try:
            status, headers, data = answer(app, head, body)
        except Exception as exc:                         # noqa: BLE001 - 1件の失敗で止めない(App が番号を付ける)
            log.exception("要求を処理できませんでした: %s", head.get("path"))
            status, headers = 500, [["Content-Type", "text/plain; charset=utf-8"]]
            data = f"内部エラー: {exc}".encode("utf-8")
        try:
            writer.write({"id": head.get("id"), "status": status, "headers": headers}, data)
        except (BrokenPipeError, OSError):
            pass

    try:
        while True:
            try:
                frame = read_frame(reader)
            except FrameTooLarge as exc:
                body = json.dumps({"error": {"code": "too_large",
                                             "message": "送る内容が大きすぎます。"}}, ensure_ascii=False)
                writer.write({"id": exc.head.get("id"), "status": 413,
                              "headers": [["Content-Type", "application/json; charset=utf-8"]]},
                             body.encode("utf-8"))
                continue
            except (ValueError, EOFError) as exc:
                log.error("要求を読めませんでした: %s", exc)
                break
            if frame is None:
                break
            pool.submit(reply, *frame)
    finally:
        pool.shutdown(wait=True)
        start_app._note_event(f"終了しました: {stop['why']}(デスクトップ版)", "終了")
        log.info("終了: %s(動いていた時間 %.0f 秒)", stop["why"], time.time() - t0)
    return 0


def main() -> int:
    proto = _protect_stdout()
    writer = FrameWriter(proto)
    reader = sys.stdin.buffer
    sys.path.insert(0, str(APP_ROOT))
    import start_app                                     # noqa: F401 - Python のキャッシュをローカル領域へ
    if getattr(sys, "pycache_prefix", None):
        sys.dont_write_bytecode = False                  # 置き場所が決まった(ローカル領域の pycache)

    def fatal(error: StartupError) -> int:
        try:
            from process_manager import write_launcher_log
            write_launcher_log(f"デスクトップ版を起動できません: {error} / {error.hint}",
                               "launcher.desktop", "ERROR")
        except Exception:                                # noqa: BLE001
            pass
        writer.event("fatal", message=str(error), hint=error.hint, log_dir=_log_dir())
        return 1

    try:
        prepare()
        marker = claim()
    except StartupError as exc:
        return fatal(exc)
    except Exception as exc:                             # noqa: BLE001 - 理由を外枠へ渡す
        return fatal(StartupError(f"起動中に思わぬエラー: {type(exc).__name__}: {exc}",
                                  "ログを確かめてください。"))
    try:
        return serve(writer, reader, os.environ.get(ENV_TOKEN, ""))
    except Exception as exc:                             # noqa: BLE001
        return fatal(StartupError(f"起動中に思わぬエラー: {type(exc).__name__}: {exc}",
                                  "ログを確かめてください。"))
    finally:
        import launch_guard
        launch_guard.remove_desktop_marker(expect=marker)


if __name__ == "__main__":
    raise SystemExit(main())
