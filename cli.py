"""
midscene-android CLI

当前支持的命令：
  midscene-android info    - 显示运行时信息（Node 路径、缓存目录等）
  midscene-android clean   - 清除 npm 缓存，下次运行时重新安装
"""

from __future__ import annotations

import sys


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "help"

    if cmd == "info":
        _cmd_info()
    elif cmd == "clean":
        _cmd_clean()
    else:
        _cmd_help()


def _cmd_info() -> None:
    from ._node_manager import (
        _get_node_bin_path,
        _NODE_SERVICE_CACHE,
        _NPM_DONE_FLAG,
        _CACHE_DIR,
    )
    import platform

    print("midscene-android runtime info")
    print("=" * 40)
    print(f"Platform      : {platform.system()} {platform.machine()}")
    print(f"Cache dir     : {_CACHE_DIR}")
    print(f"Service cache : {_NODE_SERVICE_CACHE}")
    print(f"npm installed : {_NPM_DONE_FLAG.exists()}")

    try:
        node_bin = _get_node_bin_path()
        print(f"Node binary   : {node_bin} ({'exists' if node_bin.exists() else 'MISSING'})")
    except FileNotFoundError as e:
        print(f"Node binary   : ERROR - {e}")


def _cmd_clean() -> None:
    from ._node_manager import _NODE_SERVICE_CACHE
    import shutil

    if _NODE_SERVICE_CACHE.exists():
        shutil.rmtree(_NODE_SERVICE_CACHE)
        print(f"Cleaned: {_NODE_SERVICE_CACHE}")
        print("Next run will re-install @midscene/android from npm.")
    else:
        print("Nothing to clean.")


def _cmd_help() -> None:
    print(__doc__)