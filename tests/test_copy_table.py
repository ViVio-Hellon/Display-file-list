"""一覧のコピー(Excel に貼ると列に分かれる)。中身を作る JS を node で動かして確かめる。"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node が無い")
class CopyTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, str(ROOT / "tests" / "js" / "copytable_check.mjs")],
                             capture_output=True, text=True, timeout=30, check=True)
        cls.data = json.loads(out.stdout)

    def test_tsv_columns(self):
        lines = self.data["tsv"].split("\r\n")
        self.assertEqual(lines[0], "文書番号\t名称\t更新日時\t拡張子")
        self.assertEqual(lines[1], "6-1\t梱包手順書\t2026/10/15 14:56\txlsx")
        self.assertEqual(lines[3], "\t手順書一覧\t2026/10/15 14:56\tdocx")       # 空の欄も列を保つ
        self.assertEqual(lines[4], "x\tタブ と改行 が入った名前\t\t")            # 区切り文字は空白に
        self.assertTrue(all(len(line.split("\t")) == 4 for line in lines if line))
        self.assertEqual(self.data["tsvNoHeader"].split("\r\n")[0], lines[1])

    def test_html_keeps_text_as_text_in_excel(self):
        html = self.data["html"]
        # 6-1 が日付・007 が数字に化けないよう、文字列の印
        self.assertIn('<td style="mso-number-format:\'\\@\'">6-1</td>', html)
        self.assertIn('<td style="mso-number-format:\'\\@\'">007-1</td>', html)
        self.assertIn("A&amp;B &lt;改&gt;", html)                                 # 名前はエスケープ
        self.assertEqual(html.count("<tr>"), 5)                                   # 見出し + 4行
        self.assertIn("<th>文書番号</th><th>名称</th><th>更新日時</th><th>拡張子</th>", html)

    def test_folder_list_has_no_extension_column(self):
        """フォルダの一覧(VER1.7.0)は 文書番号 / 名称 / 更新日時 の3列。"""
        lines = self.data["folderTsv"].split("\r\n")
        self.assertEqual(lines[0], "文書番号\t名称\t更新日時")
        self.assertEqual(lines[1], "6-1\t梱包手順書\t2026/10/15 14:56")
        self.assertTrue(all(len(line.split("\t")) == 3 for line in lines if line))
        html = self.data["folderHtml"]
        self.assertIn("<th>文書番号</th><th>名称</th><th>更新日時</th></tr>", html)
        self.assertNotIn("拡張子", html)
        self.assertEqual(html.count("<td"), 3 * 4)
        self.assertIn('<td style="mso-number-format:\'\\@\'">6-1</td>', html)


if __name__ == "__main__":
    unittest.main()
