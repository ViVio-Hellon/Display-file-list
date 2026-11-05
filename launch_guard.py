"""多重起動の防止とインスタンス管理 (基盤仕様書 2.4)

python-web-tools の launch_guard.py と同じ考え方を、このアプリ用に小さくしたもの。

起動ごとに**ロックファイル**(PID・ポート・起動時刻・トークン)を
ローカル領域の runtime に書き、次の起動はそれを見て判断する。

    生きている同じアプリが居る → 新しく起動せず、ブラウザだけ開く
    起動途中のロックがある     → ポートが入るまで待つ
    死んだロックが残っている   → 片付けて続行する(記録は残す)

「生きているか」は2段で見る。PID は使い回されるので PID だけでは足りず、
別のアプリが同じポートで HTTP を返していることもあるので、
`/api/health` の `app_id` まで照合する。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from app.core import config, logging_setup

log = logging_setup.get("launcher.guard")

STARTING_PORT = 0
STARTING_WAIT_SEC = 15.0


@dataclass
class LockInfo:
    app_id: str
    pid: int
    port: int
    started_at: float
    python: str = ""
    app_root: str = ""
    # stop.bat が「正常終了を頼む」ために要る。ロックは利用者ごとのローカル領域にあり、
    # 読めるのは同じ利用者だけ(その相手はプロセスを直接止められる)
    token: str = ""
    # このプロセスが起動した時刻(VER1.7.1)。PID は使い回されるので、番号と起動時刻の
    # 両方が合うときだけ「前回のツールが居る」とする。前の版のロックには無い(0)
    proc_started: float = 0.0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


def lock_path() -> Path:
    return config.local_dir("runtime") / "instance.lock"


def read_lock() -> Optional[LockInfo]:
    try:
        raw = json.loads(lock_path().read_text(encoding="utf-8"))
        return LockInfo(**{k: raw[k] for k in LockInfo.__dataclass_fields__ if k in raw})
    except FileNotFoundError:
        return None
    except Exception as exc:                          # noqa: BLE001 - 壊れたロックは無いものとする
        log.warning("ロックを読めませんでした: %s", exc)
        return None


def write_lock(info: LockInfo) -> None:
    path = lock_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(info), ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    log.info("ロックを書きました: pid=%s port=%s", info.pid, info.port)


def remove_lock(pid: Optional[int] = None) -> None:
    """`pid` を渡すと、そのプロセスのロックのときだけ消す(後から来た別の起動のものを消さない)。"""
    if pid is not None:
        info = read_lock()
        if info is not None and info.pid != pid:
            return
    try:
        lock_path().unlink()
        log.info("ロックを消しました")
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("ロックを消せませんでした: %s", exc)


def try_acquire() -> bool:
    """**作れたかどうか**で決める(O_CREAT | O_EXCL)。2つ目は必ず失敗する。"""
    path = lock_path()
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(asdict(build_lock_info(STARTING_PORT)), fh, ensure_ascii=False)
    return True


def build_lock_info(port: int, token: str = "") -> LockInfo:
    return LockInfo(app_id=config.app_id(), pid=os.getpid(), port=port,
                    started_at=time.time(), python=sys.executable,
                    app_root=str(config.BASE_DIR), token=token,
                    proc_started=process_start_time(os.getpid()) or 0.0)


# ------------------------------------------------------------------
# プロセス
# ------------------------------------------------------------------
# プロセスの道具(生きているか・起動コマンド・プロキシを通さない要求・応答の確認)は
# **process_manager.py の1か所に置く。** 止める入口は、ほかの部品が欠けていても
# 動かす必要があるので、標準ライブラリだけで書いてあちらに持たせている
from process_manager import (CLEANED_MESSAGE, confirm_ours,  # noqa: E402,F401
                             is_process_alive, kill_process, local_request,
                             lock_owner_status, probe_health, process_command_line,
                             process_start_time)

HUNG_WAIT_SEC = 5.0          # 前回のツールが居るのに応答しないとき、待つ長さ
KILL_WAIT_SEC = 8.0          # 止めてから居なくなるまで


def is_our_app(health: Optional[dict]) -> bool:
    return bool(health) and health.get("app_id") == config.app_id()


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """本番の待ち受けと**同じソケット設定**で開けるか試す(server.prepare_socket)。"""
    from server import prepare_socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            prepare_socket(s)
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick_port() -> Optional[int]:
    base = config.base_port()
    for port in range(base, base + config.port_retry() + 1):
        if is_port_free(port, config.host()):
            return port
        log.info("ポート %s は使われています", port)
    return None


# ------------------------------------------------------------------
# 判断
# ------------------------------------------------------------------
@dataclass
class GuardResult:
    running: bool               # 生きている同じアプリが居る
    url: str = ""
    message: str = ""


def check_existing() -> GuardResult:
    """ロックを見て、すでに動いているか決める。死んだロックは片付ける。"""
    info = read_lock()
    if info is None:
        return GuardResult(False)
    if info.app_id != config.app_id():
        log.warning("別のアプリのロックがありました(%s)。片付けます", info.app_id)
        remove_lock()
        return GuardResult(False)
    if info.port == STARTING_PORT:
        return _wait_for_starting(info)
    if is_our_app(probe_health(info.port)):
        return GuardResult(True, info.url, "すでに起動しています")
    owner, reason = lock_owner_status(asdict(info))
    if not owner:
        # PC の再起動などで残ったロック。番号を使い回している別のプログラムには触らない(VER1.7.1)
        log.info("残っていたロックを片付けます: %s", reason)
        remove_lock()
        return GuardResult(False)
    # 前回のツールが本当に居るのに応答しない。起動の直後か、固まっている。少しだけ待つ
    deadline = time.time() + HUNG_WAIT_SEC
    while time.time() < deadline:
        if is_our_app(probe_health(info.port)):
            return GuardResult(True, info.url, "すでに起動しています")
        time.sleep(0.5)
    return _replace_hung(info, reason)


def _replace_hung(info: LockInfo, reason: str) -> GuardResult:
    """応答しない前回のツールを終わらせて、起動し直す(VER1.7.1)。"""
    if not confirm_ours(asdict(info)):
        log.warning("応答しない pid=%s がこのアプリか確かめられないので止めません", info.pid)
        return GuardResult(True, "", f"前の起動(pid {info.pid})が応答しません。"
                                     "stop.bat で止めてから、もう一度起動してください")
    log.warning("前回のツールが %.0f 秒たっても応答しません(%s)。終わらせて起動し直します",
                HUNG_WAIT_SEC, reason)
    try:
        kill_process(info.pid)
    except Exception as exc:                          # noqa: BLE001
        log.warning("止められませんでした: %s", exc)
    deadline = time.time() + KILL_WAIT_SEC
    while time.time() < deadline and is_process_alive(info.pid):
        time.sleep(0.3)
    if is_process_alive(info.pid):
        return GuardResult(True, "", f"前の起動(pid {info.pid})が応答せず、止められませんでした。"
                                     "タスクマネージャーの「詳細」で、この番号の python / pythonw を終了してください")
    log.info("前回のツールを終わらせました。%s", CLEANED_MESSAGE)
    remove_lock(pid=info.pid)
    return GuardResult(False)


def _wait_for_starting(info: LockInfo) -> GuardResult:
    deadline = time.time() + STARTING_WAIT_SEC
    while time.time() < deadline:
        current = read_lock()
        if current is None:
            return GuardResult(False)
        if current.port != STARTING_PORT:
            return check_existing()
        owner, reason = lock_owner_status(asdict(current))
        if not owner:
            log.info("起動途中のまま残っていたロックを片付けます: %s", reason)
            remove_lock()
            return GuardResult(False)
        time.sleep(0.3)
    if lock_owner_status(asdict(info))[0]:
        return GuardResult(True, "", "前の起動がまだ終わっていません。少し待ってからもう一度起動してください")
    remove_lock()
    return GuardResult(False)
