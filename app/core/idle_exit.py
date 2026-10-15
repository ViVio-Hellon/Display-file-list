"""画面が居なくなったら終わる (基盤仕様書 2.9、監視レベル1)

画面は一定間隔で `POST /api/alive` を送り、閉じるときは `sendBeacon` で
`/api/bye` を送る。

| 場面 | 動き |
|---|---|
| 心拍が途切れた | `idle_exit_seconds`(既定90秒)で終わる |
| 閉じた合図を受けた | `bye_grace_seconds`(既定8秒)待ち、そのあいだに心拍が戻れば取り消す(再読込でも合図が飛ぶため) |
| リネームの途中 | 終わらない |
| 一度も画面が繋がっていない | 終わらない(`--no-browser` で起動した人を巻き添えにしない) |
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from . import logging_setup

log = logging_setup.get("server.idle")


class IdleMonitor:
    def __init__(self, state, *, idle_seconds: float, bye_grace: float,
                 on_idle: Callable[[str], None], interval: float = 2.0) -> None:
        self.state = state
        self.idle_seconds = idle_seconds
        self.bye_grace = bye_grace
        self.on_idle = on_idle
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="idle-exit", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def reason(self, now: float) -> str:
        """終わるべきなら理由、まだなら空文字。"""
        s = self.state
        if not s.ever_alive or s.busy_labels():
            return ""
        if s.bye_at and now - s.bye_at >= self.bye_grace and s.last_alive <= s.bye_at:
            return "画面が閉じられました"
        if now - s.last_alive >= self.idle_seconds:
            return f"画面の心拍が {int(self.idle_seconds)} 秒途切れました"
        return ""

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            why = self.reason(time.time())
            if why:
                log.info("自動終了します: %s", why)
                self.on_idle(why)
                return
