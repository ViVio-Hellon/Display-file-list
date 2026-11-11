"""デスクトップ版の入口(bridge.py)と、ブラウザ版とのすみ分け(VER2.0.0)。

- bridge.py は**ソケットを開くと落ちる**ようにして動かしても、画面・操作・終了が通る(ポートを使わない)
- ブラウザ版とデスクトップ版は同時に動かない。**どちらを後から開いても止まる**
- stop.bat はデスクトップ版も閉じる(窓に「閉じて」と頼む。処理の途中なら閉じない)
- 版は config/app.json・src-tauri/Cargo.toml・src-tauri/tauri.conf.json の3か所で同じ
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import process_manager as pm

ROOT = Path(__file__).resolve().parent.parent
NO_SOCKET = ROOT / "tests" / "desktop" / "no_socket_bridge.py"


class BridgeProcess:
    """bridge.py を子として動かし、外枠(Rust)の代わりに標準入出力で話す。"""

    def __init__(self, local: Path, *, token: str = "TK", exe_pid: int = 0) -> None:
        env = dict(os.environ, FILELIST_TOOL_LOCAL_DIR=str(local), FILELIST_TOOL_TOKEN=token,
                   PYTHONIOENCODING="utf-8")
        if exe_pid:
            env["FILELIST_TOOL_EXE_PID"] = str(exe_pid)
        self.token = token
        self.proc = subprocess.Popen([sys.executable, str(NO_SOCKET)], cwd=ROOT, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 0
        self.stderr = b""
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        self.stderr = self.proc.stderr.read()

    def read(self) -> tuple:
        line = self.proc.stdout.readline()
        if not line:
            return None, b""
        head = json.loads(line)
        size = head.get("len", 0) or 0
        return head, (self.proc.stdout.read(size) if size else b"")

    def send(self, method: str, path: str, query: str = "", body: bytes = b"", headers=(), *, size=None) -> int:
        self.next_id += 1
        head = {"id": self.next_id, "method": method, "path": path, "query": query,
                "headers": [["Host", "app.localhost"], ["X-Tool-Token", self.token], *headers],
                "len": len(body) if size is None else size}
        self.proc.stdin.write(json.dumps(head).encode() + b"\n" + body)
        self.proc.stdin.flush()
        return self.next_id

    def call(self, method: str, path: str, query: str = "", body: bytes = b"", headers=()) -> tuple:
        sent = self.send(method, path, query, body, headers)
        while True:
            head, data = self.read()
            if head is None or head.get("id") == sent:
                return head, data

    def finish(self, timeout: float = 15) -> int:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait()


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name) / "local"
        self.folder = Path(self.tmp.name) / "A班"
        self.folder.mkdir()
        (self.folder / "6-1_梱包手順書.xlsx").write_text("x", encoding="utf-8")
        (self.folder / "3-1_写真").mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_screen_operations_and_exit_without_any_socket(self):
        b = BridgeProcess(self.local)
        self.addCleanup(b.finish)
        first, _ = b.read()
        self.assertEqual(first["event"], "static")
        self.assertEqual(first["static"], [["/static/", str((ROOT / "app" / "static").resolve())]])
        self.assertEqual(b.read()[0], {"event": "started"})

        head, body = b.call("GET", "/")
        self.assertEqual(head["status"], 200)
        self.assertIn('content="TK"'.encode(), body)                 # 窓の合言葉で画面が動く
        head, body = b.call("GET", "/api/filelist", "folder=" + str(self.folder))
        self.assertEqual([r["doc_no"] for r in json.loads(body)["rows"]], ["6-1"])
        head, body = b.call("GET", "/api/filelist", "target=folders&folder=" + str(self.folder))
        self.assertEqual([r["title"] for r in json.loads(body)["rows"]], ["写真"])
        head, body = b.call("GET", "/api/health")
        health = json.loads(body)
        self.assertEqual((health["desktop"], health["port"]), (True, 0))
        self.assertEqual(pm.desktop_marker_path().name, "desktop.json")
        self.assertTrue((self.local / "runtime" / "desktop.json").exists())

        # 守りはそのまま: 合言葉が違えば断る・宛先の名前が違えば断る
        b.token = "wrong"
        head, _ = b.call("GET", "/api/state")
        self.assertEqual(head["status"], 403)
        b.token = "TK"
        b.send("GET", "/api/state", headers=[["Host", "127.0.0.1:8753"]])
        head, _ = b.read()
        self.assertEqual(head["status"], 400)                          # 待ち受けの宛先は受けない

        # 大きすぎる1件はその1件だけ断り、続けて使える
        sent = b.send("POST", "/api/log/client", body=b"", size=9 * 1024 * 1024)
        b.proc.stdin.write(b"x" * (9 * 1024 * 1024))
        b.proc.stdin.flush()
        head, _ = b.read()
        self.assertEqual((head["id"], head["status"]), (sent, 413))
        self.assertEqual(b.call("GET", "/api/health")[0]["status"], 200)

        # 画面の「終了」(窓の × も外枠がこれを呼ぶ)→ quit を知らせる → 外枠が閉じれば終わる
        b.send("POST", "/api/shutdown", body=b"{}", headers=[["Content-Type", "application/json"]])
        events = [b.read()[0], b.read()[0]]
        self.assertIn({"event": "quit"}, events)
        self.assertEqual(b.finish(), 0)
        self.assertFalse((self.local / "runtime" / "desktop.json").exists())
        self.assertNotIn("ソケット".encode(), b.stderr)                # ソケットを開こうとしていない

    def test_refuses_when_browser_version_is_running(self):
        """ブラウザ版が先に動いている → デスクトップ版の Python は起動を断り、理由を窓へ。"""
        env = dict(os.environ, FILELIST_TOOL_LOCAL_DIR=str(self.local))
        browser = subprocess.Popen([sys.executable, "start_app.py", "--no-browser"], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threading.Thread(target=browser.wait, daemon=True).start()
        self.addCleanup(lambda: subprocess.run([sys.executable, "process_manager.py"], cwd=ROOT, env=env,
                                               capture_output=True, timeout=60))
        lock = self.local / "runtime" / "instance.lock"
        deadline = time.time() + 30
        while time.time() < deadline and not (lock.exists() and json.loads(lock.read_text("utf-8") or "{}").get("port")):
            time.sleep(0.2)
        b = BridgeProcess(self.local)
        head, _ = b.read()
        self.assertEqual(head["event"], "fatal")
        self.assertEqual(head["message"], "ブラウザ版のファイル名一覧取得が動いています")
        self.assertIn("stop.bat", head["hint"])
        self.assertEqual(b.finish(), 1)
        self.assertFalse((self.local / "runtime" / "desktop.json").exists())

    def test_browser_version_refuses_when_desktop_is_running(self):
        """デスクトップ版が先に動いている → ブラウザ版(Start.vbs / start.bat)は起動しない。"""
        b = BridgeProcess(self.local)
        self.addCleanup(b.finish)
        self.assertEqual(b.read()[0]["event"], "static")
        self.assertEqual(b.read()[0]["event"], "started")
        env = dict(os.environ, FILELIST_TOOL_LOCAL_DIR=str(self.local))
        res = subprocess.run([sys.executable, "start_app.py", "--no-browser"], cwd=ROOT, env=env,
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(res.returncode, 1)
        self.assertIn("デスクトップ版のファイル名一覧取得が動いています", res.stderr)
        self.assertFalse((self.local / "runtime" / "instance.lock").exists())

    def test_stop_bat_closes_desktop_window(self):
        """stop.bat → 窓に「閉じて」と頼む(ここでは外枠の代わりに標準入力を閉じる)。"""
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # 窓(exe)の代わり
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        b = BridgeProcess(self.local, exe_pid=sleeper.pid)
        self.addCleanup(b.finish)
        b.read()
        b.read()
        asked = []

        def close_window(pid):
            asked.append(pid)
            b.proc.stdin.close()                                       # 外枠が閉じたのと同じ
            threading.Thread(target=b.proc.wait, daemon=True).start()
            return 1

        with mock.patch.dict(os.environ, {"FILELIST_TOOL_LOCAL_DIR": str(self.local)}), \
                mock.patch.object(pm, "_close_windows_of", side_effect=close_window):
            alive, raw, _ = pm.desktop_status()
            self.assertTrue(alive)
            self.assertEqual(raw["exe_pid"], sleeper.pid)
            code, message = pm.stop()
        self.assertEqual((code, message), (0, "デスクトップ版の窓を閉じました"))
        self.assertEqual(asked, [sleeper.pid])
        self.assertFalse((self.local / "runtime" / "desktop.json").exists())

    def test_stop_bat_does_not_close_while_busy(self):
        """窓が閉じない(リネームの途中で窓が断った)→ 2 を返して --force を案内する。"""
        raw = {"pid": os.getpid(), "exe_pid": os.getpid(), "started_at": time.time()}
        with mock.patch.object(pm, "_close_windows_of", return_value=1), \
                mock.patch.object(pm, "DESKTOP_CLOSE_WAIT_SEC", 0.3), \
                mock.patch.object(pm, "_exe_is_desktop", return_value=True):
            code, message = pm.stop_desktop(raw)
        self.assertEqual(code, 2)
        self.assertIn("--force", message)

    def test_stale_desktop_marker_is_not_running(self):
        """落ちたデスクトップ版の印・番号が使い回された印は「動いていない」。"""
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        started = pm.process_start_time(sleeper.pid)
        with mock.patch.dict(os.environ, {"FILELIST_TOOL_LOCAL_DIR": str(self.local)}):
            self.assertFalse(pm.desktop_status({"pid": 0})[0])
            if started is not None:
                alive, _, reason = pm.desktop_status({"pid": sleeper.pid, "proc_started": started - 3600})
                self.assertFalse(alive)
                self.assertIn("別のプログラム", reason)
            alive, _, reason = pm.desktop_status({"pid": sleeper.pid, "proc_started": started or 0})
            self.assertFalse(alive)                                    # bridge.py を動かしていない
            self.assertIn("起動コマンド", reason)


class GateTest(unittest.TestCase):
    def test_gate_is_exclusive_between_processes(self):
        import launch_guard
        script = ("import sys, time; sys.path.insert(0, r'%s'); import launch_guard\n"
                  "with launch_guard.startup_gate():\n    print('in', flush=True); time.sleep(2)\n") % ROOT
        holder = subprocess.Popen([sys.executable, "-c", script], cwd=ROOT, stdout=subprocess.PIPE)
        self.addCleanup(holder.wait)
        self.assertEqual(holder.stdout.readline().strip(), b"in")
        t0 = time.time()
        with launch_guard.startup_gate(timeout=10):
            waited = time.time() - t0
        self.assertGreater(waited, 0.8)                                 # 相手が放すまで待った
        self.assertLess(waited, 8)


class VersionTest(unittest.TestCase):
    def test_versions_agree(self):
        app = json.loads((ROOT / "config" / "app.json").read_text(encoding="utf-8"))["version"]
        cargo = re.search(r'^version = "([^"]+)"', (ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"), re.M)
        tauri = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual((cargo.group(1), tauri), (app, app))

    def test_names_agree_between_rust_and_python(self):
        main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        bridge = (ROOT / "src-tauri" / "src" / "bridge.rs").read_text(encoding="utf-8")
        from app.application import DESKTOP_HOSTS
        self.assertIn('const SCHEME: &str = "app";', main)
        self.assertEqual(DESKTOP_HOSTS, ("app.localhost", "localhost"))
        self.assertIn('const LOCAL_NAME: &str = "FileListTool";', main)
        self.assertEqual(pm.DEFAULT_LOCAL_NAME, "FileListTool")
        for env in ("FILELIST_TOOL_TOKEN", "FILELIST_TOOL_EXE_PID"):
            self.assertIn(f'"{env}"', bridge)
        self.assertIn('join("desktop.lock")', main)


if __name__ == "__main__":
    unittest.main()
