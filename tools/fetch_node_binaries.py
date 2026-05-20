#!/usr/bin/env python3
"""
开发者工具：下载各平台 Node.js 二进制 + npm-cli.js，放置到 _runtime/ 目录。

在发布新版本前运行：
    python scripts/fetch_node_binaries.py

可选参数：
    --node-version  指定 Node.js 版本（默认 22.12.0）
    --platform      只下载指定平台（默认全部）
                    可选: linux-x64 linux-arm64 darwin-x64 darwin-arm64 win32-x64
    --skip-npm      跳过 npm-cli.js 下载
"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# 目标目录
SCRIPT_DIR = Path(__file__).parent
PACKAGE_DIR = SCRIPT_DIR.parent / "midscene_android"
NODE_BIN_DIR = PACKAGE_DIR / "_runtime" / "bin"
NPM_DIR = PACKAGE_DIR / "_runtime" / "npm"

# Node.js 默认版本（LTS）
DEFAULT_NODE_VERSION = "22.12.0"

# 各平台的下载配置
# key: 我们的命名规范  value: Node.js 官方发行包命名
PLATFORMS = {
    "linux-x64": {
        "archive": "node-v{version}-linux-x64.tar.gz",
        "bin_in_archive": "node-v{version}-linux-x64/bin/node",
        "output": "node-linux-x64",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-linux-x64.tar.gz",
    },
    "linux-arm64": {
        "archive": "node-v{version}-linux-arm64.tar.gz",
        "bin_in_archive": "node-v{version}-linux-arm64/bin/node",
        "output": "node-linux-arm64",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-linux-arm64.tar.gz",
    },
    "darwin-x64": {
        "archive": "node-v{version}-darwin-x64.tar.gz",
        "bin_in_archive": "node-v{version}-darwin-x64/bin/node",
        "output": "node-darwin-x64",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-darwin-x64.tar.gz",
    },
    "darwin-arm64": {
        "archive": "node-v{version}-darwin-arm64.tar.gz",
        "bin_in_archive": "node-v{version}-darwin-arm64/bin/node",
        "output": "node-darwin-arm64",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-darwin-arm64.tar.gz",
    },
    "win32-x64": {
        "archive": "node-v{version}-win-x64.zip",
        "bin_in_archive": "node-v{version}-win-x64/node.exe",
        "output": "node-win32-x64.exe",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-win-x64.zip",
    },
}

# npm-cli.js 下载（从 npm registry 获取 npm 包中提取）
NPM_CLI_URL = "https://registry.npmjs.org/npm/-/npm-{npm_version}.tgz"
NPM_CLI_PATH_IN_TGZ = "package/bin/npm-cli.js"


def download_file(url: str, dest: Path, desc: str) -> None:
    print(f"  Downloading {desc}...")
    print(f"  URL: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _progress(block_num, block_size, total_size):
        if total_size > 0:
            pct = min(block_num * block_size / total_size * 100, 100)
            print(f"\r  Progress: {pct:.1f}%", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=_progress)
    print()  # newline after progress


def extract_node_binary(archive_path: Path, bin_path_in_archive: str, output_path: Path) -> None:
    """从压缩包中提取 node 可执行文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if archive_path.suffix == ".gz":
        with tarfile.open(archive_path, "r:gz") as tar:
            member = tar.getmember(bin_path_in_archive)
            src = tar.extractfile(member)
            assert src is not None
            output_path.write_bytes(src.read())
    elif archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as z:
            data = z.read(bin_path_in_archive)
            output_path.write_bytes(data)

    # 设置可执行权限（Windows 不需要）
    if not str(output_path).endswith(".exe"):
        output_path.chmod(output_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"  ✓ Extracted: {output_path} ({output_path.stat().st_size // 1024 // 1024}MB)")


def fetch_node_binary(platform_key: str, version: str) -> None:
    config = PLATFORMS[platform_key]
    url = config["url"].format(version=version)
    archive_name = config["archive"].format(version=version)
    bin_in_archive = config["bin_in_archive"].format(version=version)
    output = NODE_BIN_DIR / config["output"]

    if output.exists():
        print(f"  ✓ Already exists, skipping: {output}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / archive_name
        download_file(url, archive_path, f"Node.js {version} ({platform_key})")
        extract_node_binary(archive_path, bin_in_archive, output)


def fetch_npm_cli(version: str = "10.9.2") -> None:
    """下载 npm-cli.js，作为内置 npm 使用。"""
    output = NPM_DIR / "npm-cli.js"
    if output.exists():
        print(f"  ✓ npm-cli.js already exists, skipping")
        return

    url = NPM_CLI_URL.format(npm_version=version)
    with tempfile.TemporaryDirectory() as tmp:
        tgz_path = Path(tmp) / f"npm-{version}.tgz"
        download_file(url, tgz_path, f"npm {version}")

        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tgz_path, "r:gz") as tar:
            member = tar.getmember(NPM_CLI_PATH_IN_TGZ)
            src = tar.extractfile(member)
            assert src is not None
            output.write_bytes(src.read())
        print(f"  ✓ npm-cli.js extracted: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-version", default=DEFAULT_NODE_VERSION)
    parser.add_argument("--platform", choices=list(PLATFORMS.keys()), default=None)
    parser.add_argument("--skip-npm", action="store_true")
    args = parser.parse_args()

    platforms = [args.platform] if args.platform else list(PLATFORMS.keys())

    print(f"Node.js version: {args.node_version}")
    print(f"Platforms: {', '.join(platforms)}")
    print(f"Output dir: {NODE_BIN_DIR}")
    print()

    for platform_key in platforms:
        print(f"[{platform_key}]")
        try:
            fetch_node_binary(platform_key, args.node_version)
        except Exception as e:
            print(f"  ✗ Failed: {e}", file=sys.stderr)
        print()

    if not args.skip_npm:
        print("[npm-cli.js]")
        try:
            fetch_npm_cli()
        except Exception as e:
            print(f"  ✗ Failed to fetch npm-cli.js: {e}", file=sys.stderr)
        print()

    print("Done. Now you can run: python -m build")


if __name__ == "__main__":
    main()