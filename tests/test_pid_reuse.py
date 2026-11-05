"""PID の使い回し(VER1.7.1)。

ツールは起動するときに PID をロックに書き、次の起動はその番号のプロセスが居れば「起動中」と
判断していた。Windows は番号を使い回すので、ツールが動いたまま PC を終了・再起動すると、
別のプログラムが同じ番号を持ち、いつまでも「起動中」で画面に接続できなかった
(stop.bat も「止めません」で終わり、ロックを消していなかった)。

いまは**番号と起動時刻の両方**が合うときだけ「前回のツールが居る」とする。前の版のロック
(起動時刻なし)は「ロックを書いた時刻より後に起動したプロセスは本人ではない」とする。
ここでは本物のプロセスを立てて確かめる。
"""
import subprocess
import sys
import time
import unittest
from dataclasses import asdict
from unittest import mock

import launch_guard
import process_manager as pm


class StartTimeTest(unittest.TestCase):
    def setUp(self):
        self.child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(self.child.wait)
        self.addCleanup(self.child.kill)
        time.sleep(0.2)

    def test_start_time_is_read(self):
        started = pm.process_start_time(self.child.pid)
        if started is None:
            self.skipTest("この OS では起動時刻が取れない")
        self.assertLess(abs(started - time.time()), 30)
        self.assertIsNone(pm.process_start_time(0))

    def lock(self, **kw):
        info = {"app_id": "nlm.file-list-tool", "pid": self.child.pid, "port": 1}
        info.update(kw)
        return info

    def test_same_number_and_start_time_is_the_owner(self):
        started = pm.process_start_time(self.child.pid)
        if started is None:
            self.skipTest("起動時刻が取れない")
        self.assertTrue(pm.lock_owner_alive(self.lock(proc_started=started)))

    def test_same_number_other_start_time_is_not_the_owner(self):
        """PC を再起動したあと、別のプログラムが同じ番号を持っている。"""
        started = pm.process_start_time(self.child.pid)
        if started is None:
            self.skipTest("起動時刻が取れない")
        owner, reason = pm.lock_owner_status(self.lock(proc_started=started - 86400))
        self.assertFalse(owner)
        self.assertIn("別のプログラム", reason)

    def test_old_lock_written_before_the_process_started(self):
        """前の版のロック(起動時刻なし)。ロックを書いた時刻より後に起動したプロセスは本人ではない。"""
        if pm.process_start_time(self.child.pid) is None:
            self.skipTest("起動時刻が取れない")
        self.assertFalse(pm.lock_owner_alive(self.lock(started_at=time.time() - 3600)))
        # ロックより前から居るプロセスは、書いた本人かもしれない(誤って片付けない)
        self.assertTrue(pm.lock_owner_alive(self.lock(started_at=time.time() + 60)))

    def test_gone_process_is_not_the_owner(self):
        self.child.kill()
        self.child.wait()
        self.assertFalse(pm.lock_owner_alive(self.lock(proc_started=1.0)))


class OwnLockTest(unittest.TestCase):
    def test_lock_records_own_start_time(self):
        info = launch_guard.build_lock_info(8753, "T")
        if info.proc_started == 0.0:
            self.skipTest("起動時刻が取れない")
        self.assertTrue(pm.lock_owner_alive(asdict(info)))


class GuardTest(unittest.TestCase):
    """起動のときの判断。"""

    def setUp(self):
        launch_guard.remove_lock()
        self.child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(self.child.wait)
        self.addCleanup(self.child.kill)
        self.addCleanup(launch_guard.remove_lock)
        time.sleep(0.2)

    def write(self, **kw):
        info = launch_guard.build_lock_info(1, "T")
        info.pid = self.child.pid
        for k, v in kw.items():
            setattr(info, k, v)
        launch_guard.write_lock(info)
        return info

    def test_reused_pid_lock_is_cleaned_and_start_goes_on(self):
        started = pm.process_start_time(self.child.pid)
        if started is None:
            self.skipTest("起動時刻が取れない")
        self.write(proc_started=started - 86400)
        with mock.patch.object(launch_guard, "kill_process") as killer:
            result = launch_guard.check_existing()
        self.assertFalse(result.running)                       # 普通に起動する
        self.assertIsNone(launch_guard.read_lock())             # 残りものは片付けた
        killer.assert_not_called()                               # 別のプログラムには触らない
        self.assertIsNone(self.child.poll())

    def test_old_version_lock_with_reused_pid(self):
        if pm.process_start_time(self.child.pid) is None:
            self.skipTest("起動時刻が取れない")
        self.write(proc_started=0.0, started_at=time.time() - 3600)
        with mock.patch.object(launch_guard, "kill_process") as killer:
            self.assertFalse(launch_guard.check_existing().running)
        killer.assert_not_called()

    def test_reused_pid_while_starting(self):
        started = pm.process_start_time(self.child.pid)
        if started is None:
            self.skipTest("起動時刻が取れない")
        self.write(port=launch_guard.STARTING_PORT, proc_started=started - 86400)
        t0 = time.time()
        self.assertFalse(launch_guard.check_existing().running)
        self.assertLess(time.time() - t0, 3)                    # 15 秒待たない

    def test_real_previous_tool_hung_is_replaced(self):
        """前回のツールが本当に残っていて 5 秒たっても応答しない → 終わらせて起動し直す。"""
        started = pm.process_start_time(self.child.pid)
        if started is None:
            self.skipTest("起動時刻が取れない")
        self.write(proc_started=started)
        # 止めたあとの後始末(この試験では子プロセスなので、居なくなるには親が受け取る)
        reap = lambda pid: (self.child.kill(), self.child.wait(timeout=5))   # noqa: E731
        with mock.patch.object(launch_guard, "HUNG_WAIT_SEC", 0.3), \
                mock.patch.object(launch_guard, "confirm_ours", return_value=True), \
                mock.patch.object(launch_guard, "kill_process", side_effect=reap) as killer:
            result = launch_guard.check_existing()
        self.assertFalse(result.running)
        killer.assert_called_once_with(self.child.pid)
        self.assertIsNone(launch_guard.read_lock())

    def test_hung_but_not_confirmed_is_left_alone(self):
        started = pm.process_start_time(self.child.pid)
        if started is None:
            self.skipTest("起動時刻が取れない")
        self.write(proc_started=started)
        with mock.patch.object(launch_guard, "HUNG_WAIT_SEC", 0.3), \
                mock.patch.object(launch_guard, "confirm_ours", return_value=False):
            result = launch_guard.check_existing()
        self.assertTrue(result.running)
        self.assertIn("stop.bat", result.message)
        self.assertIsNone(self.child.poll())


class StopReusedPidTest(unittest.TestCase):
    """stop.bat。接続できないとき、残りもののロックを片付ける。"""

    def test_stop_cleans_reused_pid_lock(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.addCleanup(launch_guard.remove_lock)
        time.sleep(0.2)
        started = pm.process_start_time(child.pid)
        if started is None:
            self.skipTest("起動時刻が取れない")
        info = launch_guard.build_lock_info(1, "T")
        info.pid, info.proc_started = child.pid, started - 86400
        launch_guard.write_lock(info)
        with mock.patch.object(pm, "kill_process") as killer, \
                mock.patch.object(pm, "lock_path", launch_guard.lock_path):
            code, message = pm.stop()
        self.assertEqual(code, 0)
        self.assertIn("片付けました。Start.vbs で起動できます", message)
        killer.assert_not_called()
        self.assertIsNone(child.poll())
        self.assertIsNone(launch_guard.read_lock())


if __name__ == "__main__":
    unittest.main()
