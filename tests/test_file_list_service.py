import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from app.services import file_list_service as fls

GOLDEN = json.loads((Path(__file__).parent / "golden" / "vba_cases.json").read_text(encoding="utf-8"))


def _fields(parsed):
    return {"key": parsed.sort_key, "doc_no": parsed.doc_no, "title": parsed.title, "ext": parsed.ext}


class GoldenCasesTest(unittest.TestCase):
    """VBA のコードから読んだ正解と突き合わせる。"""

    def test_fixed(self):
        for case in GOLDEN["cases"]:
            with self.subTest(name=case["name"]):
                expected = {k: case[k] for k in ("key", "doc_no", "title", "ext")}
                self.assertEqual(_fields(fls.parse_name(case["name"])), expected)

    def test_strict_vba(self):
        for case in GOLDEN["cases"]:
            with self.subTest(name=case["name"]):
                strict = case.get("strict")
                if strict == "error":
                    with self.assertRaises(fls.VbaWouldStop):
                        fls.parse_name(case["name"], strict_vba=True)
                elif strict == "blank":
                    parsed = fls.parse_name(case["name"], strict_vba=True)
                    self.assertTrue(parsed.blank_row)
                    self.assertEqual(_fields(parsed), {"key": None, "doc_no": "", "title": "", "ext": ""})
                else:
                    expected = {k: case[k] for k in ("key", "doc_no", "title", "ext")}
                    self.assertEqual(_fields(fls.parse_name(case["name"], strict_vba=True)), expected)

    def test_tail_empty_gets_note(self):
        self.assertEqual(fls.parse_name("abc_").note, fls.NOTE_TAIL_EMPTY)
        self.assertEqual(fls.parse_name("abc_.pdf").note, fls.NOTE_TAIL_EMPTY)
        self.assertEqual(fls.parse_name("6-1_手順.pdf").note, "")


T = datetime(2026, 10, 15, 9, 5, 7)


class SortTest(unittest.TestCase):
    def names(self, rows):
        return [r.file_name for r in rows]

    def test_numbers_first_blanks_keep_order(self):
        rows = fls.build_rows([(n, T) for n in [
            "手順書.pdf", "12-1_b.pdf", "abc_x.pdf", "6-4_a.pdf", "1.5-1_c.pdf", "README", "6-1_z.pdf"]])
        self.assertEqual(self.names(rows), [
            "1.5-1_c.pdf", "6-4_a.pdf", "6-1_z.pdf", "12-1_b.pdf",   # 同じ6は読んだ順
            "手順書.pdf", "abc_x.pdf", "README"])                     # 空欄は読んだ順

    def test_negative_key_sorts_first(self):
        rows = fls.build_rows([(n, T) for n in ["1-1_a.pdf", "&HFFFF-1_x.pdf"]])
        self.assertEqual(self.names(rows), ["&HFFFF-1_x.pdf", "1-1_a.pdf"])

    def test_two_underscores_now_sorted_by_number(self):
        rows = fls.build_rows([(n, T) for n in ["手順.pdf", "6-4_手順_改.pdf", "3-1_a.pdf"]])
        self.assertEqual(self.names(rows), ["3-1_a.pdf", "6-4_手順_改.pdf", "手順.pdf"])

    def test_strict_blank_rows_go_back(self):
        rows = fls.build_rows([(n, T) for n in ["6-4_手順_改.pdf", "3-1_a.pdf", "手順.pdf"]],
                              strict_vba=True)
        self.assertEqual(self.names(rows), ["3-1_a.pdf", "6-4_手順_改.pdf", "手順.pdf"])
        self.assertTrue(rows[1].parsed.blank_row)

    def test_only_first_300_rows_sorted(self):
        # VBA: Range("A1:E300").Sort。301 行目以降は読んだ順のまま
        entries = [(f"{1000 - i}-1_x{i}.pdf", T) for i in range(305)]
        rows = fls.build_rows(entries)
        head_keys = [r.parsed.sort_key for r in rows[:300]]
        self.assertEqual(head_keys, sorted(head_keys))
        self.assertEqual(head_keys[0], 1000 - 299)
        self.assertEqual(self.names(rows[300:]), [f"{1000 - i}-1_x{i}.pdf" for i in range(300, 305)])


class FolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, rel, mtime=None):
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_lists_files_only_with_modified(self):
        stamp = time.mktime((2026, 10, 1, 8, 30, 15, 0, 0, -1)) + 0.9
        self.touch("A班/6-1_手順.pdf", stamp)
        self.touch("A班/.hidden")
        (self.base / "A班" / "サブ").mkdir()
        self.touch("A班/サブ/9-9_中.pdf")                  # サブフォルダの中は見ない
        result = fls.list_folder(self.base / "A班")
        self.assertEqual(result.title, "A班")
        names = [r.file_name for r in result.rows]
        self.assertEqual(sorted(names), [".hidden", "6-1_手順.pdf"])
        row = next(r for r in result.rows if r.file_name == "6-1_手順.pdf")
        self.assertEqual(row.modified, datetime(2026, 10, 1, 8, 30, 15))   # 秒の端数は切り捨て
        self.assertEqual(fls.format_modified(row.modified), "2026/10/1 8:30")

    def test_to_dict_message_when_over_limit(self):
        for i in range(302):
            self.touch(f"{i}-1_x.pdf")
        data = fls.to_dict(fls.list_folder(self.base))
        self.assertEqual(data["count"], 302)
        self.assertEqual(data["sorted_rows"], 300)
        self.assertIn("残りの 2 件は読んだ順", data["message"])
        self.assertEqual(set(data["rows"][0]), {"file_name", "doc_no", "title", "modified",
                                                "modified_iso", "ext", "note"})


class FolderNameTest(unittest.TestCase):
    """フォルダの一覧(VER1.7.0)の名前の分け方。最初の `_` で分け、`.` では分けない。"""

    def p(self, name):
        x = fls.parse_folder_name(name)
        return (x.doc_no, x.title, x.ext, x.sort_key, bool(x.note))

    def test_split_at_first_underscore(self):
        self.assertEqual(self.p("6-1_梱包手順"), ("6-1", "梱包手順", "", 6, False))
        self.assertEqual(self.p("6-4_手順_改"), ("6-4", "手順_改", "", 6, False))
        self.assertEqual(self.p("20260123_梱包班休憩所共有PC"), ("20260123", "梱包班休憩所共有PC", "", 20260123, False))

    def test_dots_are_part_of_the_name(self):
        # ファイルなら「99」と「生産管理課 土曜日出勤者」に分かれてしまう
        self.assertEqual(self.p("99.生産管理課　土曜日出勤者"), ("", "99.生産管理課　土曜日出勤者", "", None, False))
        self.assertEqual(self.p("12-1_手順書.v2"), ("12-1", "手順書.v2", "", 12, False))

    def test_without_underscore_and_odd_names(self):
        self.assertEqual(self.p("2026年2月6日 資材倉庫"), ("", "2026年2月6日 資材倉庫", "", None, False))
        self.assertEqual(self.p("abc_"), ("abc", "", "", None, True))       # 理由を添える
        self.assertEqual(self.p("_写真"), ("", "写真", "", None, False))
        self.assertEqual(self.p("１２-3_全角"), ("１２-3", "全角", "", None, False))  # Q12: 文字列

    def test_sorted_like_files(self):
        rows = fls.build_folder_rows([("b", datetime(2026, 1, 1)), ("10-1_x", datetime(2026, 1, 1)),
                                      ("2-1_y", datetime(2026, 1, 1)), ("a", datetime(2026, 1, 1))])
        self.assertEqual([r.file_name for r in rows], ["2-1_y", "10-1_x", "b", "a"])


class FolderListTest(unittest.TestCase):
    setUp, tearDown, touch = FolderTest.setUp, FolderTest.tearDown, FolderTest.touch

    def test_lists_direct_subfolders_only(self):
        stamp = time.mktime((2026, 10, 2, 9, 5, 0, 0, 0, -1))
        self.touch("A班/6-1_手順.pdf")                                     # ファイルは出さない
        self.touch("A班/3-1_写真/中/9-9_奥")                               # 孫は出さない
        (self.base / "A班" / "1-2_図面").mkdir()
        (self.base / "A班" / ".隠し").mkdir()
        os.utime(self.base / "A班" / "1-2_図面", (stamp, stamp))
        result = fls.list_folder(self.base / "A班", target=fls.TARGET_FOLDERS)
        self.assertEqual(result.target, "folders")
        self.assertEqual([r.file_name for r in result.rows], ["1-2_図面", "3-1_写真", ".隠し"])
        self.assertEqual(result.rows[0].modified, datetime(2026, 10, 2, 9, 5))
        data = fls.to_dict(result)
        self.assertEqual(data["target"], "folders")
        self.assertEqual([(r["doc_no"], r["title"], r["ext"]) for r in data["rows"]],
                         [("1-2", "図面", ""), ("3-1", "写真", ""), ("", ".隠し", "")])
        # ファイルの一覧はこれまでどおり(フォルダは出さない)
        files = fls.list_folder(self.base / "A班")
        self.assertEqual((files.target, [r.file_name for r in files.rows]), ("files", ["6-1_手順.pdf"]))

    def test_unknown_target(self):
        with self.assertRaises(ValueError):
            fls.list_folder(self.base, target="both")


if __name__ == "__main__":
    unittest.main()
