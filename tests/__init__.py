"""試験。本物のローカル領域(%LOCALAPPDATA%\\FileListTool)を触らないよう、一時フォルダへ逃がす。

    python -m unittest discover -s tests -t . -v
"""
import os
import tempfile

_LOCAL = tempfile.mkdtemp(prefix="filelist-test-local-")
os.environ["FILELIST_TOOL_LOCAL_DIR"] = _LOCAL

import logging

for _name in ("launcher", "server", "app"):
    logging.getLogger(_name).addHandler(logging.NullHandler())
