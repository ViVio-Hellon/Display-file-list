import tempfile
import unittest
from pathlib import Path

from app.services import folder_input as fi


class CleanTest(unittest.TestCase):
    def test_quotes_from_copy_as_path(self):
        # エクスプローラーの「パスのコピー」は " で囲む(VER1.1.0 で「見つからない」になった原因)
        self.assertEqual(fi.clean('"C:\\Users\\a\\A班"'), "C:\\Users\\a\\A班")
        self.assertEqual(fi.clean('  "C:\\x"  \n'), "C:\\x")
        self.assertEqual(fi.clean("“C:\\x”"), "C:\\x")
        self.assertEqual(fi.clean("'\\\\srv\\share\\A班'"), "\\\\srv\\share\\A班")
        self.assertEqual(fi.clean('"'), "")

    def test_fullwidth_space_and_newline(self):
        self.assertEqual(fi.clean("\u3000C:\\x\u3000\r\n"), "C:\\x")

    def test_file_url(self):
        self.assertEqual(fi.clean("file:///C:/Users/a/A%E7%8F%AD"), "C:/Users/a/A班")
        self.assertEqual(fi.clean("file://srv/share/A%E7%8F%AD"), "\\\\srv\\share\\A班")

    def test_plain_kept(self):
        self.assertEqual(fi.clean("C:\\Users\\a b\\A班"), "C:\\Users\\a b\\A班")


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "A班"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def error(self, text):
        with self.assertRaises(fi.FolderInputError) as ctx:
            fi.parse(text)
        return ctx.exception

    def test_ok_with_quotes(self):
        self.assertEqual(fi.parse(f'"{self.dir}"'), self.dir)

    def test_empty(self):
        self.assertEqual(self.error("  ").code, "folder_empty")
        self.assertEqual(self.error('""').code, "folder_empty")

    def test_relative_refused(self):
        e = self.error("A班")
        self.assertEqual((e.code, e.folder), ("folder_relative", "A班"))

    def test_missing_reports_path_read(self):
        e = self.error(f'"{self.dir / "無い"}"')
        self.assertEqual(e.code, "folder_missing")
        self.assertEqual(e.message, "指定のフォルダは存在しません。")
        self.assertEqual(e.folder, str(self.dir / "無い"))

    def test_file_refused(self):
        f = self.dir / "a.txt"
        f.write_text("x", encoding="utf-8")
        self.assertEqual(self.error(str(f)).code, "folder_is_file")


if __name__ == "__main__":
    unittest.main()
