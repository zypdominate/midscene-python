#!/usr/bin/env python3
"""
开发者工具：预下载 Node.js 二进制 + npm 到 src/midscene_android/_node_driver/（本地 git 开发用）。

PyPI 安装用户无需此脚本；首次运行时会自动下载到 ~/.midscene_android/node_runtime/。

用法：
    python tools/fetch_node_binaries.py --platform win32-x64
    python tools/fetch_node_binaries.py --platform win32-x64 --force-npm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PACKAGE_DIR = SCRIPT_DIR.parent / "src" / "midscene_android"
DEV_NODE_BIN_DIR = PACKAGE_DIR / "_node_driver" / "bin"
DEV_NPM_DIR = PACKAGE_DIR / "_node_driver" / "npm"

# 从包内 bootstrap 模块复用下载逻辑
sys.path.insert(0, str(SCRIPT_DIR.parent / "src"))
from midscene_android.node_bootstrap import (  # noqa: E402
    DEFAULT_NODE_VERSION,
    PLATFORMS,
    detect_current_platform,
    install_node_runtime,
    node_binary_path,
    npm_cli_path,
    verify_npm,
)


def fetch_npm_only(platform_key: str, version: str) -> None:
    node_bin = node_binary_path(DEV_NODE_BIN_DIR, platform_key)
    if not node_bin.exists():
        print(f"  Node binary missing, downloading with npm: {node_bin.name}")
        install_node_runtime(
            DEV_NODE_BIN_DIR,
            DEV_NPM_DIR,
            platform_key,
            version,
            extract_npm=True,
        )
    else:
        install_node_runtime(
            DEV_NODE_BIN_DIR,
            DEV_NPM_DIR,
            platform_key,
            version,
            extract_npm=True,
        )


def fetch_node_binary(
    platform_key: str,
    version: str,
    *,
    extract_npm: bool,
    force_npm: bool,
) -> None:
    node_bin = node_binary_path(DEV_NODE_BIN_DIR, platform_key)
    npm_cli = npm_cli_path(DEV_NPM_DIR)

    if node_bin.exists() and npm_cli.exists() and not force_npm and not extract_npm:
        print(f"  ✓ Already present: {node_bin.name}")
        return

    if force_npm and DEV_NPM_DIR.exists():
        print("  Replacing bundled npm (--force-npm)")

    install_node_runtime(
        DEV_NODE_BIN_DIR,
        DEV_NPM_DIR,
        platform_key,
        version,
        extract_npm=extract_npm or force_npm or not npm_cli.exists(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-version", default=DEFAULT_NODE_VERSION)
    parser.add_argument(
        "--platform",
        choices=list(PLATFORMS.keys()),
        default=None,
        help="Download target platform (default: all)",
    )
    parser.add_argument(
        "--force-npm",
        action="store_true",
        help="Re-extract npm from Node official bundle even if already present",
    )
    parser.add_argument(
        "--npm-only",
        action="store_true",
        help="Only (re)extract npm, skip Node binary download",
    )
    args = parser.parse_args()

    platforms = [args.platform] if args.platform else list(PLATFORMS.keys())
    npm_platform = args.platform or detect_current_platform()

    print(f"Node.js version : {args.node_version}")
    print(f"Output dir      : {PACKAGE_DIR / '_node_driver'}")
    print()

    if args.npm_only:
        print(f"[npm only via {npm_platform}]")
        fetch_npm_only(npm_platform, args.node_version)
    else:
        for platform_key in platforms:
            print(f"[{platform_key}]")
            try:
                fetch_node_binary(
                    platform_key,
                    args.node_version,
                    extract_npm=(platform_key == npm_platform),
                    force_npm=args.force_npm and platform_key == npm_platform,
                )
            except Exception as e:
                print(f"  ✗ Failed: {e}", file=sys.stderr)
                sys.exit(1)
            print()

        if args.force_npm and npm_platform not in platforms:
            print(f"[npm via {npm_platform}]")
            fetch_npm_only(npm_platform, args.node_version)

    node_file = node_binary_path(DEV_NODE_BIN_DIR, npm_platform)
    if node_file.exists():
        print("[verify]")
        verify_npm(node_file, DEV_NPM_DIR)
        print(f"  ✓ npm verification OK")

    print("\nDone.")


if __name__ == "__main__":
    main()
