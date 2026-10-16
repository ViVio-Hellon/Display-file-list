"""画面に打たれた・貼られたフォルダのパスを読む(一覧・変換で共通)

VER1.2.0 で班のボタンと基準フォルダをなくし、**フォルダはパスを打つだけ**にした。
パスの読み方はここ1か所で決める。

■ 受け付けるもの
- `C:\\…` `\\\\サーバ\\共有\\…` のような、はじめから書いたパス
- 前後の空白(全角の空白も)・改行は取る
- **前後の `"` は取る。** エクスプローラーの「パスのコピー」は `"C:\\…\\A班"` と
  `"` で囲んで写す。VER1.1.0 まではこれを取らず、相対パスと読んで
  「見つからない」と断っていた(現場で踏んだ)
- `file:///C:/…` の形(ブラウザのアドレス欄から写したとき)

■ 断るもの(理由と、読んだパスを返す)
- 空
- 相対パス(`A班` など)。どこから見た相対かが利用者に見えないため
- 見つからない / フォルダではなくファイル
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

QUOTES = "\"'“”„‟「」『』"

MESSAGE_EMPTY = "フォルダのパスを入れてください。"
MESSAGE_RELATIVE = ("フォルダは「C:\\…」や「\\\\サーバ\\…」のように、はじめから書いてください"
                    "(エクスプローラーのアドレス欄からコピーできます)。")
MESSAGE_MISSING = "指定のフォルダは存在しません。"      # VBA Get_FileName の MsgBox と同じ文言
MESSAGE_FILE = "ファイルではなく、フォルダのパスを入れてください。"


class FolderInputError(Exception):
    def __init__(self, code: str, message: str, folder: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.folder = folder


def clean(text: str) -> str:
    """打たれた文字からパスの文字だけを取り出す(フォルダがあるかはまだ見ない)。"""
    value = (text or "").strip()
    # 囲みの記号は何重でも外す("“C:\…”" のような貼り付けもある)
    while len(value) >= 1 and (value[0] in QUOTES or value[-1] in QUOTES):
        value = value.strip(QUOTES).strip()
    if value.lower().startswith("file:"):
        parsed = urlparse(value)
        path = unquote(parsed.path)
        if parsed.netloc:                                  # file://サーバ/共有/…
            value = "\\\\" + parsed.netloc + path.replace("/", "\\")
        else:                                              # file:///C:/…
            value = path.lstrip("/") if len(path) > 2 and path[2] == ":" else path
    return value


def parse(text: str) -> Path:
    """フォルダの Path を返す。読めなければ FolderInputError。"""
    value = clean(text)
    if value == "":
        raise FolderInputError("folder_empty", MESSAGE_EMPTY)
    path = Path(value)
    if not path.is_absolute():
        raise FolderInputError("folder_relative", MESSAGE_RELATIVE, value)
    try:
        if path.is_dir():
            return path
        if path.exists():
            raise FolderInputError("folder_is_file", MESSAGE_FILE, value)
    except OSError:
        pass
    raise FolderInputError("folder_missing", MESSAGE_MISSING, value)
