"""一覧の印刷の字・罫線は、紙の端から 5mm 以上内側に置く(VER1.6.1)。

プリンターは紙の縁 約 4mm に刷れない。ブラウザの印刷プレビューは紙の端まで描くので、
画面で収まって見えても紙でははみ出す(「余白 5mm 内側にしないとはみ出す」2026-10-17)。

距離は `@page` の余白ではなく紙の中(`.print-sheet` の padding)で取る。
`@page` の余白は印刷ダイアログの「余白: なし」で 0 に上書きされるため
(coil-packing-tools の梱包明細・資材計算・ペナラベルと同じ決まり)。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app" / "static" / "css" / "app.css"
SAFE_MM = 5.0


def _css() -> str:
    text = CSS.read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)       # 説明の中の例は数えない


def _print_block(css: str) -> str:
    start = css.index("@media print{")
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        depth += {"{": 1, "}": -1}.get(css[j], 0)
        if depth == 0:
            return css[i + 1:j]
    raise AssertionError("@media print が閉じていない")


def _rule(block: str, selector: str) -> str:
    m = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", block)
    assert m, selector
    return m.group(1)


class PrintMarginTest(unittest.TestCase):
    def test_every_page_rule_has_zero_margin(self):
        """`@page` の余白に頼らない(ダイアログの「なし」で消える)。1つでも残すと打ち消し合う。"""
        rules = re.findall(r"@page\s*\{([^}]*)\}", _css())
        self.assertEqual(len(rules), 1, rules)
        self.assertRegex(rules[0], r"size\s*:\s*A4 portrait")
        self.assertRegex(rules[0], r"margin\s*:\s*0\s*(;|$)")

    def test_distance_is_taken_inside_the_paper(self):
        body = _rule(_print_block(_css()), ".print-sheet")
        m = re.search(r"(?:^|[;\s])padding\s*:\s*([\d.]+)mm\s*(;|$)", body)
        self.assertTrue(m, body)
        self.assertGreaterEqual(float(m.group(1)), SAFE_MM)
        # 2 枚目以降の紙の上端・下端も同じだけ空ける
        self.assertIn("box-decoration-break:clone", body)
        self.assertIn("-webkit-box-decoration-break:clone", body)

    def test_colors_do_not_depend_on_dialog_settings(self):
        """「背景のグラフィック」が無いと見出しの網掛けが消え、薄い字が濃く刷り直される。"""
        body = _rule(_print_block(_css()), ".print-sheet")
        self.assertIn("print-color-adjust:exact", body)

    def test_nothing_is_placed_in_the_page_margin(self):
        """余白 0 なので、余白に置く物(ページ番号など)は刷れない場所に来る。置かない。"""
        self.assertNotRegex(_css(), r"@(top|bottom)-(left|center|right)")


if __name__ == "__main__":
    unittest.main()
