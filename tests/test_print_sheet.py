"""一覧の印刷(VER1.6.0)。紙面を作る JS を node で動かして確かめる。"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node が無い")
class PrintSheetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, str(ROOT / "tests" / "js" / "printsheet_check.mjs")],
                             capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
        cls.data = json.loads(out.stdout)

    def test_sheet_has_title_meta_and_rows_in_screen_order(self):
        html = self.data["normal"]
        self.assertIn("<h1>A班 の一覧</h1>", html)
        self.assertIn("フォルダ: C:\\現場\\A班 ／ 取得: 2026/10/16 9:12 ／ 3 件 ／ 印刷: 2026/10/16 9:30", html)
        self.assertIn("<thead><tr><th>文書番号</th><th>名称</th><th>更新日時</th><th>拡張子</th></tr></thead>", html)
        self.assertEqual(html.count("<tr>"), 4)                                    # 見出し + 3行
        self.assertLess(html.index(">6-1<"), html.index(">007-1<"))               # 画面の並びのまま
        self.assertIn("A&amp;B &lt;改&gt;", html)                                 # 名前はエスケープ
        self.assertNotIn("<改>", html)
        self.assertIn('<span class="p-note">abc_ … 名前が _ で終わっている</span>', html)
        self.assertNotIn("p-warn", html)

    def test_sheet_says_when_list_is_stale_or_partly_sorted(self):
        self.assertIn("ファイル名を直しました", self.data["stale"])
        self.assertIn('<p class="p-warn">301 件(先頭 300 件だけ並べ替えています。)</p>', self.data["over"])

    def test_no_list_prints_a_reason_instead_of_a_blank_page(self):
        for key in ("empty", "zero"):
            self.assertIn("印刷する一覧がありません", self.data[key])
            self.assertNotIn("<table>", self.data[key])

    def test_folder_list_sheet(self):
        """フォルダの一覧(VER1.7.0): 見出しは「◯◯ のフォルダ一覧」、拡張子の列は無い。"""
        html = self.data["folders"]
        self.assertIn("<h1>A班 のフォルダ一覧</h1>", html)
        self.assertIn("<thead><tr><th>文書番号</th><th>名称</th><th>更新日時</th></tr></thead>", html)
        self.assertIn('<tr><td>3-1</td><td>写真</td><td class="p-date">2026/10/2 9:05</td></tr>', html)
        self.assertEqual(html.count("<col "), 3)
        self.assertIn("<h1>A班 の一覧</h1>", self.data["normal"])             # ファイルはこれまでどおり


if __name__ == "__main__":
    unittest.main()
