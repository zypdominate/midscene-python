#!/usr/bin/env python3
"""
构建 midscene-android 发行包（py3-none-any wheel + sdist）。

Node 二进制与 npm 不再打入包内；用户 pip install 后首次运行自动下载。

用法：
    python tools/build_wheel.py
    python tools/build_wheel.py --clean
    python tools/build_wheel.py --wheel-only
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"


def _run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def _cleanup_temp_artifacts() -> None:
    """删除构建产生的临时目录。"""
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
        print(f"  Cleaned: {BUILD_DIR}")

    for egg_info in REPO_ROOT.glob("*.egg-info"):
        shutil.rmtree(egg_info, ignore_errors=True)
        print(f"  Cleaned: {egg_info}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="构建前清空 dist/")
    parser.add_argument("--wheel-only", action="store_true", help="只构建 wheel")
    parser.add_argument("--sdist-only", action="store_true", help="只构建 sdist")
    args = parser.parse_args()

    if args.clean and DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
        print(f"  Cleaned: {DIST_DIR}")

    try:
        import build  # noqa: F401
    except ImportError:
        print("Installing build...")
        subprocess.run([sys.executable, "-m", "pip", "install", "build"], check=True)

    try:
        if not args.sdist_only:
            _run([sys.executable, "-m", "build", "--wheel", "--outdir", str(DIST_DIR)])

        if not args.wheel_only:
            _run([sys.executable, "-m", "build", "--sdist", "--outdir", str(DIST_DIR)])
    finally:
        _cleanup_temp_artifacts()

    print(f"\n{'=' * 60}")
    print(f"  Build Summary  →  {DIST_DIR}")
    print(f"{'=' * 60}")
    if DIST_DIR.exists():
        for artifact in sorted(DIST_DIR.iterdir()):
            size = artifact.stat().st_size
            label = (
                f"{size / 1024 / 1024:.1f} MB"
                if size > 1024 * 1024
                else f"{size / 1024:.0f} KB"
            )
            print(f"  ✓ {artifact.name:<60} {label}")
    else:
        print("  (empty)")


if __name__ == "__main__":
    main()
