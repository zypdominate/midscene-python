#!/usr/bin/env python3
"""
已弃用：请使用 tools/build_wheel.py。

保留此文件仅为兼容旧文档/脚本引用，内部转发到 build_wheel.py。
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    print(
        "Note: build_platform_wheel.py is deprecated; use tools/build_wheel.py instead.",
        file=sys.stderr,
    )
    runpy.run_path(str(Path(__file__).parent / "build_wheel.py"), run_name="__main__")
