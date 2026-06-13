#!/usr/bin/env python3
"""
开发者工具：下载各平台 Node.js 二进制 + npm（来自 Node 官方发行包），放置到 src/midscene_android/_node_driver/。

npm 从 Node 官方包内的 node_modules/npm 提取（与 Node 版本配套），不使用系统 npm，
也不单独下载 npm registry tgz（Windows 上易静默失败）。

用法：
    python tools/fetch_node_binaries.py --platform win32-x64
    python tools/fetch_node_binaries.py --platform win32-x64 --force-npm
"""

from __future__ import annotations

import argparse
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
PACKAGE_DIR = SCRIPT_DIR.parent / "src" / "midscene_android"
NODE_BIN_DIR = PACKAGE_DIR / "_node_driver" / "bin"
NPM_DIR = PACKAGE_DIR / "_node_driver" / "npm"

DEFAULT_NODE_VERSION = "22.12.0"

PLATFORMS = {
    # npm_prefix：Node 官方压缩包内 npm 目录的路径前缀（用于解压提取内置 npm），
    "linux-x64": {
        "archive": "node-v{version}-linux-x64.tar.gz",
        "bin_in_archive": "node-v{version}-linux-x64/bin/node",
        "npm_prefix": "node-v{version}-linux-x64/lib/node_modules/npm/",
        "output": "node-linux-x64",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-linux-x64.tar.gz",
    },
    "linux-arm64": {
        "archive": "node-v{version}-linux-arm64.tar.gz",
        "bin_in_archive": "node-v{version}-linux-arm64/bin/node",
        "npm_prefix": "node-v{version}-linux-arm64/lib/node_modules/npm/",
        "output": "node-linux-arm64",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-linux-arm64.tar.gz",
    },
    "darwin-x64": {
        "archive": "node-v{version}-darwin-x64.tar.gz",
        "bin_in_archive": "node-v{version}-darwin-x64/bin/node",
        "npm_prefix": "node-v{version}-darwin-x64/lib/node_modules/npm/",
        "output": "node-darwin-x64",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-darwin-x64.tar.gz",
    },
    "darwin-arm64": {
        "archive": "node-v{version}-darwin-arm64.tar.gz",
        "bin_in_archive": "node-v{version}-darwin-arm64/bin/node",
        "npm_prefix": "node-v{version}-darwin-arm64/lib/node_modules/npm/",
        "output": "node-darwin-arm64",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-darwin-arm64.tar.gz",
    },
    "win32-x64": {
        "archive": "node-v{version}-win-x64.zip",
        "bin_in_archive": "node-v{version}-win-x64/node.exe",
        "npm_prefix": "node-v{version}-win-x64/node_modules/npm/",
        "output": "node-win32-x64.exe",
        "url": "https://nodejs.org/dist/v{version}/node-v{version}-win-x64.zip",
    },
}


