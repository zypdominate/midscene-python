#!/usr/bin/env python3
"""
开发者工具：下载各平台 Node.js 二进制 + 完整 npm 包，放置到 _runtime/ 目录。

在发布新版本前运行：
    python scripts/fetch_node_binaries.py

可选参数：
    --node-version  指定 Node.js 版本（默认 22.12.0）
    --platform      只下载指定平台（默认全部）
                    可选: linux-x64 linux-arm64 darwin-x64 darwin-arm64 win32-x64
    --skip-npm      跳过 npm 下载
    --npm-version   指定 npm 版本（默认 10.9.2）
"""

import argparse
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import requests

# 目标目录
SCRIPT_DIR = Path(__file__).parent
PACKAGE_DIR = SCRIPT_DIR.parent / "midscene_android"
NODE_BIN_DIR = PACKAGE_DIR / "_runtime" / "bin"
NPM_DIR = PACKAGE_DIR / "_runtime" / "npm"

# Node.js 默认版本（LTS）
DEFAULT_NODE_VERSION = "22.12.0"
DEFAULT_NPM_VERSION = "10.9.2"

# 各平台下载配置
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

# npm 完整包（从 registry 下载 tgz，解压整个 package/ 到 _runtime/npm/）
NPM_TGZ_URL = "https://registry.npmjs.org/npm/-/npm-{version}.tgz"


def download_file(url: str, dest: Path, desc: str) -> None:
    print(f"  Downloading {desc}...")
    print(f"  URL: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True) as resp:
        resp.raise_for_status()
        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = downloaded / total_size * 100
                        print(f"\r  Progress: {pct:.1f}%", end="", flush=True)
    print()


def extract_node_binary(archive_path: Path, bin_path_in_archive: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if str(archive_path).endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tar:
            member = tar.getmember(bin_path_in_archive)
            src = tar.extractfile(member)
            assert src is not None
            output_path.write_bytes(src.read())
    elif str(archive_path).endswith(".zip"):
        with zipfile.ZipFile(archive_path) as z:
            data = z.read(bin_path_in_archive)
            output_path.write_bytes(data)

    if not str(output_path).endswith(".exe"):
        output_path.chmod(output_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"  ✓ Extracted: {output_path} ({output_path.stat().st_size // 1024 // 1024} MB)")


def fetch_node_binary(platform_key: str, version: str) -> None:
    config = PLATFORMS[platform_key]
    url = config["url"].format(version=version)
    archive_name = config["archive"].format(version=version)
    bin_in_archive = config["bin_in_archive"].format(version=version)
    output = NODE_BIN_DIR / config["output"]

    if output.exists():
        print(f"  ✓ Already exists, skipping: {output.name}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / archive_name
        download_file(url, archive_path, f"Node.js {version} ({platform_key})")
        extract_node_binary(archive_path, bin_in_archive, output)


def fetch_npm(version: str = DEFAULT_NPM_VERSION) -> None:
    """
    下载完整 npm 包，解压到 _runtime/npm/。

    npm tgz 内部结构为 package/...，解压后目录结构：
      _runtime/npm/bin/npm-cli.js   ← 入口
      _runtime/npm/lib/...
      _runtime/npm/node_modules/...

    调用方式：<node_bin> _runtime/npm/bin/npm-cli.js install
    """
    npm_cli_entry = NPM_DIR / "bin" / "npm-cli.js"
    if npm_cli_entry.exists():
        print(f"  ✓ npm already exists, skipping ({npm_cli_entry})")
        return

    url = NPM_TGZ_URL.format(version=version)
    with tempfile.TemporaryDirectory() as tmp:
        tgz_path = Path(tmp) / f"npm-{version}.tgz"
        download_file(url, tgz_path, f"npm {version} (full package)")

        NPM_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  Extracting to {NPM_DIR} ...")
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                # 内部路径形如 package/bin/npm-cli.js，去掉 package/ 前缀
                if not member.name.startswith("package/"):
                    continue
                rel = member.name[len("package/"):]
                if not rel:
                    continue
                dest = NPM_DIR / rel
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    f = tar.extractfile(member)
                    if f:
                        dest.write_bytes(f.read())

    print(f"  ✓ npm extracted: {npm_cli_entry}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-version", default=DEFAULT_NODE_VERSION)
    parser.add_argument("--npm-version", default=DEFAULT_NPM_VERSION)
    parser.add_argument("--platform", choices=list(PLATFORMS.keys()), default=None)
    parser.add_argument("--skip-npm", action="store_true")
    args = parser.parse_args()

    platforms = [args.platform] if args.platform else list(PLATFORMS.keys())

    print(f"Node.js version : {args.node_version}")
    print(f"npm version     : {args.npm_version}")
    print(f"Platforms       : {', '.join(platforms)}")
    print(f"Output dir      : {NODE_BIN_DIR}")
    print()

    for platform_key in platforms:
        print(f"[{platform_key}]")
        try:
            fetch_node_binary(platform_key, args.node_version)
        except Exception as e:
            print(f"  ✗ Failed: {e}", file=sys.stderr)
        print()

    if not args.skip_npm:
        print("[npm]")
        try:
            fetch_npm(args.npm_version)
        except Exception as e:
            print(f"  ✗ Failed: {e}", file=sys.stderr)
        print()

    print("Done. You can now run: python -m build")


if __name__ == "__main__":
    main()