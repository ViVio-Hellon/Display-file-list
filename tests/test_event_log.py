"""ログ(出来事の記録・なぜなぜ・出力先)。日報管理ツールの tests/test_event_log.py に倣う。"""
import json
import logging
import random
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from app.application import App
from app.core import event_log, event_rules as rule, logging_setup
from app.repositories import settings_repository
from app.web import Request

PORT = 18754
HOST = f"127.0.0.1:{PORT}"
AT = datetime(2026, 10, 16, 9, 12, 30)


class RulesTest(unittest.TestCase):
    """純粋な決まり(ファイルも時計も触らない)。"""

    def test_id_has_kind_date_and_unambiguous_tail(self):
        event_id = rule.new_id(rule.KIND_ERROR, AT, random.Random(1))
        self.assertRegex(event_id, r"^E1016-0912-[234679ACDEFGHJKMNPQRTUVWXYZ]{3}$")
        self.assertTrue(rule.new_id(rule.KIND_REFUSED, AT).startswith("R1016-0912-"))
        self.assertTrue(rule.new_id(rule.KIND_CLIENT, AT).startswith("C"))

    def test_input_is_flat_without_blanks_and_secrets(self):
        out = rule.summarize_input({"folder": "C:\\A班", "rename_folders": False, "empty": "  ",
                                    "token": "abc", "nested": {"password": "x", "n": 1}})
        self.assertEqual(out, {"folder": "C:\\A班", "rename_folders": "False",
                               "token": "***", "nested.password": "***", "nested.n": "1"})

    def test_too_many_items(self):
        out = rule.summarize_input({f"k{i}": i for i in range(50)})
        self.assertEqual(out["…"], "ほか 10 項目")

    def test_where_in_code_is_deepest_of_ours(self):
        frames = [("/app/x/app/routes/rename.py", 10, "run"),
                  ("/app/x/app/services/rename_service.py", 42, "plan"),
                  ("/usr/lib/python3/os.py", 5, "rename")]
        self.assertEqual(rule.where_in_code(frames, ["/app/x"]),
                         "app/services/rename_service.py:42 (plan)")

    def test_labels(self):
        self.assertEqual(rule.label_of("GET", "/api/filelist"), "ファイル名取得")
        self.assertEqual(rule.label_of("POST", "/api/rename/run"), "ファイル名変換: この内容で直す")
        self.assertEqual(rule.label_of("GET", "/"), "画面を開いた")
        self.assertEqual(rule.label_of("GET", "/logs"), "ログを開いた")

    def test_what_to_record(self):
        self.assertTrue(rule.should_record("GET", "/api/filelist", 200))      # 業務の操作
        self.assertTrue(rule.should_record("POST", "/api/rename/preview", 200))
        self.assertTrue(rule.should_record("GET", "/", 200))
        self.assertTrue(rule.should_record("GET", "/api/state", 403))         # 断りは全部
        self.assertFalse(rule.should_record("POST", "/api/alive", 200))       # 心拍
        self.assertFalse(rule.should_record("GET", "/api/state", 200))        # 読むだけ
        self.assertFalse(rule.should_record("GET", "/static/js/app.js", 200))
        self.assertFalse(rule.should_record("GET", "/api/log/events", 200))   # ログの面そのもの
        self.assertTrue(rule.should_record("POST", "/api/log/settings", 200)) # 出力先の変更は残す
        self.assertFalse(rule.should_record("GET", "/favicon.ico", 404))

    def test_timeline_same_tab_30_before_5_after(self):
        def ev(minutes, tab="t1", terminal="PC1", id_=None):
            return rule.make(rule.KIND_OP, at=AT + timedelta(minutes=minutes),
                             id=id_ or f"O-{minutes}-{tab}", tab=tab, terminal=terminal)
        target = ev(0, id_="E-target")
        records = [ev(-40), ev(-20), ev(-10, tab="t2"), ev(-5, terminal="PC2"), target, ev(3), ev(9)]
        ids = [r["id"] for r in rule.timeline(records, target)]
        self.assertEqual(ids, ["O--20-t1", "E-target", "O-3-t1"])

    def test_select_by_scope_newest_first(self):
        recs = [rule.make(rule.KIND_OP, at=AT, id="O1"),
                rule.make(rule.KIND_ERROR, at=AT + timedelta(seconds=1), id="E1"),
                rule.make(rule.KIND_REFUSED, at=AT + timedelta(seconds=2), id="R1", message="見つかりません")]
        self.assertEqual([r["id"] for r in rule.select(recs)], ["E1"])
        self.assertEqual([r["id"] for r in rule.select(recs, scope="problems")], ["R1", "E1"])
        self.assertEqual([r["id"] for r in rule.select(recs, scope="all", text="見つかり")], ["R1"])

    def test_sheet_separates_record_and_human(self):
        target = rule.make(rule.KIND_ERROR, at=AT, id="E1", label="ファイル名取得",
                           message="思わぬエラーが起きました(エラー番号 E1)",
                           cause="KeyError: 'x'", where="app/x.py:3 (f)",
                           input={"folder": "C:\\A班"}, version="1.3.0")
        sheet = rule.sheet(target, [target])
        labels = [f["label"] for f in sheet["facts"]]
        self.assertIn("何をした", labels)
        self.assertEqual(sheet["state"][0], {"label": "フォルダ", "value": "C:\\A班"})
        self.assertIn("KeyError", sheet["hint"])
        self.assertEqual(sheet["analysis"]["whys"], [""] * 5)
        self.assertEqual(rule.headline(target), "KeyError: 'x'")    # 決まり文句なら例外を見出しに

    def test_analysis_is_five_whys(self):
        note = rule.clean_analysis({"whys": ["a", "b"], "status": "bogus", "measure": "m" * 500})
        self.assertEqual(len(note["whys"]), 5)
        self.assertEqual(note["status"], rule.STATUS_OPEN)
        self.assertEqual(len(note["measure"]), rule.NOTE_MAX)

    def test_csv_row_matches_header(self):
        rec = rule.make(rule.KIND_ERROR, at=AT, id="E1", input={"folder": "C:\\x"})
        self.assertEqual(len(rule.csv_row(rec)), len(rule.CSV_HEADER))
        self.assertEqual(len(rule.csv_row(rec, rule.clean_analysis({"whys": ["a"]}))), len(rule.CSV_HEADER))


