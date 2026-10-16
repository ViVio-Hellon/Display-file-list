"""VBA の組み込み関数のうち、結果を一致させる必要があるものの再現

`Val` だけを置く。一覧の並べ替えキー(文書番号の先頭の数字)を決めているので、
Python の `float()` や `int()` に置き換えると並び順が変わる。

VBA `Val` の読み方(Microsoft の説明と同じ):

- 空白・タブ・改行は**どこにあっても取り除いてから**読む(`" 1 2"` → 12)
- `&H`(16進)・`&O`(8進)の接頭辞を読む。4桁以内は Integer として符号付きに
  なる(`&HFFFF` → -1)、それを超えると Long として符号付き
- 符号・小数点(`.` 固定)・指数(`E` / `D`)を読む(`1e3` → 1000、`1.5` → 1.5)
- 読めない文字が来たところで止める(`6a` → 6)。1文字も読めなければ 0

【決まったこと】全角数字(`１２`)は数字として読まない。`１２-3` は文字列(2026-10-16 の回答。
移植計画 Q12)。並べ替えでは番号の無いものと同じく後ろへ回る。半角の 0-9 だけを数字とする。
"""
from __future__ import annotations

import re
from typing import Union

Number = Union[int, float]

# VBA の説明にある3つ。全角空白は含めない(確かめていないため)
_STRIP = re.compile(r"[ \t\n]")
_RADIX = re.compile(r"&([HhOo])")
_DECIMAL = re.compile(r"[+-]?([0-9]*)(\.[0-9]*)?([EeDd][+-]?[0-9]+)?")


def val(text: str) -> Number:
    """VBA `Val(text)`。"""
    s = _STRIP.sub("", text or "")
    radix = _RADIX.match(s)
    if radix:
        hexa = radix.group(1) in "Hh"
        digits = re.match(r"[0-9A-Fa-f]*" if hexa else r"[0-7]*", s[2:]).group(0)
        if not digits:
            return 0
        value = int(digits, 16 if hexa else 8)
        if value <= 0xFFFF:                    # Integer
            return value - 0x10000 if value >= 0x8000 else value
        value &= 0xFFFFFFFF                    # Long
        return value - 0x100000000 if value >= 0x80000000 else value

    m = _DECIMAL.match(s)
    mantissa = (m.group(1) or "") + (m.group(2) or "")
    if not re.search(r"[0-9]", mantissa):
        return 0
    number = float(m.group(0).replace("D", "E").replace("d", "e"))
    return int(number) if number.is_integer() and abs(number) < 1e15 else number
