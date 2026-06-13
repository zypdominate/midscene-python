#!/usr/bin/env python3
"""
平台差异化 Wheel 构建脚本。

为指定平台构建只包含该平台 Node.js 二进制的 wheel，
避免将所有平台的 Node 二进制（共 ~400MB）打入同一个包。

用法
----
# 为当前平台构建
python tools/build_platform_wheel.py

# 为指定平台构建（可在任意平台交叉构建）
python tools/build_platform_wheel.py --platform win32-x64
python tools/build_platform_wheel.py --platform linux-x64
python tools/build_platform_wheel.py --platform linux-arm64
python tools/build_platform_wheel.py --platform darwin-x64
python tools/build_platform_wheel.py --platform darwin-arm64

# 构建全部平台 wheel（自动下载所需 Node 二进制）
python tools/build_platform_wheel.py --all

依赖
----
    pip install build wheel requests
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
NODE_BIN_DIR = REPO_ROOT / "src" / "midscene_android" / "_node_driver" / "bin"
DIST_DIR = REPO_ROOT / "dist"

# ─── 平台配置 ───
#
# key          : fetch_node_binaries.py 中的 --platform 参数
# node_file    : 放置在 _node_driver/bin/ 下的文件名
# wheel_plat   : bdist_wheel --plat-name 接受的平台 tag
#
PLATFORM_MAP: dict[str, dict[str, str]] = {
    "win32-x64": {
        "node_file": "node-win32-x64.exe",
        "wheel_plat": "win_amd64",
    },
    "linux-x64": {
        "node_file": "node-linux-x64",
        # manylinux_2_17 覆盖 CentOS 7+ / Ubuntu 18.04+ / Debian 9+
        "wheel_plat": "manylinux_2_17_x86_64.manylinux2014_x86_64",
    },
    "linux-arm64": {
        "node_file": "node-linux-arm64",
        "wheel_plat": "manylinux_2_17_aarch64.manylinux2014_aarch64",
    },
    "darwin-x64": {
        "node_file": "node-darwin-x64",
        "wheel_plat": "macosx_10_14_x86_64",
    },
    "darwin-arm64": {
        "node_file": "node-darwin-arm64",
        "wheel_plat": "macosx_11_0_arm64",
    },
}

ALL_PLATFORMS = list(PLATFORM_MAP.keys())


# ─── 工具函数 ───


def _run(cmd: list[str], cwd: Path = REPO_ROOT) -> None:
    """运行命令，失败时抛出 RuntimeError。"""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


def _detect_current_platform() -> str:
    """根据当前系统自动识别平台 key。"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        return "win32-x64"
    elif system == "darwin":
        return "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x64"
    else:
        return "linux-arm64" if machine in ("arm64", "aarch64") else "linux-x64"


def _ensure_node_binary(platform_key: str) -> None:
    """
    确保指定平台的 Node 二进制已存在。
    不存在时调用 fetch_node_binaries.py 自动下载。
    """
    cfg = PLATFORM_MAP[platform_key]
    node_file = NODE_BIN_DIR / cfg["node_file"]

    if node_file.exists():
        print(f"  ✓ Node binary exists: {node_file.name}")
        return

    print(f"  Downloading Node binary for {platform_key} ...")
    fetch_script = REPO_ROOT / "tools" / "fetch_node_binaries.py"
    _run([sys.executable, str(fetch_script), "--platform", platform_key, "--skip-npm"])


def _hide_other_binaries(keep_platform: str) -> dict[str, Path]:
    """
    将其他平台的 Node 二进制临时重命名为 .bak，
    使 setuptools 的 package-data 只收集目标平台的文件。

    返回 {原始名: bak路径} 字典，用于还原。
    """
    keep_file = PLATFORM_MAP[keep_platform]["node_file"]
    backed_up: dict[str, Path] = {}

    for plat_key, cfg in PLATFORM_MAP.items():
        if plat_key == keep_platform:
            continue
        original = NODE_BIN_DIR / cfg["node_file"]
        if original.exists():
            bak = original.with_suffix(original.suffix + ".bak")
            original.rename(bak)
            backed_up[cfg["node_file"]] = bak

    return backed_up


def _restore_binaries(backed_up: dict[str, Path]) -> None:
    """还原被临时隐藏的 Node 二进制。"""
    for original_name, bak_path in backed_up.items():
        original = NODE_BIN_DIR / original_name
        if bak_path.exists():
            bak_path.rename(original)