class _Dir(unittest.TestCase):
    """出来事を一時フォルダへ閉じ込める。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        event_log.install(log_dir=self.dir)
        event_log.reset()

    def tearDown(self):
        event_log.flush()
        event_log._override["dir"] = None
        event_log.reset()
        settings_repository.save(settings_repository.KEY_LOG_DIR, "")
        self.tmp.cleanup()


class ServiceTest(_Dir):
    def test_per_terminal_per_day_file(self):
        rec = rule.make(rule.KIND_OP, at=AT, id="O1", terminal="PC 1")
        event_log.record(rec)
        event_log.flush()
        self.assertTrue((self.dir / "出来事_2026-10-16_PC_1.jsonl").exists())
        self.assertEqual([r["id"] for r in event_log.load(date(2026, 10, 16), date(2026, 10, 16))], ["O1"])

    def test_warnings_become_events_once_a_minute(self):
        log = logging.getLogger("app.test_events")
        for _ in range(3):
            log.warning("マスタが読めません")
        event_log.flush()
        recs = event_log.load(date.today(), date.today())
        warns = [r for r in recs if r["message"] == "マスタが読めません"]
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0]["kind"], rule.KIND_WARN)
        self.assertIn("test_event_log.py", warns[0]["where"])

    def test_records_with_event_id_not_doubled(self):
        logging.getLogger("app.test_events").error("x", extra={"event_id": "E1"})
        event_log.flush()
        self.assertEqual([r for r in event_log.load(date.today(), date.today()) if r["message"] == "x"], [])

    def test_purge_only_my_old_files(self):
        me = event_log.safe_name(event_log.terminal_name())
        old_mine = self.dir / f"出来事_2026-01-01_{me}.jsonl"
        old_other = self.dir / "出来事_2026-01-01_OTHER-PC.jsonl"
        new_mine = self.dir / f"出来事_2026-10-15_{me}.jsonl"
        for p in (old_mine, old_other, new_mine):
            p.write_text("", encoding="utf-8")
        self.assertEqual(event_log.purge(today=date(2026, 10, 16)), 1)
        self.assertFalse(old_mine.exists())
        self.assertTrue(old_other.exists() and new_mine.exists())

    def test_analysis_latest_wins_across_terminals(self):
        (self.dir / "なぜなぜ_A.jsonl").write_text(
            json.dumps({"id": "E1", "at": "2026-10-16T09:00:00", "status": "doing"}) + "\n", encoding="utf-8")
        (self.dir / "なぜなぜ_B.jsonl").write_text(
            json.dumps({"id": "E1", "at": "2026-10-16T10:00:00", "status": "done"}) + "\n", encoding="utf-8")
        self.assertEqual(event_log.analyses()["E1"]["status"], "done")

    def test_broken_lines_skipped(self):
        (self.dir / "出来事_2026-10-16_X.jsonl").write_text(
            '{"id": "O1", "kind": "op"}\n{"id": "O2", "ki\n', encoding="utf-8")
        self.assertEqual([r["id"] for r in event_log.load(date(2026, 10, 16), date(2026, 10, 16))], ["O1"])


class FallbackTest(unittest.TestCase):
    """出力先に書けなければ手元の logs へ書き、理由を言う。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        blocker = Path(self.tmp.name) / "file.txt"
        blocker.write_text("x", encoding="utf-8")
        event_log._override["dir"] = None
        event_log.reset()
        settings_repository.save(settings_repository.KEY_LOG_DIR, str(blocker / "logs"))

    def tearDown(self):
        settings_repository.save(settings_repository.KEY_LOG_DIR, "")
        event_log.reset()
        self.tmp.cleanup()

    def test_falls_back_to_local(self):
        rec = rule.make(rule.KIND_OP, at=datetime.now(), id="O-fallback", terminal="PCF")
        event_log.record(rec)
        event_log.flush()
        status = event_log.status()
        self.assertIn("に書けません", status["fallback"])
        self.assertEqual(status["writing_to"], str(event_log.default_dir()))
        self.assertTrue(any(p.name.endswith("_PCF.jsonl") for p in event_log.default_dir().glob("出来事_*")))


