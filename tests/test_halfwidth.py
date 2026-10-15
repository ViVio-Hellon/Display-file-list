import re
import unittest
from pathlib import Path

from app.services import halfwidth

VBA_SOURCE = Path(__file__).resolve().parent.parent / "vba" / "原本_ファイル名一覧取得.txt"


def vba_table():
    """VBA `ConvertZenkakuToHankaku` の Select Case をソースから読んで、同じ表を作る。"""
    text = VBA_SOURCE.read_text(encoding="utf-8")
    body = text[text.index("Private Function ConvertZenkakuToHankaku"):]
    body = body[:body.index("End Function")]
    table = {}
    for lo, hi, base in re.findall(r"Case (\d+) To (\d+).*\n.*asciiCode - \d+ \+ (\d+)", body):
        for code in range(int(lo), int(hi) + 1):
            table[code] = code - int(lo) + int(base)
    table[12288] = 0x20
    for code, ch in re.findall(r'Case (\d+): result = result & "(.)"', body):
        table[int(code)] = ord(ch)
    for code in re.findall(r"Case (\d+): result = result & Chr\(34\)", body):
        table[int(code)] = 34
    return table


class HalfwidthTest(unittest.TestCase):
    def test_same_table_as_vba_source(self):
        self.assertEqual(halfwidth.TABLE, vba_table())
        self.assertEqual(len(halfwidth.TABLE), 95)

    def test_every_char(self):
        for code in range(0xFF01, 0xFF5F):
            self.assertEqual(halfwidth.to_halfwidth(chr(code)), chr(code - 0xFEE0))
        self.assertEqual(halfwidth.to_halfwidth("　"), " ")

    def test_untouched(self):
        for text in ("カタカナ", "ひらがな", "漢字", "〜", "−", "￥", "ｶﾅ", "abcXYZ"):
            self.assertEqual(halfwidth.to_halfwidth(text), text)

    def test_case_kept(self):
        self.assertEqual(halfwidth.to_halfwidth("ＧＧＬ9アｂｃｒ.txt"), "GGL9アbcr.txt")
        self.assertEqual(halfwidth.to_halfwidth("＿  ＿～.txt"), "_  _~.txt")

    def test_changed_chars(self):
        self.assertEqual(halfwidth.changed_chars("６－４＿６"), ["６", "－", "４", "＿"])


if __name__ == "__main__":
    unittest.main()
