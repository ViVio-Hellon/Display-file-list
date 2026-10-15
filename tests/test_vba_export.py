"""ブックから書き出した VBA(vba/export)と、Python 側の決め打ちの値を突き合わせる。

VBA を正とする値は、ソースから読んで比べる。片方だけ直して食い違うのを防ぐ。
"""
import re
import unittest
from pathlib import Path

from app.services import file_list_service as fls

EXPORT = Path(__file__).resolve().parent.parent / "vba" / "export"


def read(name):
    return (EXPORT / name).read_bytes().decode("cp932").replace("\r\n", "\n")


def frx_texts():
    """UF.frx の中の UTF-16 の文字列(キャプションと初期値)。"""
    data = (EXPORT / "UF.frx").read_bytes()
    texts = set()
    for start in (0, 1):
        s = data[start:].decode("utf-16-le", errors="replace")
        texts.update(re.findall(r"[　-鿿＀-￯A-Za-z0-9 .→－]{2,}", s))
    return texts


class KirokuModuleTest(unittest.TestCase):
    """記録.bas(Get_FileName)。"""

    def setUp(self):
        self.src = read("記録.bas")

    def test_group_folders(self):
        found = dict(re.findall(r'Case UF\.OB(\w+):\s+strF = "(.+?)"', self.src))
        self.assertEqual(found, {k: label for k, label in fls.GROUPS})

    def test_sort_range(self):
        self.assertIn('WS.Range("A1:E' + str(fls.SORT_LIMIT_ROWS) + '").Sort', self.src)

    def test_missing_message(self):
        self.assertIn('MsgBox "' + fls.FolderMissing.message + '"', self.src)

    def test_no_option_explicit(self):
        # 移植計画 Q1: folder / file を宣言せずに使っているので、このモジュールには Option Explicit が無い
        self.assertNotIn("Option Explicit", self.src)

    def test_list_files_in_folder_is_not_in_workbook(self):
        # 移植計画 Q6: 最初に貼り付けてもらった中にあった ListFilesInFolder は、ブックのモジュールに無い
        for name in ("記録.bas", "全角文字を半角文字に.bas", "UF.frm"):
            self.assertNotIn("ListFilesInFolder", read(name))


class FormTest(unittest.TestCase):
    """UF.frx の表記と初期値。"""

    def setUp(self):
        self.texts = frx_texts()

    def test_captions(self):
        joined = "\n".join(self.texts)
        for caption in ("ファイル名取得", "ファイル名変換", "PDF作成", "全角を半角に",
                        "全角数字 → 半角数字", "ﾌｫﾙﾀﾞも対象"):
            self.assertIn(caption, joined)

    def test_rename_folder_default_is_workbook_path(self):
        # T2(直すフォルダ)の初期値。Forms 2.0 は ASCII だけの文字列を1バイトで持つ
        self.assertIn(b"ThisWorkbook.Path", (EXPORT / "UF.frx").read_bytes())

    def test_hiru_caption(self):
        self.assertEqual(fls.group_button_label("HIRU"), "昼(日勤)")
        self.assertEqual(fls.group_button_label("A"), "A班")


if __name__ == "__main__":
    unittest.main()
