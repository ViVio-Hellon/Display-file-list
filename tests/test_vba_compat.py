import unittest

from app.services.vba_compat import val


class ValTest(unittest.TestCase):
    """VBA `Val` の説明どおりか。"""

    def test_plain(self):
        self.assertEqual(val("6"), 6)
        self.assertEqual(val("12"), 12)
        self.assertEqual(val("007"), 7)
        self.assertEqual(val("1.5"), 1.5)
        self.assertEqual(val(".5"), 0.5)
        self.assertEqual(val("5."), 5)

    def test_stops_at_unknown(self):
        self.assertEqual(val("6a"), 6)
        self.assertEqual(val("1,000"), 1)
        self.assertEqual(val("abc"), 0)
        self.assertEqual(val(""), 0)
        self.assertEqual(val("~$6"), 0)
        self.assertEqual(val("$6"), 0)

    def test_strips_blanks_everywhere(self):
        self.assertEqual(val(" 1 2"), 12)
        self.assertEqual(val("1\t2\n3"), 123)

    def test_sign_and_exponent(self):
        self.assertEqual(val("+5"), 5)
        self.assertEqual(val("-5"), -5)
        self.assertEqual(val("1e3"), 1000)
        self.assertEqual(val("1E+2"), 100)
        self.assertEqual(val("1d2"), 100)
        self.assertEqual(val("1e"), 1)          # 指数が読めなければそこまで
        self.assertEqual(val("+"), 0)
        self.assertEqual(val("."), 0)

    def test_radix(self):
        self.assertEqual(val("&H10"), 16)
        self.assertEqual(val("&h1F"), 31)
        self.assertEqual(val("&O17"), 15)
        self.assertEqual(val("&HFFFF"), -1)      # Integer
        self.assertEqual(val("&H7FFF"), 32767)
        self.assertEqual(val("&H10000"), 65536)  # Long
        self.assertEqual(val("&HFFFFFFFF"), -1)
        self.assertEqual(val("&H"), 0)
        self.assertEqual(val("&Hxyz"), 0)
        self.assertEqual(val("&O8"), 0)

    def test_fullwidth_digits_are_not_digits(self):
        # 移植計画 Q12: 全角数字は文字列。数字として扱わない(2026-10-16 決定)
        self.assertEqual(val("１２"), 0)


if __name__ == "__main__":
    unittest.main()
