"""API と守り。サーバを立てずに App.handle を直接呼ぶ。"""
import json
import tempfile
import unittest
from pathlib import Path

from app.application import App
from app.web import Request

PORT = 18753
HOST = f"127.0.0.1:{PORT}"


class WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.stopped = []
        self.app = App(port=PORT, token="T", on_shutdown=lambda: self.stopped.append(True))
        self.app.state.ready = True

    def tearDown(self):
        self.tmp.cleanup()

    def q(self, path):
        from urllib.parse import quote
        return quote(str(path))

    def call(self, method, path, body=None, *, token="T", host=HOST, headers=None):
        h = {"Host": host}
        if token:
            h["X-Tool-Token"] = token
        h.update(headers or {})
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        resp = self.app.handle(Request.build(method, path, h, raw))
        data = json.loads(resp.body) if resp.content_type.startswith("application/json") else resp.body
        return resp.status, data

    # --- 守り ----------------------------------------------------------
    def test_host_checked(self):
        self.assertEqual(self.call("GET", "/", host="evil.example:80")[0], 400)
        self.assertEqual(self.call("GET", "/", host=f"localhost:{PORT}")[0], 200)

    def test_token_required(self):
        self.assertEqual(self.call("GET", "/api/state", token="")[0], 403)
        self.assertEqual(self.call("GET", "/api/state", token="wrong")[0], 403)
        self.assertEqual(self.call("GET", "/api/state", token="ü")[0], 403)
        # /print は VER1.4.0 でなくした。VER1.6.0 の印刷は画面の中で紙面を作る(サーバの経路は要らない)
        self.assertEqual(self.call("GET", f"/print?folder={self.q(self.base)}")[0], 404)
        self.assertEqual(self.call("GET", "/api/health", token="")[0], 200)

    def test_cross_site_refused(self):
        status, _ = self.call("GET", "/api/state", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)

    def test_not_ready(self):
        self.app.state.ready = False
        self.assertEqual(self.call("GET", "/api/state")[0], 503)
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("起動しています".encode("utf-8"), body)

    def test_unknown(self):
        self.assertEqual(self.call("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.call("GET", "/api/rename/preview")[0], 405)
        self.assertEqual(self.call("GET", "/static/../application.py")[0], 404)

    def test_static(self):
        status, body = self.call("GET", "/static/js/app.js")
        self.assertEqual(status, 200)

    def test_index_has_token(self):
        status, body = self.call("GET", "/")
        self.assertIn(b'content="T"', body)
        self.assertNotIn(b"{{", body)

    # --- 一覧 ----------------------------------------------------------
    def test_filelist(self):
        (self.base / "A班").mkdir()
        (self.base / "A班" / "6-1_手順.pdf").write_text("x", encoding="utf-8")
        # 「パスのコピー」で付く " があっても読める
        status, data = self.call("GET", "/api/filelist?folder=" + self.q(f'"{self.base / "A班"}"'))
        self.assertEqual(status, 200)
        self.assertEqual((data["title"], data["folder"]), ("A班", str(self.base / "A班")))
        self.assertEqual([(r["doc_no"], r["title"], r["ext"]) for r in data["rows"]],
                         [("6-1", "手順", "pdf")])
        # 使えたパスを覚えて、次に開いたときに入れる
        _, state = self.call("GET", "/api/state")
        self.assertEqual(state["list_dir"], str(self.base / "A班"))

    def test_folderlist(self):
        """選択ボタンで「フォルダ」(VER1.7.0)。直下のフォルダの一覧。選んだものも覚える。"""
        (self.base / "A班" / "6-1_梱包").mkdir(parents=True)
        (self.base / "A班" / "6-1_手順.pdf").write_text("x", encoding="utf-8")
        _, state = self.call("GET", "/api/state")
        self.assertEqual(state["list_target"], "files")                  # 初めはファイル(VBA どおり)
        status, data = self.call("GET", "/api/filelist?target=folders&folder=" + self.q(self.base / "A班"))
        self.assertEqual(status, 200)
        self.assertEqual(data["target"], "folders")
        self.assertEqual([(r["doc_no"], r["title"], r["ext"]) for r in data["rows"]], [("6-1", "梱包", "")])
        _, state = self.call("GET", "/api/state")
        self.assertEqual(state["list_target"], "folders")
        status, data = self.call("GET", "/api/filelist?target=files&folder=" + self.q(self.base / "A班"))
        self.assertEqual([r["file_name"] for r in data["rows"]], ["6-1_手順.pdf"])

    def test_filelist_bad_target(self):
        status, data = self.call("GET", "/api/filelist?target=both&folder=" + self.q(self.base))
        self.assertEqual((status, data["error"]["code"]), (422, "bad_target"))

    def test_filelist_missing_folder(self):
        status, data = self.call("GET", "/api/filelist?folder=" + self.q(self.base / "B班"))
        self.assertEqual(status, 422)
        self.assertEqual(data["error"]["message"], "指定のフォルダは存在しません。")
        self.assertEqual(data["folder"], str(self.base / "B班"))

    def test_filelist_relative_and_empty(self):
        status, data = self.call("GET", "/api/filelist?folder=A%E7%8F%AD")
        self.assertEqual((status, data["error"]["code"]), (422, "folder_relative"))
        status, data = self.call("GET", "/api/filelist?folder=")
        self.assertEqual((status, data["error"]["code"]), (422, "folder_empty"))

    # --- リネーム ------------------------------------------------------
    def test_rename_preview_then_run(self):
        (self.base / "Ａ.txt").write_text("x", encoding="utf-8")
        req = {"folder": f'"{self.base}"', "rename_folders": False}
        status, plan = self.call("POST", "/api/rename/preview", req)
        self.assertEqual(status, 200)
        self.assertTrue((self.base / "Ａ.txt").exists())
        status, result = self.call("POST", "/api/rename/run", {**req, "plan_id": plan["plan_id"]})
        self.assertEqual(status, 200)
        self.assertEqual(result["counts"], {"total": 1, "ok": 1, "fail": 0})
        self.assertTrue((self.base / "A.txt").exists())

    def test_rename_changed_is_409(self):
        (self.base / "Ａ.txt").write_text("x", encoding="utf-8")
        req = {"folder": str(self.base), "rename_folders": False}
        _, plan = self.call("POST", "/api/rename/preview", req)
        (self.base / "Ｂ.txt").write_text("x", encoding="utf-8")
        status, data = self.call("POST", "/api/rename/run", {**req, "plan_id": plan["plan_id"]})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"]["code"], "plan_changed")
        self.assertEqual(len(data["plan"]["items"]), 2)

    def test_rename_input_checks(self):
        self.assertEqual(self.call("POST", "/api/rename/preview",
                                   {"folder": " ", "rename_folders": False})[0], 422)
        self.assertEqual(self.call("POST", "/api/rename/preview",
                                   {"folder": str(self.base / "無い"), "rename_folders": False})[0], 422)
        self.assertEqual(self.call("POST", "/api/rename/preview",
                                   {"folder": "ThisWorkbook.Path", "rename_folders": False})[0], 422)
        self.assertEqual(self.call("POST", "/api/rename/preview",
                                   {"folder": str(self.base), "rename_folders": "yes"})[0], 400)
        self.assertEqual(self.call("POST", "/api/rename/run",
                                   {"folder": str(self.base), "rename_folders": False,
                                    "plan_id": ""})[0], 400)

    def test_removed_endpoints(self):
        # VER1.2.0 で基準フォルダの設定とフォルダ参照をなくした
        self.assertEqual(self.call("POST", "/api/settings", {"base_dir": ""})[0], 404)
        self.assertEqual(self.call("GET", "/api/fs/list?path=/")[0], 404)

    # --- 停止 ----------------------------------------------------------
    def test_shutdown_refused_while_busy(self):
        self.app.state.begin("全角→半角リネーム")
        status, data = self.call("POST", "/api/shutdown", {})
        self.assertEqual(status, 409)
        self.assertEqual(data["running"], ["全角→半角リネーム"])
        self.app.state.end("全角→半角リネーム")
        status, data = self.call("POST", "/api/shutdown", {})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("POST", "/api/shutdown", {}, token="")[0], 403)

    def test_bad_json(self):
        resp = self.app.handle(Request.build("POST", "/api/rename/preview",
                                             {"Host": HOST, "X-Tool-Token": "T"}, b"{oops"))
        self.assertEqual(resp.status, 400)


if __name__ == "__main__":
    unittest.main()