class CaptureTest(_Dir):
    """要求ごとの記録・予期しないエラーの番号。"""

    def setUp(self):
        super().setUp()
        self.folder = self.dir / "A班"
        self.folder.mkdir()
        self.app = App(port=PORT, token="T")
        self.app.state.ready = True

        def boom(req):
            raise KeyError("x")
        self.app.router.add("POST", "/api/boom", boom)
        self.app.router.add("GET", "/boom-page", boom)

    def call(self, method, path, body=None, headers=None):
        h = {"Host": HOST, "X-Tool-Token": "T", "X-Tab": "tab1", "X-Screen": "/"}
        h.update(headers or {})
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        resp = self.app.handle(Request.build(method, path, h, raw))
        is_json = resp.content_type.startswith("application/json")
        return resp.status, (json.loads(resp.body) if is_json else resp.body.decode("utf-8"))

    def events(self):
        event_log.flush()
        return event_log.load(date.today(), date.today())

    def test_unexpected_error_has_number_in_message_and_record(self):
        status, body = self.call("POST", "/api/boom", {"folder": "C:\\x", "password": "p"})
        self.assertEqual(status, 500)
        event_id = body["event_id"]
        self.assertRegex(event_id, r"^E\d{4}-\d{4}-\w{3}$")
        self.assertIn(event_id, body["error"]["message"])
        rec = next(r for r in self.events() if r["id"] == event_id)
        self.assertEqual(rec["cause"], "KeyError: 'x'")
        self.assertIn("tests/test_event_log.py", rec["where"])
        self.assertEqual(rec["input"]["password"], "***")
        self.assertEqual((rec["tab"], rec["folder"]), ("tab1", "C:\\x"))
        # 文字のログにも出すが、出来事は二重にしない
        self.assertEqual(sum(1 for r in self.events() if r["id"] == event_id), 1)

    def test_html_error_page_has_number(self):
        status, text = self.call("GET", "/boom-page")
        self.assertEqual(status, 500)
        self.assertRegex(text, r"エラー番号 <code>E\d{4}-\d{4}-\w{3}</code>")
        self.assertIn("/logs?id=E", text)

    def test_refusal_recorded_with_message(self):
        self.call("GET", "/api/filelist?folder=" + quote(str(self.dir / "無い")))
        rec = [r for r in self.events() if r["kind"] == rule.KIND_REFUSED][-1]
        self.assertEqual(rec["message"], "指定のフォルダは存在しません。")
        self.assertEqual(rec["label"], "ファイル名取得")
        self.assertEqual(rec["status"], 422)

    def test_operations_recorded_but_not_heartbeat(self):
        self.call("GET", "/api/filelist?folder=" + quote(str(self.folder)) + "&t=T")
        self.call("POST", "/api/alive", {})
        self.call("GET", "/api/state")
        recs = self.events()
        self.assertEqual([r["label"] for r in recs], ["ファイル名取得"])
        self.assertNotIn("t", recs[0]["input"])               # トークンは残さない
        self.assertEqual(recs[0]["folder"], str(self.folder))

    def test_rename_result_noted(self):
        (self.folder / "Ａ.txt").write_text("x", encoding="utf-8")
        _, plan = self.call("POST", "/api/rename/preview", {"folder": str(self.folder), "rename_folders": False})
        self.call("POST", "/api/rename/run", {"folder": str(self.folder), "rename_folders": False,
                                              "plan_id": plan["plan_id"]})
        notes = [r for r in self.events() if r["label"] == "ファイル名変換の結果"]
        self.assertEqual(len(notes), 1)
        self.assertIn("成功 1 件", notes[0]["message"])

    def test_sheet_and_timeline_and_analysis(self):
        self.call("GET", "/api/filelist?folder=" + quote(str(self.folder)))
        _, body = self.call("POST", "/api/boom", {})
        event_id = body["event_id"]
        status, data = self.call("GET", f"/api/log/event?id={event_id}")
        self.assertEqual(status, 200)
        steps = [s["text"] for s in data["sheet"]["steps"]]
        self.assertTrue(any("ファイル名取得" in s for s in steps))
        _, summary = self.call("GET", "/api/log/summary")
        before = summary["open_errors"]
        status, saved = self.call("POST", "/api/log/event/analysis",
                                  {"id": event_id, "whys": ["パスが違った"], "status": "done", "by": "山田"})
        self.assertEqual(status, 200)
        self.assertEqual(saved["sheet"]["analysis"]["whys"][0], "パスが違った")
        _, summary = self.call("GET", "/api/log/summary")
        self.assertEqual(summary["open_errors"], before - 1)
        _, listing = self.call("GET", "/api/log/events?scope=errors")
        row = next(r for r in listing["rows"] if r["id"] == event_id)
        self.assertEqual(row["status_label"], "対策済")

    def test_unknown_id_404(self):
        self.assertEqual(self.call("GET", "/api/log/event?id=E0101-0000-AAA")[0], 404)

    def test_csv_written_to_export_folder(self):
        self.call("POST", "/api/boom", {})
        status, body = self.call("POST", "/api/log/csv", {"scope": "errors"})
        self.assertEqual(status, 200)
        path = Path(body["path"])
        self.assertEqual(path.parent, self.dir / "書き出し")
        text = path.read_text(encoding="utf-8-sig")
        self.assertTrue(text.startswith("番号,日時,種類"))

    def test_client_error_numbered_and_rate_limited(self):
        from app.routes import logs as logs_route
        logs_route._client_window.update(start=0.0, count=0)
        status, body = self.call("POST", "/api/log/client",
                                 {"message": "TypeError: x is undefined", "where": "/static/js/app.js:1:2",
                                  "crumbs": ["09:00:00 押した: ファイル名取得 #btn-list"]})
        self.assertEqual(status, 200)
        self.assertTrue(body["id"].startswith("C"))
        rec = next(r for r in self.events() if r["id"] == body["id"])
        self.assertEqual(rec["crumbs"][0], "09:00:00 押した: ファイル名取得 #btn-list")
        for _ in range(logs_route.CLIENT_PER_MINUTE):
            _, last = self.call("POST", "/api/log/client", {"message": "y"})
        self.assertTrue(last.get("skipped"))