def build_sdist() -> Path:
    """
    构建源码包 (.tar.gz)。

    sdist 包含所有 Python 源码和 service.js，但不含 Node 二进制
    （Node 二进制是平台相关的大文件，由各平台 wheel 单独携带）。
    安装时若无匹配 wheel，pip 会下载 sdist 并提示用户手动运行
    fetch_node_binaries.py。

    构建工具：python setup.py sdist --formats=gztar
    """
    print(f"\n{'=' * 60}")
    print("  Building sdist (.tar.gz)")
    print(f"{'=' * 60}")

    DIST_DIR.mkdir(exist_ok=True)
    _run(
        [sys.executable, "setup.py", "sdist", "--formats=gztar", f"--dist-dir={DIST_DIR}"]
    )

    tarballs = sorted(
        DIST_DIR.glob("*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not tarballs:
        raise FileNotFoundError(f"No .tar.gz found in {DIST_DIR}")

    sdist_path = tarballs[0]
    size_kb = sdist_path.stat().st_size / 1024
    print(f"\n  ✓ sdist built: {sdist_path.name}  ({size_kb:.0f} KB)")
    return sdist_path


def build_wheel(platform_key: str) -> Path:
    """
    为指定平台构建一个 wheel 文件（py3-none-<plat>.whl）。

    步骤：
    1. 确保目标平台 Node 二进制存在（否则自动下载）
    2. 临时隐藏其他平台的 Node 二进制，使 package-data 只收集目标文件
    3. 调用 setup.py bdist_wheel --plat-name <tag>
       → 产出 py3-none-<plat>.whl（不绑定 CPython 版本）
    4. 还原隐藏的文件
    5. 返回生成的 .whl 路径
    """
    cfg = PLATFORM_MAP[platform_key]
    wheel_plat = cfg["wheel_plat"]

    print(f"\n{'=' * 60}")
    print(f"  Building wheel: {platform_key}  →  py3-none-{wheel_plat}")
    print(f"{'=' * 60}")

    _ensure_node_binary(platform_key)

    backed_up = _hide_other_binaries(platform_key)
    try:
        DIST_DIR.mkdir(exist_ok=True)
        _run(
            [
                sys.executable,
                "setup.py",
                "bdist_wheel",
                f"--plat-name={wheel_plat}",
                f"--dist-dir={DIST_DIR}",
            ]
        )
    finally:
        _restore_binaries(backed_up)

    # 找到刚生成的 wheel（按修改时间排序取最新）
    wheels = sorted(
        DIST_DIR.glob(f"*{wheel_plat}*.whl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not wheels:
        raise FileNotFoundError(
            f"No wheel found in {DIST_DIR} for platform {wheel_plat}"
        )

    wheel_path = wheels[0]
    size_mb = wheel_path.stat().st_size / 1024 / 1024
    print(f"\n  ✓ Wheel built: {wheel_path.name}  ({size_mb:.1f} MB)")
    return wheel_path


# ─── CLI ───


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--platform",
        choices=ALL_PLATFORMS,
        default=None,
        help="目标平台（默认：自动检测当前平台）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="构建全部 5 个平台 wheel + sdist",
    )
    parser.add_argument(
        "--sdist-only",
        action="store_true",
        help="只构建 sdist (.tar.gz)，不构建 wheel",
    )
    parser.add_argument(
        "--no-sdist",
        action="store_true",
        help="只构建 wheel，跳过 sdist",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="构建前清空 dist/ 目录",
    )
    args = parser.parse_args()

    if args.clean and DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
        print(f"  Cleaned: {DIST_DIR}")

    built: list[Path] = []
    failed: list[str] = []

    # ── sdist ───
    if not args.no_sdist:
        try:
            sdist = build_sdist()
            built.append(sdist)
        except Exception as exc:
            print(f"\n  ✗ Failed to build sdist: {exc}", file=sys.stderr)
            failed.append("sdist")

    # ── wheel(s) ───
    if not args.sdist_only:
        if args.all:
            platforms = ALL_PLATFORMS
        elif args.platform:
            platforms = [args.platform]
        else:
            detected = _detect_current_platform()
            print(f"\n  Auto-detected platform: {detected}")
            platforms = [detected]

        for plat in platforms:
            try:
                whl = build_wheel(plat)
                built.append(whl)
            except Exception as exc:
                print(f"\n  ✗ Failed to build wheel [{plat}]: {exc}", file=sys.stderr)
                failed.append(plat)

    # ── Summary ────
    print(f"\n{'=' * 60}")
    print(f"  Build Summary  →  {DIST_DIR}")
    print(f"{'=' * 60}")
    for artifact in built:
        size = artifact.stat().st_size
        label = (
            f"{size / 1024 / 1024:.1f} MB"
            if size > 1024 * 1024
            else f"{size / 1024:.0f} KB"
        )
        print(f"  ✓ {artifact.name:<60} {label}")
    for name in failed:
        print(f"  ✗ {name}  (failed)")

    # ── Cleanup ────
    build_dir = REPO_ROOT / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
        print(f"  Cleaned temporary build dir: {build_dir}")
    for egg_info in REPO_ROOT.glob("*.egg-info"):
        shutil.rmtree(egg_info, ignore_errors=True)
        print(f"  Cleaned temporary egg-info dir: {egg_info}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
