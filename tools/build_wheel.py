#!/usr/bin/env python3
"""
构建 `midscene` 发行包（py3-none-any wheel + sdist）。

Node 二进制与 npm 不打入包内；用户 pip install 后首次运行自动下载到 ~/.midscene/。
wheel 仅携带两个平台的 Node 服务源码（package.json + service.js），npm install 按需懒触发。

用法：
    python tools/build_wheel.py                 # 构建 wheel + sdist
    python tools/build_wheel.py --clean         # 构建前清空 dist/
    python tools/build_wheel.py --wheel-only
    python tools/build_wheel.py --sdist-only
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DIST_DIR = REPO_ROOT / "dist"


def _run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def _cleanup_temp_artifacts() -> None:
    """删除构建产生的临时目录。"""
    build_dir = REPO_ROOT / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
        print(f"  Cleaned: {build_dir}")
    for egg_info in (REPO_ROOT / "src").glob("*.egg-info"):
        shutil.rmtree(egg_info, ignore_errors=True)
        print(f"  Cleaned: {egg_info}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clean", action="store_true", help="构建前清空 dist/")
    parser.add_argument("--wheel-only", action="store_true", help="只构建 wheel")
    parser.add_argument("--sdist-only", action="store_true", help="只构建 sdist")
    args = parser.parse_args()

    if args.clean and DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
        print(f"  Cleaned: {DIST_DIR}")
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import build  # noqa: F401
    except ImportError:
        print("Installing build...")
        subprocess.run([sys.executable, "-m", "pip", "install", "build"], check=True)

    try:
        if not args.sdist_only:
            _run([sys.executable, "-m", "build", "--wheel", str(REPO_ROOT), "--outdir", str(DIST_DIR)])
        if not args.wheel_only:
            _run([sys.executable, "-m", "build", "--sdist", str(REPO_ROOT), "--outdir", str(DIST_DIR)])
    finally:
        _cleanup_temp_artifacts()

    print(f"\n{'=' * 60}")
    print(f"  Build Summary  →  {DIST_DIR}")
    print(f"{'=' * 60}")
    for artifact in sorted(DIST_DIR.iterdir()):
        size = artifact.stat().st_size
        label = (
            f"{size / 1024 / 1024:.1f} MB"
            if size > 1024 * 1024
            else f"{size / 1024:.0f} KB"
        )
        print(f"  ✓ {artifact.name:<55} {label}")


if __name__ == "__main__":
    main()
