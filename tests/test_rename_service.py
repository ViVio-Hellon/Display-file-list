import os
import tempfile
import unittest
from pathlib import Path

from app.services import rename_service as rs

FOLD = str.casefold        # Windows と同じく大文字小文字を区別しない想定で試す


class RenameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def files(self, *names):
        for n in names:
            (self.dir / n).write_text(n, encoding="utf-8")

    def listing(self):
        return sorted(p.name for p in self.dir.iterdir())

    def by_old(self, plan):
        return {i.old: i for i in plan.items}

    # --- 下見 ----------------------------------------------------------
    def test_plan_changes_nothing(self):
        self.files("６－４＿手順.pdf", "そのまま.pdf")
        before = self.listing()
        plan = rs.plan(self.dir, rename_folders=False, fold=FOLD)
        self.assertEqual(self.listing(), before)
        self.assertEqual([(i.old, i.new, i.status) for i in plan.items],
                         [("６－４＿手順.pdf", "6-4_手順.pdf", rs.STATUS_RENAME)])

    def test_numbered_when_taken(self):
        # VBA RenameFile: 同名があれば 基本名_1.拡張子、それも有れば _2
        self.files("Ａ.txt", "A.txt", "A_1.txt", "Ｂ")
        (self.dir / "B").write_text("", encoding="utf-8")
        items = self.by_old(rs.plan(self.dir, rename_folders=False, fold=FOLD))
        self.assertEqual(items["Ａ.txt"].new, "A_2.txt")
        self.assertEqual(items["Ａ.txt"].status, rs.STATUS_NUMBERED)
        self.assertEqual(items["Ｂ"].new, "B_1")          # 拡張子なし

    def test_case_insensitive_like_windows(self):
        self.files("ａ.txt", "A.txt")
        item = rs.plan(self.dir, rename_folders=False, fold=FOLD).items[0]
        self.assertEqual(item.new, "a_1.txt")

    def test_two_files_to_same_name_in_order(self):
        # 1件ずつ処理するので、前の件で付けた名前が後の件の「既にある」に入る
        self.files("Ａ．txt", "Ａ.txt")
        plan = rs.plan(self.dir, rename_folders=False, fold=FOLD)
        news = [i.new for i in plan.items]
        self.assertEqual(sorted(news), ["A.txt", "A_1.txt"])

    def test_invalid_chars_fail_before_trying(self):
        self.files("Ａ／Ｂ.txt", "ａ：ｂ.txt", "ｘ？.txt")
        items = rs.plan(self.dir, rename_folders=False, fold=FOLD).items
        self.assertTrue(all(i.status == rs.STATUS_FAIL for i in items))
        self.assertIn("/", self.by_old(rs.plan(self.dir, rename_folders=False, fold=FOLD))["Ａ／Ｂ.txt"].reason)

    def test_trailing_and_reserved_fail(self):
        self.files("ａｂ．", "ＣＯＮ.txt")
        items = self.by_old(rs.plan(self.dir, rename_folders=False, fold=FOLD))
        self.assertEqual(items["ａｂ．"].reason, rs.REASON_TRAILING)
        self.assertIn("CON", items["ＣＯＮ.txt"].reason)

    def test_folders_only_when_checked(self):
        (self.dir / "Ｄｏｃｓ").mkdir()
        self.assertEqual(rs.plan(self.dir, rename_folders=False, fold=FOLD).items, [])
        items = rs.plan(self.dir, rename_folders=True, fold=FOLD).items
        self.assertEqual([(i.kind, i.new) for i in items], [(rs.KIND_FOLDER, "Docs")])

    def test_folder_exists_fails_without_number(self):
        (self.dir / "Ｄｏｃｓ").mkdir()
        (self.dir / "docs").mkdir()
        item = rs.plan(self.dir, rename_folders=True, fold=FOLD).items[0]
        self.assertEqual((item.status, item.reason), (rs.STATUS_FAIL, rs.REASON_FOLDER_EXISTS))

    def test_file_vs_folder_name_clash(self):
        (self.dir / "A.txt").mkdir()
        self.files("Ａ.txt")
        item = rs.plan(self.dir, rename_folders=False, fold=FOLD).items[0]
        self.assertEqual(item.status, rs.STATUS_FAIL)

    def test_subfolder_contents_untouched(self):
        (self.dir / "sub").mkdir()
        (self.dir / "sub" / "Ａ.txt").write_text("", encoding="utf-8")
        self.assertEqual(rs.plan(self.dir, rename_folders=True, fold=FOLD).items, [])

    def test_missing_folder(self):
        with self.assertRaises(rs.FolderNotFound):
            rs.plan(self.dir / "無い", rename_folders=False)

    # --- 実行 ----------------------------------------------------------
    def test_run_renames(self):
        self.files("６－４＿手順.pdf", "Ａ.txt", "A.txt", "Ｘ／.txt")
        (self.dir / "Ｄｏｃｓ").mkdir()
        plan = rs.plan(self.dir, rename_folders=True, fold=FOLD)
        logs = []
        result = rs.run(self.dir, rename_folders=True, plan_id=plan.plan_id, fold=FOLD, log=logs.append)
        self.assertEqual(self.listing(), sorted(["6-4_手順.pdf", "A.txt", "A_1.txt", "Ｘ／.txt", "Docs"]))
        self.assertEqual((self.dir / "A_1.txt").read_text(encoding="utf-8"), "Ａ.txt")   # 中身はそのまま
        self.assertEqual(result.counts(), {"total": 4, "ok": 3, "fail": 1})
        self.assertEqual(len(logs), 3)

    def test_run_refuses_when_changed(self):
        self.files("Ａ.txt")
        plan = rs.plan(self.dir, rename_folders=False, fold=FOLD)
        self.files("Ｂ.txt")                          # 下見のあとで別のPCが置いた
        with self.assertRaises(rs.PlanChanged) as ctx:
            rs.run(self.dir, rename_folders=False, plan_id=plan.plan_id, fold=FOLD)
        self.assertEqual(self.listing(), ["Ａ.txt", "Ｂ.txt"])           # 何も変えない
        self.assertEqual(len(ctx.exception.plan.items), 2)

    def test_run_never_overwrites(self):
        self.files("Ａ.txt")
        plan = rs.plan(self.dir, rename_folders=False, fold=FOLD)
        original_lexists = os.path.lexists

        def lexists(p):
            # 計画を作り直した直後、変える直前に別のPCが同じ名前を置いた
            Path(p).write_text("先に置かれた", encoding="utf-8")
            return original_lexists(p)
        os.path.lexists = lexists
        try:
            result = rs.run(self.dir, rename_folders=False, plan_id=plan.plan_id, fold=FOLD)
        finally:
            os.path.lexists = original_lexists
        self.assertFalse(result.outcomes[0].ok)
        self.assertEqual(result.outcomes[0].reason, rs.REASON_APPEARED)
        self.assertEqual((self.dir / "A.txt").read_text(encoding="utf-8"), "先に置かれた")
        self.assertTrue((self.dir / "Ａ.txt").exists())

    # --- 入力 ----------------------------------------------------------
    def test_resolve_folder(self):
        base = Path("/base")
        self.assertIsNone(rs.resolve_folder("  ", base))
        self.assertEqual(rs.resolve_folder(" ThisWorkbook.Path ", base), base)
        self.assertEqual(rs.resolve_folder("A班", base), base / "A班")
        self.assertEqual(rs.resolve_folder(str(self.dir), base), self.dir)

    def test_split_base_ext_like_fso(self):
        self.assertEqual(rs.split_base_ext("a.b.txt"), ("a.b", "txt"))
        self.assertEqual(rs.split_base_ext("README"), ("README", ""))
        self.assertEqual(rs.split_base_ext(".gitignore"), ("", "gitignore"))


if __name__ == "__main__":
    unittest.main()
