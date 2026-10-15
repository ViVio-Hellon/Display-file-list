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

    def test_group_folder(self):
        self.assertEqual(fls.group_folder(self.base, ""), self.base)
        self.assertEqual(fls.group_folder(self.base, "A"), self.base / "A班")
        self.assertEqual(fls.group_folder(self.base, "HIRU"), self.base / "日勤")
        with self.assertRaises(ValueError):
            fls.group_folder(self.base, "Z")

    def test_lists_files_only_with_modified(self):
        stamp = time.mktime((2026, 10, 1, 8, 30, 15, 0, 0, -1)) + 0.9
        self.touch("A班/6-1_手順.pdf", stamp)
        self.touch("A班/.hidden")
        (self.base / "A班" / "サブ").mkdir()
        self.touch("A班/サブ/9-9_中.pdf")                  # サブフォルダの中は見ない
        result = fls.list_folder(self.base, "A")
        names = [r.file_name for r in result.rows]
        self.assertEqual(sorted(names), [".hidden", "6-1_手順.pdf"])
        row = next(r for r in result.rows if r.file_name == "6-1_手順.pdf")
        self.assertEqual(row.modified, datetime(2026, 10, 1, 8, 30, 15))   # 秒の端数は切り捨て
        self.assertEqual(fls.format_modified(row.modified), "2026/10/1 8:30")

    def test_missing_folder(self):
        with self.assertRaises(fls.FolderMissing) as ctx:
            fls.list_folder(self.base, "B")
        self.assertEqual(ctx.exception.folder, str(self.base / "B班"))
        self.assertEqual(ctx.exception.message, "指定のフォルダは存在しません。")

    def test_to_dict_message_when_over_limit(self):
        for i in range(302):
            self.touch(f"{i}-1_x.pdf")
        data = fls.to_dict(fls.list_folder(self.base, ""))
        self.assertEqual(data["count"], 302)
        self.assertEqual(data["sorted_rows"], 300)
        self.assertIn("残りの 2 件は読んだ順", data["message"])
        self.assertEqual(set(data["rows"][0]), {"file_name", "doc_no", "title", "modified",
                                                "modified_iso", "ext", "note"})


if __name__ == "__main__":
    unittest.main()
