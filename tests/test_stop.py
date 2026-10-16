"""止める入口(stop.bat → process_manager.py)と、起動に失敗したときの見え方。

all-tools で起きたこと(2026-10-16): 起動の途中で本体を組み立てられなかった Python が
理由の画面を出したまま残り、stop.bat でも止まらず、フォルダを消せなかった。
  - 待機画面が止める合図に答えていなかった
  - stop.bat が、止まったかを確かめずに「終わってもらいました」と言っていた
同じ状況を作って、このツールでは起きないことを確かめる。
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import launch_guard
import process_manager as pm
from app.application import App
from app.core import config
from app.web import Request

ROOT = Path(__file__).resolve().parent.parent
PORT = 18755
STDLIB_OK = {"__future__", "argparse", "json", "os", "signal", "subprocess", "sys", "time",
             "urllib", "datetime", "pathlib", "typing", "ctypes"}


class ShutdownWhileBrokenTest(unittest.TestCase):
    """準備に失敗して理由を出している最中でも、止める合図に答える。"""

    def test_shutdown_answers_when_startup_failed(self):
        stopped = []
        app = App(port=PORT, token="T", on_shutdown=lambda: stopped.append(True))
        app.state.ready = False
        app.state.startup_error = "自分自身に接続できません"
        headers = {"Host": f"127.0.0.1:{PORT}", "X-Tool-Token": "T"}
        resp = app.handle(Request.build("POST", "/api/shutdown", headers, b"{}"))
        self.assertEqual(resp.status, 200)
        # 止める処理は別のスレッドで走る
        for _ in range(50):
            if stopped:
                break
            import time
            time.sleep(0.02)
        self.assertEqual(stopped, [True])
        # 業務の要求は断る(503)。止める口だけは開けておく
        self.assertEqual(app.handle(Request.build("GET", "/api/state", headers)).status, 503)
        # トークンは要る(ほかのページから止めさせない)
        no_token = {"Host": f"127.0.0.1:{PORT}"}
        self.assertEqual(app.handle(Request.build("POST", "/api/shutdown", no_token, b"{}")).status, 403)

    def test_waiting_screen_sends_heartbeat(self):
        text = (ROOT / "loading.html").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/alive"', text)
        self.assertIn('sendBeacon("/api/bye"', text)


class StopConfirmsTest(unittest.TestCase):
    """「終わった」と言うのは、PID が居なくなったのを確かめてから。"""

    INFO = {"app_id": "nlm.file-list-tool", "pid": 424242, "port": 1, "token": "T",
            "app_root": str(ROOT)}

    def setUp(self):
        patches = [mock.patch.object(pm, "GRACEFUL_WAIT_SEC", 0.1),
                   mock.patch.object(pm, "EXIT_WAIT_SEC", 0.1),
                   mock.patch.object(pm, "KILL_WAIT_SEC", 0.1),
                   mock.patch.object(pm, "read_lock", return_value=dict(self.INFO)),
                   mock.patch.object(pm, "remove_lock"),
                   mock.patch.object(pm, "write_launcher_log")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_stop(self, *, answers, shutdown, alive, ours=True, kill_works=True, force=False):
        state = {"alive": alive, "answers": answers}

        def kill(pid):
            if kill_works:
                state["alive"] = False

        def ask(info, f):
            if shutdown.get("ok") and shutdown.get("exits"):
                state["alive"] = False
                state["answers"] = False
            elif shutdown.get("ok"):
                state["answers"] = False          # 待ち受けは閉じたが、プロセスは残った
            return shutdown

        with mock.patch.object(pm, "_answers", side_effect=lambda info: state["answers"]), \
                mock.patch.object(pm, "_request_shutdown", side_effect=ask), \
                mock.patch.object(pm, "is_process_alive", side_effect=lambda pid: state["alive"]), \
                mock.patch.object(pm, "looks_like_ours", return_value=ours), \
                mock.patch.object(pm, "kill_process", side_effect=kill) as killer:
            code, message = pm.stop(force=force)
        return code, message, killer

    def test_graceful(self):
        code, message, killer = self.run_stop(answers=True, shutdown={"ok": True, "exits": True}, alive=True)
        self.assertEqual((code, message), (0, "正常に終了しました"))
        killer.assert_not_called()

    def test_accepted_but_process_remains_then_killed(self):
        # all-tools の不具合: ここで「終わってもらいました」と言っていた
        code, message, killer = self.run_stop(answers=True, shutdown={"ok": True}, alive=True)
        self.assertEqual(code, 0)
        self.assertIn("プロセスを止めました", message)
        killer.assert_called_once_with(424242)

    def test_kill_did_not_work_is_reported(self):
        code, message, _ = self.run_stop(answers=True, shutdown={"ok": True}, alive=True, kill_works=False)
        self.assertEqual(code, 1)
        self.assertIn("止まりませんでした", message)
        self.assertIn("424242", message)
        pm.remove_lock.assert_not_called()

    def test_refused_request_falls_back_to_pid(self):
        code, message, killer = self.run_stop(answers=True, shutdown={"ok": False, "refused": 503}, alive=True)
        self.assertEqual(code, 0)
        killer.assert_called_once()

    def test_no_answer_falls_back_to_pid(self):
        code, _, killer = self.run_stop(answers=False, shutdown={}, alive=True)
        self.assertEqual(code, 0)
        killer.assert_called_once()

    def test_not_ours_is_left_alone(self):
        code, message, killer = self.run_stop(answers=False, shutdown={}, alive=True, ours=False)
        self.assertEqual(code, 1)
        self.assertIn("このアプリではない", message)
        killer.assert_not_called()

    def test_busy_is_not_stopped_without_force(self):
        code, message, killer = self.run_stop(answers=True, shutdown={"ok": False, "busy": True,
                                                                     "running": ["全角→半角リネーム"]}, alive=True)
        self.assertEqual(code, 2)
        self.assertIn("--force", message)
        killer.assert_not_called()

    def test_already_gone(self):
        code, message, _ = self.run_stop(answers=False, shutdown={}, alive=False)
        self.assertEqual(code, 0)
        self.assertIn("片付けました", message)


class StopEntryStandaloneTest(unittest.TestCase):
    """止める入口は、ほかの部品が欠けていても動く(標準ライブラリだけ)。"""

    def test_imports_only_stdlib(self):
        tree = ast.parse((ROOT / "process_manager.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        self.assertLessEqual(names, STDLIB_OK, names - STDLIB_OK)

    def test_same_lock_as_launch_guard(self):
        self.assertEqual(pm.lock_path(), launch_guard.lock_path())

    def test_runs_alone_in_half_deleted_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(ROOT / "process_manager.py", tmp)          # app\ も config\ も無い
            env = dict(os.environ, FILELIST_TOOL_LOCAL_DIR=str(Path(tmp) / "local"))
            out = subprocess.run([sys.executable, "-I", "process_manager.py"], cwd=tmp, env=env,
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("起動していません", out.stdout)
            self.assertEqual(out.stderr, "")


class StartupFailureTest(unittest.TestCase):
    """部品が欠けたフォルダから起動したら、黙って消えずに理由を言う。ロックも残さない。"""

    def test_missing_services_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "tool"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests"))
            shutil.rmtree(copy / "app" / "services")
            local = Path(tmp) / "local"
            env = dict(os.environ, FILELIST_TOOL_LOCAL_DIR=str(local))
            out = subprocess.run([sys.executable, "start_app.py", "--no-browser"], cwd=copy, env=env,
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 1)
            self.assertIn("app/services", out.stderr)
            self.assertIn("配布フォルダを丸ごと入れ直してください", out.stderr)
            self.assertIn("app/services", (local / "logs" / "launcher.log").read_text(encoding="utf-8"))
            self.assertFalse((local / "runtime" / "instance.lock").exists())

    def test_broken_config_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "tool"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests"))
            (copy / "config" / "app.json").write_text("{壊れた", encoding="utf-8")
            local = Path(tmp) / "local"
            env = dict(os.environ, FILELIST_TOOL_LOCAL_DIR=str(local))
            out = subprocess.run([sys.executable, "start_app.py", "--no-browser"], cwd=copy, env=env,
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 1)
            self.assertIn("config", out.stderr)
            self.assertNotIn("Traceback (most recent call last)", out.stderr.split("ログ:")[0])


if __name__ == "__main__":
    unittest.main()
