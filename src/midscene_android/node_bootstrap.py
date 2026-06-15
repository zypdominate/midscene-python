"""
首次使用时从 nodejs.org 下载 Node 二进制与 npm，缓存到 ~/.midscene_android/node_runtime/。

PyPI 包不再携带 Node/npm 大文件；pip install 后由 runtime 自动调用本模块。
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

import requests

from .exceptions import MidsceneSetupError

logger = logging.getLogger(__name__)

DEFAULT_NODE_VERSION = "22.12.0"

CACHE_DIR = Path.home() / ".midscene_android"
NODE_RUNTIME_CACHE = CACHE_DIR / "node_runtime"
NODE_RUNTIME_BIN = NODE_RUNTIME_CACHE / "bin"
NODE_RUNTIME_NPM = NODE_RUNTIME_CACHE / "npm"
NODE_VERSION_FILE = NODE_RUNTIME_CACHE / ".node_version"

# npm_prefix：Node 官方压缩包内 npm 目录的路径前缀（用于解压提取内置 npm）
PLATFORMS: dict[str, dict[str, str]] = {
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


def detect_current_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "win32-x64"
    if system == "darwin":
        return "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x64"
    return "linux-arm64" if machine in ("arm64", "aarch64") else "linux-x64"


def get_node_version() -> str:
    return os.environ.get("MIDSCENE_NODE_VERSION", DEFAULT_NODE_VERSION)


def node_binary_path(bin_dir: Path, platform_key: str | None = None) -> Path:
    key = platform_key or detect_current_platform()
    return bin_dir / PLATFORMS[key]["output"]


def npm_cli_path(npm_dir: Path) -> Path:
    return npm_dir / "bin" / "npm-cli.js"


def is_node_runtime_ready(
    bin_dir: Path = NODE_RUNTIME_BIN,
    npm_dir: Path = NODE_RUNTIME_NPM,
    *,
    version: str | None = None,
    platform_key: str | None = None,
) -> bool:
    version = version or get_node_version()
    platform_key = platform_key or detect_current_platform()
    node_bin = node_binary_path(bin_dir, platform_key)
    npm_cli = npm_cli_path(npm_dir)
    if not node_bin.is_file() or not npm_cli.is_file():
        return False
    if not NODE_VERSION_FILE.is_file():
        return False
    return NODE_VERSION_FILE.read_text(encoding="utf-8").strip() == version


def download_file(url: str, dest: Path, desc: str) -> None:
    print(f"  Downloading {desc}...", flush=True)
    print(f"  URL: {url}", flush=True)
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
    print(flush=True)


def _chmod_executable(path: Path) -> None:
    if not str(path).endswith(".exe"):
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def extract_node_binary(
    archive_path: Path,
    bin_path_in_archive: str,
    output_path: Path,
) -> None:
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
    size_mb = output_path.stat().st_size // 1024 // 1024
    print(f"  ✓ Node binary: {output_path.name} ({size_mb} MB)", flush=True)


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
    print(f"  ✓ npm extracted ({count} files)", flush=True)


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
    print(f"  ✓ npm extracted ({count} files)", flush=True)


def install_node_runtime(
    bin_dir: Path,
    npm_dir: Path,
    platform_key: str,
    version: str,
    *,
    extract_npm: bool = True,
) -> Path:
    """下载并解压 Node + npm 到指定目录，返回 node 可执行文件路径。"""
    config = PLATFORMS[platform_key]
    url = config["url"].format(version=version)
    archive_name = config["archive"].format(version=version)
    bin_in_archive = config["bin_in_archive"].format(version=version)
    npm_prefix = config["npm_prefix"].format(version=version)
    output = bin_dir / config["output"]

    bin_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / archive_name
        download_file(url, archive_path, f"Node.js {version} ({platform_key})")

        if not output.exists():
            extract_node_binary(archive_path, bin_in_archive, output)

        if extract_npm:
            if str(archive_path).endswith(".tar.gz"):
                extract_npm_from_tar(archive_path, npm_prefix, npm_dir)
            else:
                extract_npm_from_zip(archive_path, npm_prefix, npm_dir)

    npm_cli = npm_cli_path(npm_dir)
    if not npm_cli.is_file():
        raise MidsceneSetupError(f"npm extraction failed: {npm_cli} not found")

    return output


def verify_npm(node_bin: Path, npm_dir: Path) -> None:
    npm_cli = npm_cli_path(npm_dir)
    result = subprocess.run(
        [str(node_bin), str(npm_cli), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise MidsceneSetupError(
            f"npm verification failed (exit={result.returncode})\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    logger.debug("npm verification OK: v%s", result.stdout.strip())


def _print_banner(*lines: str) -> None:
    sep = "=" * 60
    print(f"\n{sep}", flush=True)
    for line in lines:
        print(f"[midscene-android] {line}", flush=True)
    print(f"{sep}\n", flush=True)


def try_seed_from_dev_bundle() -> bool:
    """
    若 git 开发目录已有 _node_driver（fetch_node_binaries 预填），复制到缓存。
    pip 安装用户无此目录，会直接走 nodejs.org 下载。
    """
    if is_node_runtime_ready():
        return True

    try:
        from .runtime import PACKAGE_DIR
    except ImportError:
        return False

    dev_bin_dir = PACKAGE_DIR / "_node_driver" / "bin"
    dev_npm_dir = PACKAGE_DIR / "_node_driver" / "npm"
    platform_key = detect_current_platform()
    dev_node = node_binary_path(dev_bin_dir, platform_key)
    dev_npm = npm_cli_path(dev_npm_dir)

    if not dev_node.is_file() or not dev_npm.is_file():
        return False

    print("[midscene-android] Seeding Node runtime from local _node_driver/ ...", flush=True)
    NODE_RUNTIME_BIN.mkdir(parents=True, exist_ok=True)
    dest_node = node_binary_path(NODE_RUNTIME_BIN, platform_key)
    shutil.copy2(dev_node, dest_node)
    _chmod_executable(dest_node)

    if NODE_RUNTIME_NPM.exists():
        shutil.rmtree(NODE_RUNTIME_NPM)
    shutil.copytree(dev_npm_dir, NODE_RUNTIME_NPM)

    NODE_VERSION_FILE.write_text(get_node_version(), encoding="utf-8")
    print(f"[midscene-android] Node runtime seeded → {NODE_RUNTIME_CACHE}", flush=True)
    return True


def ensure_node_runtime() -> Path:
    """
    确保当前平台的 Node + npm 已缓存到 ~/.midscene_android/node_runtime/。

    Returns:
        Node 可执行文件路径。
    """
    version = get_node_version()
    platform_key = detect_current_platform()

    if is_node_runtime_ready(version=version, platform_key=platform_key):
        node_bin = node_binary_path(NODE_RUNTIME_BIN, platform_key)
        logger.debug("Node runtime cache hit: %s", node_bin)
        return node_bin

    if try_seed_from_dev_bundle():
        node_bin = node_binary_path(NODE_RUNTIME_BIN, platform_key)
        verify_npm(node_bin, NODE_RUNTIME_NPM)
        return node_bin

    _print_banner(
        "Downloading Node.js runtime (first use)",
        f"Node version    : {version}",
        f"Platform        : {platform_key}",
        f"Cache directory : {NODE_RUNTIME_CACHE}",
        "Requires network access to nodejs.org.",
    )

    try:
        node_bin = install_node_runtime(
            NODE_RUNTIME_BIN,
            NODE_RUNTIME_NPM,
            platform_key,
            version,
        )
        verify_npm(node_bin, NODE_RUNTIME_NPM)
    except requests.RequestException as exc:
        raise MidsceneSetupError(
            f"Failed to download Node.js from nodejs.org: {exc}\n"
            "Check network connectivity or set MIDSCENE_NODE_VERSION."
        ) from exc

    NODE_VERSION_FILE.write_text(version, encoding="utf-8")
    print(
        f"[midscene-android] Node runtime ready (v{version}, {platform_key}).",
        flush=True,
    )
    return node_bin


def get_cached_node_bin() -> Path:
    """返回缓存中的 Node 路径（不触发下载）。"""
    return node_binary_path(NODE_RUNTIME_BIN)


def get_cached_npm_cli() -> Path:
    """返回缓存中的 npm-cli.js 路径（不触发下载）。"""
    return npm_cli_path(NODE_RUNTIME_NPM)