class LogDirSettingTest(unittest.TestCase):
    """ログの出力先を変えると、その場でそこへ書く(出来事も文字のログも)。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        event_log._override["dir"] = None
        event_log.reset()
        logging_setup.setup()
        self.app = App(port=PORT, token="T")
        self.app.state.ready = True

    def tearDown(self):
        self.call("POST", "/api/log/settings", {"log_dir": ""})
        event_log.flush()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        resp = self.app.handle(Request.build(method, path, {"Host": HOST, "X-Tool-Token": "T"}, raw))
        return resp.status, json.loads(resp.body)

    def test_change_moves_writing(self):
        shared = self.base / "共有" / "logs"
        status, body = self.call("POST", "/api/log/settings", {"log_dir": f'"{shared}"'})
        self.assertEqual(status, 200)
        self.assertEqual((body["dir"], body["setting"]), (str(shared), str(shared)))
        self.assertEqual(body["text_dir"], str(shared))
        logging.getLogger("app.test_events").info("文字のログの行")
        event_log.flush()
        names = [p.name for p in shared.iterdir()]
        self.assertTrue(any(re.match(r"出来事_\d{4}-\d{2}-\d{2}_.+\.jsonl", n) for n in names), names)
        self.assertTrue(any(re.match(r"app_.+\.log", n) for n in names), names)   # 端末名つき
        # この端末に戻す
        status, body = self.call("POST", "/api/log/settings", {"log_dir": ""})
        self.assertTrue(body["is_default"])

    def test_unwritable_or_relative_refused(self):
        blocker = self.base / "file.txt"
        blocker.write_text("x", encoding="utf-8")
        status, body = self.call("POST", "/api/log/settings", {"log_dir": str(blocker / "logs")})
        self.assertEqual((status, body["error"]["code"]), (422, "log_dir_unwritable"))
        status, body = self.call("POST", "/api/log/settings", {"log_dir": "logs"})
        self.assertEqual((status, body["error"]["code"]), (422, "folder_relative"))


if __name__ == "__main__":
    unittest.main()
