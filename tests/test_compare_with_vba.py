import csv
import io
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import compare_with_vba as cmp


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "A班"
        self.dir.mkdir()
        self.stamp = time.mktime((2026, 10, 1, 8, 30, 15, 0, 0, -1))
        for name in ["手順書.pdf", "12-1_b.pdf", "6-4_手順_改.pdf", "6-1_a.pdf"]:
            p = self.dir / name
            p.write_text("x", encoding="utf-8")
            os.utime(p, (self.stamp, self.stamp))
        self.csv = Path(self.tmp.name) / "一覧_照合用.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def write_csv(self, rows):
        with self.csv.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["行", "文書番号", "名称", "更新日時", "拡張子"])
            for i, r in enumerate(rows, 1):
                w.writerow([i, *r])

    def run_main(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cmp.main(["--csv", str(self.csv), "--folder", str(self.dir)])
        return code, out.getvalue()

    def vba_rows(self):
        # VBA が作るはずの一覧(手で書いた)。_ が2つの名前は空行で、空欄キーの組の中で元の順
        d = "2026/10/01 08:30:15"
        order = [p.name for p in os.scandir(self.dir)]
        blank_group = [n for n in order if n in ("手順書.pdf", "6-4_手順_改.pdf")]
        rows = [["6-1", "a", d, "pdf"], ["12-1", "b", d, "pdf"]]
        for n in blank_group:
            rows.append(["", "手順書", d, "pdf"] if n == "手順書.pdf" else ["", "", "", ""])
        return rows

    def test_all_match(self):
        self.write_csv(self.vba_rows())
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("すべて一致", out)
        self.assertIn("6-4_手順_改.pdf → 文書番号「6-4」 名称「手順_改」", out)

    def test_difference_reported(self):
        rows = self.vba_rows()
        rows[0][1] = "45293"                     # Excel が日付にした、など
        self.write_csv(rows)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("1 行目 title", out)


if __name__ == "__main__":
    unittest.main()
