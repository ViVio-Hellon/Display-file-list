"""試験用: **ソケットを開くと落ちる**ようにしてから bridge.py を動かす(ポートを使わないことの確かめ)。"""
import runpy
import socket
import sys
from pathlib import Path


class _NoSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise OSError("デスクトップ版はソケットを開いてはいけません")


socket.socket = _NoSocket                     # type: ignore[misc]
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(OSError("ソケットは使えません"))  # noqa: E731
root = Path(__file__).resolve().parents[2]
sys.argv = [str(root / "bridge.py")]
sys.path.insert(0, str(root))
runpy.run_path(str(root / "bridge.py"), run_name="__main__")