def download_file(url: str, dest: Path, desc: str) -> None:
    print(f"  Downloading {desc}...")
    print(f"  URL: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True, timeout=120) as resp:
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


def _chmod_executable(path: Path) -> None:
    if not str(path).endswith(".exe"):
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def extract_node_binary(archive_path: Path, bin_path_in_archive: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if str(archive_path).endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tar:
            member = tar.getmember(bin_path_in_archive)
            src = tar.extractfile(member)
            assert src is not None
            output_path.write_bytes(src.read())
    else:
        with zipfile.ZipFile(archive_path) as zf:
            output_path.write_bytes(zf.read(bin_path_in_archive))

    _chmod_executable(output_path)
    print(f"  ✓ Node binary: {output_path} ({output_path.stat().st_size // 1024 // 1024} MB)")


def _clear_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def extract_npm_from_tar(archive_path: Path, npm_prefix: str, dest: Path) -> None:
    _clear_dir(dest)
    count = 0
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.startswith(npm_prefix) or member.isdir():
                continue
            rel = member.name[len(npm_prefix):]
            if not rel:
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            assert src is not None
            out.write_bytes(src.read())
            count += 1
    print(f"  ✓ npm extracted from Node tarball ({count} files) → {dest}")


def extract_npm_from_zip(archive_path: Path, npm_prefix: str, dest: Path) -> None:
    _clear_dir(dest)
    count = 0
    with zipfile.ZipFile(archive_path) as zf:
        for name in zf.namelist():
            if not name.startswith(npm_prefix) or name.endswith("/"):
                continue
            rel = name[len(npm_prefix):]
            if not rel:
                continue
            out = dest / Path(rel.replace("\\", "/"))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(name))
            count += 1
    print(f"  ✓ npm extracted from Node zip ({count} files) → {dest}")


def fetch_npm_from_node_archive(
        platform_key: str,
        version: str,
        *,
        force: bool,
) -> None:
    npm_cli = NPM_DIR / "bin" / "npm-cli.js"
    if npm_cli.exists() and not force:
        print(f"  ✓ npm already exists, skipping ({npm_cli})")
        print("    Use --force-npm to re-extract from Node official bundle")
        return

    config = PLATFORMS[platform_key]
    url = config["url"].format(version=version)
    archive_name = config["archive"].format(version=version)
    npm_prefix = config["npm_prefix"].format(version=version)

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / archive_name
        download_file(url, archive_path, f"Node.js {version} ({platform_key}, for npm)")
        if str(archive_path).endswith(".tar.gz"):
            extract_npm_from_tar(archive_path, npm_prefix, NPM_DIR)
        else:
            extract_npm_from_zip(archive_path, npm_prefix, NPM_DIR)

    if not npm_cli.exists():
        raise RuntimeError(f"npm extraction failed: {npm_cli} not found")


def fetch_node_binary(platform_key: str, version: str, *, extract_npm: bool, force_npm: bool) -> None:
    config = PLATFORMS[platform_key]
    url = config["url"].format(version=version)
    archive_name = config["archive"].format(version=version)
    bin_in_archive = config["bin_in_archive"].format(version=version)
    npm_prefix = config["npm_prefix"].format(version=version)
    output = NODE_BIN_DIR / config["output"]

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / archive_name
        need_download = not output.exists() or extract_npm or force_npm
        if need_download:
            download_file(url, archive_path, f"Node.js {version} ({platform_key})")
        else:
            print(f"  ✓ Node binary exists, skipping download: {output.name}")

        if not output.exists():
            extract_node_binary(archive_path, bin_in_archive, output)

        if extract_npm or force_npm:
            if force_npm and NPM_DIR.exists():
                print("  Replacing bundled npm (--force-npm)")
            if str(archive_path).endswith(".tar.gz"):
                extract_npm_from_tar(archive_path, npm_prefix, NPM_DIR)
            else:
                extract_npm_from_zip(archive_path, npm_prefix, NPM_DIR)


def verify_bundled_npm(node_path: Path) -> None:
    npm_cli = NPM_DIR / "bin" / "npm-cli.js"
    if not npm_cli.exists():
        raise RuntimeError(f"npm-cli.js missing: {npm_cli}")
    import subprocess

    result = subprocess.run(
        [str(node_path), str(npm_cli), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Bundled npm verification failed (exit={result.returncode})\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    print(f"  ✓ npm verification OK: v{result.stdout.strip()}")


def _detect_current_platform() -> str:
    import platform

    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "win32-x64"
    if system == "darwin":
        return "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x64"
    return "linux-arm64" if machine in ("arm64", "aarch64") else "linux-x64"


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
    npm_platform = args.platform or _detect_current_platform()

    print(f"Node.js version : {args.node_version}")
    print(f"Output dir      : {PACKAGE_DIR / '_node_driver'}")
    print()

    if args.npm_only:
        print(f"[npm only via {npm_platform}]")
        fetch_npm_from_node_archive(npm_platform, args.node_version, force=True)
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
            fetch_npm_from_node_archive(npm_platform, args.node_version, force=True)

    node_file = NODE_BIN_DIR / PLATFORMS[npm_platform]["output"]
    if node_file.exists():
        print("[verify]")
        verify_bundled_npm(node_file)

    print("\nDone.")


if __name__ == "__main__":
    main()
