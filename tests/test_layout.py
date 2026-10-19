"""画面の割合(VER1.6.2)。結果:操作 = 6:4、操作は 360px より狭くしない。"""
import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "app.css"


class LayoutTest(unittest.TestCase):
    def test_result_and_panel_are_six_to_four(self):
        """指示: 8:2 ぐらいを 6:4 に。フォルダのパスの欄を長く(操作の幅に合わせて伸びる)。"""
        m = re.search(r"\.work\{[^}]*grid-template-columns:([^;}]*)", CSS.read_text(encoding="utf-8"))
        self.assertTrue(m)
        self.assertEqual(m.group(1).strip(), "minmax(0,3fr) minmax(360px,2fr)")


if __name__ == "__main__":
    unittest.main()
