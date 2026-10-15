"""全角→半角 (VBA `ConvertZenkakuToHankaku` の移植)

VBA の Select Case は、次の 95 文字をそれぞれ1文字ずつ並べていた。

    U+FF01〜U+FF5E(！〜～ の 94 文字) → U+0021〜U+007E(! 〜 ~)
    U+3000(全角空白)                    → U+0020(半角空白)

どの文字も「全角の位置 − 0xFEE0 = 半角の位置」なので、表で持つ。
python-web-tools の `lot_browse_session._HALF` と同じ表。

**変えない文字**(VBA でも対象外): 全角カタカナ・ひらがな・漢字・「〜」(U+301C)・
「−」(U+2212)・「￥」(U+FFE5)・半角カナ。英字の大文字小文字も変えない。
"""
from __future__ import annotations

TABLE = {**{code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)}, 0x3000: 0x20}


def to_halfwidth(text: str) -> str:
    return (text or "").translate(TABLE)


def changed_chars(text: str) -> list:
    """変わる文字(重複なし、出てきた順)。画面で「何が変わるか」を示す。"""
    seen: list = []
    for ch in text or "":
        if ord(ch) in TABLE and ch not in seen:
            seen.append(ch)
    return seen
