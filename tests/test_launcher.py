"""起動基盤: ロック・多重起動・自動終了・起動ファイルの文字コード。"""
import os
import re
import unittest
from pathlib import Path

import launch_guard
from app.application import AppState
from app.core import config
from app.core.idle_exit import IdleMonitor

ROOT = Path(__file__).resolve().parent.parent


class LockTest(unittest.TestCase):
    def setUp(self):
        launch_guard.remove_lock()

    def tearDown(self):
        launch_guard.remove_lock()

    def test_second_acquire_fails(self):
        self.assertTrue(launch_guard.try_acquire())
        self.assertFalse(launch_guard.try_acquire())

    def test_lock_lives_in_local_dir(self):
        self.assertEqual(launch_guard.lock_path().parent, config.local_root() / "runtime")

    def test_stale_lock_is_cleared(self):
        info = launch_guard.build_lock_info(1)
        info.pid = 2 ** 22 + 12345             # 居ない PID
        launch_guard.write_lock(info)
        result = launch_guard.check_existing()
        self.assertFalse(result.running)
        self.assertIsNone(launch_guard.read_lock())

    def test_other_app_lock_is_cleared(self):
        info = launch_guard.build_lock_info(1)
        info.app_id = "other.app"
        launch_guard.write_lock(info)
        self.assertFalse(launch_guard.check_existing().running)

    def test_remove_only_own(self):
        info = launch_guard.build_lock_info(1)
        launch_guard.write_lock(info)
        launch_guard.remove_lock(pid=os.getpid() + 1)
        self.assertIsNotNone(launch_guard.read_lock())
        launch_guard.remove_lock(pid=os.getpid())
        self.assertIsNone(launch_guard.read_lock())

    def test_is_our_app(self):
        self.assertTrue(launch_guard.is_our_app({"app_id": config.app_id()}))
        self.assertFalse(launch_guard.is_our_app({"app_id": "x"}))
        self.assertFalse(launch_guard.is_our_app(None))

    def test_process_alive(self):
        self.assertTrue(launch_guard.is_process_alive(os.getpid()))
        self.assertFalse(launch_guard.is_process_alive(0))


class IdleTest(unittest.TestCase):
    def monitor(self, state):
        return IdleMonitor(state, idle_seconds=90, bye_grace=8, on_idle=lambda why: None)

    def test_never_connected_never_exits(self):
        s = AppState()
        self.assertEqual(self.monitor(s).reason(10 ** 10), "")

    def test_heartbeat_timeout(self):
        s = AppState()
        s.alive()
        m = self.monitor(s)
        self.assertEqual(m.reason(s.last_alive + 89), "")
        self.assertIn("90", m.reason(s.last_alive + 91))

    def test_bye_grace_and_cancel(self):
        s = AppState()
        s.alive()
        s.bye()
        m = self.monitor(s)
        self.assertEqual(m.reason(s.bye_at + 5), "")
        self.assertEqual(m.reason(s.bye_at + 9), "画面が閉じられました")
        s.alive()                                     # 再読込で戻ってきた
        self.assertEqual(m.reason(s.last_alive + 9), "")

    def test_busy_never_exits(self):
        s = AppState()
        s.alive()
        s.begin("全角→半角リネーム")
        self.assertEqual(self.monitor(s).reason(s.last_alive + 10 ** 6), "")


class LaunchFilesTest(unittest.TestCase):
    """Start.vbs / start.bat / stop.bat は CP932 + CRLF(python-web-tools と同じ約束)。"""

    def test_encoding_and_line_endings(self):
        for name in ("Start.vbs", "start.bat", "stop.bat"):
            raw = (ROOT / name).read_bytes()
            with self.subTest(name=name):
                raw.decode("cp932")                       # 読めること
                self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
                with self.assertRaises(UnicodeDecodeError):
                    raw.decode("utf-8")                   # UTF-8 で保存し直していないこと

    def test_bat_ascii_before_chcp(self):
        for name in ("start.bat", "stop.bat"):
            raw = (ROOT / name).read_bytes()
            head = raw[:raw.index(b"chcp 932")]
            self.assertTrue(all(b < 0x80 for b in head), name)

    def test_vbs_starts_start_app(self):
        text = (ROOT / "Start.vbs").read_bytes().decode("cp932")
        self.assertIn('"start_app.py"', text)
        self.assertRegex(text, re.compile(r"pythonw "))


if __name__ == "__main__":
    unittest.main()


class PortTest(unittest.TestCase):
    def test_busy_port_is_detected_and_server_refuses_it(self):
        import socket
        from server import AppServer
        from app.application import App
        with socket.socket() as other:                     # ほかのアプリが待ち受けている
            other.bind(("127.0.0.1", 0))
            other.listen()
            port = other.getsockname()[1]
            self.assertFalse(launch_guard.is_port_free(port))
            with self.assertRaises(OSError):
                AppServer(App(port=port), "127.0.0.1", port)

    def test_port_free_after_close(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.assertTrue(launch_guard.is_port_free(port))
