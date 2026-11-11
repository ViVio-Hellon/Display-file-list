#!/usr/bin/env python3
"""デスクトップ版(Tauri)のアイコンを作る(標準ライブラリだけ)

窓・タスクバー・exe に出るアイコン。画面の上の帯と同じ色(tokens.css の --bar-a → --bar-b)の
角丸に、白で「一覧」の印(点と横線の3行)。作り直すときだけ流す(作ったものはリポジトリに入れてある)。

    python scripts/make_desktop_icon.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src-tauri" / "icons"
TOP = (0x15, 0x32, 0x47)          # --bar-a
BOTTOM = (0x1e, 0x60, 0x79)       # --bar-b
WHITE = (255, 255, 255)


def _inside_round(x: float, y: float, size: int, radius: float) -> float:
    """角丸の中なら 1、外なら 0(縁はなめらかに)。"""
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
    return max(0.0, min(1.0, radius - d + 0.5))


def _shapes(size: int) -> list:
    """白で塗る形(点は円、線は角丸の棒)。0〜1 の割合で決めて大きさに合わせる。"""
    out = []
    for row in range(3):
        cy = (0.30 + row * 0.20) * size
        out.append(("dot", 0.27 * size, cy, 0.055 * size))
        out.append(("bar", 0.40 * size, cy, 0.76 * size, 0.045 * size))
    return out


def _white(x: float, y: float, shapes: list) -> float:
    best = 0.0
    for shape in shapes:
        if shape[0] == "dot":
            _, cx, cy, r = shape
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        else:
            _, x0, cy, x1, r = shape
            d = ((x - min(max(x, x0), x1)) ** 2 + (y - cy) ** 2) ** 0.5
        best = max(best, max(0.0, min(1.0, r - d + 0.5)))
    return best


def draw(size: int) -> bytes:
    """RGBA の生の画素。"""
    shapes = _shapes(size)
    radius = size / 6
    rows = []
    for y in range(size):
        t = y / max(size - 1, 1)
        base = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
        row = bytearray([0])                               # PNG の行の頭(フィルタなし)
        for x in range(size):
            alpha = _inside_round(x + 0.5, y + 0.5, size, radius)
            w = _white(x + 0.5, y + 0.5, shapes)
            color = tuple(round(c + (255 - c) * w) for c in base)
            row += bytes(color) + bytes([round(alpha * 255)])
        rows.append(bytes(row))
    return b"".join(rows)


def png(size: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    head = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
            + chunk(b"IDAT", zlib.compress(draw(size), 9)) + chunk(b"IEND", b""))


def ico(sizes: list) -> bytes:
    """中身が PNG のアイコン(Windows Vista 以降が読める形)。"""
    images = [png(s) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for s, data in zip(sizes, images):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(images)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.png").write_bytes(png(512))
    for size in (32, 128):
        (OUT / f"{size}x{size}.png").write_bytes(png(size))
    (OUT / "icon.ico").write_bytes(ico([16, 24, 32, 48, 64, 128, 256]))
    print(f"作りました: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
