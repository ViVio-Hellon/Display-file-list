"""API と守り。サーバを立てずに App.handle を直接呼ぶ。"""
import json
import tempfile
import unittest
from pathlib import Path

from app.application import App
from app.repositories import settings_repository
from app.web import Request

PORT = 18753
HOST = f"127.0.0.1:{PORT}"


class WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        settings_repository.save(settings_repository.KEY_BASE_DIR, str(self.base))
        self.stopped = []
        self.app = App(port=PORT, token="T", on_shutdown=lambda: self.stopped.append(True))
        self.app.state.ready = True

    def tearDown(self):
        settings_repository.save(settings_repository.KEY_BASE_DIR, "")
        self.tmp.cleanup()

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
        self.assertEqual(self.call("GET", "/print?group=", token="")[0], 403)
        self.assertEqual(self.call("GET", "/print?group=&t=T", token="")[0], 200)
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
        status, data = self.call("GET", "/api/filelist?group=A")
        self.assertEqual(status, 200)
        self.assertEqual(data["group_label"], "A班")
        self.assertEqual([(r["doc_no"], r["title"], r["ext"]) for r in data["rows"]],
                         [("6-1", "手順", "pdf")])

    def test_filelist_missing_folder(self):
        status, data = self.call("GET", "/api/filelist?group=B")
        self.assertEqual(status, 422)
        self.assertEqual(data["error"]["message"], "指定のフォルダは存在しません。")

    def test_filelist_bad_group(self):
        self.assertEqual(self.call("GET", "/api/filelist?group=Z")[0], 400)

    def test_print(self):
        (self.base / "1-1_あ.pdf").write_text("x", encoding="utf-8")
        status, body = self.call("GET", "/print?group=")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("<td>1-1</td><td>あ</td>", text)
        self.assertIn("A4 portrait", text)
        status, body = self.call("GET", "/print?group=C")
        self.assertEqual(status, 422)
        self.assertIn("印刷できません", body.decode("utf-8"))

    # --- リネーム ------------------------------------------------------
    def test_rename_preview_then_run(self):
        (self.base / "Ａ.txt").write_text("x", encoding="utf-8")
        req = {"folder": "ThisWorkbook.Path", "rename_folders": False}
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
                                   {"folder": "無いフォルダ", "rename_folders": False})[0], 422)
        self.assertEqual(self.call("POST", "/api/rename/preview",
                                   {"folder": str(self.base), "rename_folders": "yes"})[0], 400)
        self.assertEqual(self.call("POST", "/api/rename/run",
                                   {"folder": str(self.base), "rename_folders": False,
                                    "plan_id": ""})[0], 400)

    # --- 設定 ----------------------------------------------------------
    def test_settings(self):
        status, data = self.call("POST", "/api/settings", {"base_dir": "relative"})
        self.assertEqual(status, 422)
        status, data = self.call("POST", "/api/settings", {"base_dir": str(self.base / "無い")})
        self.assertEqual(status, 422)
        status, data = self.call("POST", "/api/settings", {"base_dir": str(self.base)})
        self.assertEqual((status, data["base_dir"], data["base_dir_ok"]), (200, str(self.base), True))
        status, data = self.call("POST", "/api/settings", {"base_dir": ""})
        self.assertTrue(data["base_dir_default"])

    def test_fs_list_returns_folder_names_only(self):
        (self.base / "A班").mkdir()
        (self.base / "secret.txt").write_text("x", encoding="utf-8")
        _, data = self.call("GET", "/api/fs/list?path=" + str(self.base))
        self.assertEqual([d["name"] for d in data["dirs"]], ["A班"])
        self.assertNotIn("secret", json.dumps(data))

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
        resp = self.app.handle(Request.build("POST", "/api/settings",
                                             {"Host": HOST, "X-Tool-Token": "T"}, b"{oops"))
        self.assertEqual(resp.status, 400)


if __name__ == "__main__":
    unittest.main()
