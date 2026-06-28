#!/usr/bin/env python3
"""
检查 dist/ 中的发行包并上传到 PyPI / TestPyPI。

包地址
https://pypi.org/project/midscene/#history

在 build_wheel.py 构建完成后使用：

    python tools/build_wheel.py --clean
    python tools/upload_pypi.py --dry-run
    python tools/upload_pypi.py --require-all --yes

认证（任选其一）：
    - ~/.pypirc（推荐）
    - 环境变量 TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-...
    - 命令行 --token pypi-...

依赖：twine（pip install -e \".[dev]\"）
"""

from __future__ import annotations

import argparse
import configparser
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
DEFAULT_DIST_DIR = REPO_ROOT / "dist"

REPOSITORY_URLS = {
    "pypi": "https://upload.pypi.org/legacy/",
    "testpypi": "https://test.pypi.org/legacy/",
}

MAX_ARTIFACT_SIZE = 100 * 1024 * 1024  # PyPI 单文件 100 MB 限制


def is_universal_wheel(whl: Path) -> bool:
    return "-py3-none-any.whl" in whl.name


def validate_artifacts(
    artifacts: dict[str, list[Path]],
    *,
    require_all: bool,
) -> list[Path]:
    wheels = artifacts["wheels"]
    sdists = artifacts["sdists"]

    if not wheels and not sdists:
        raise FileNotFoundError("dist/ 中没有匹配当前版本的 .whl 或 .tar.gz")

    empty = [p for p in wheels + sdists if p.stat().st_size == 0]
    if empty:
        raise ValueError(f"发现空文件: {', '.join(p.name for p in empty)}")

    oversized = [p for p in wheels + sdists if p.stat().st_size > MAX_ARTIFACT_SIZE]
    if oversized:
        names = ", ".join(
            f"{p.name} ({format_size(p.stat().st_size)})" for p in oversized
        )
        raise ValueError(
            f"文件超过 PyPI 100MB 限制: {names}\n"
            "请确认 pyproject.toml 未打包 Node/npm，并重新运行 tools/build_wheel.py --clean"
        )

    files = sdists + wheels

    if require_all:
        if not sdists:
            raise FileNotFoundError("缺少 sdist (.tar.gz)，请运行: python tools/build_wheel.py --clean")
        if len(wheels) != 1:
            raise FileNotFoundError(
                f"期望 1 个 py3-none-any wheel，实际 {len(wheels)} 个"
            )
        if not is_universal_wheel(wheels[0]):
            raise FileNotFoundError(
                f"wheel 应为 py3-none-any，实际: {wheels[0].name}\n"
                "请使用 tools/build_wheel.py 构建（不再使用平台差异化 wheel）"
            )

    return files


def read_project_meta() -> tuple[str, str]:
    """从根 pyproject.toml 读取 (name, version)。"""
    text = PYPROJECT.read_text(encoding="utf-8")
    name_m = re.search(r'^name\s*=\s*"([^"]+)"', text, re.MULTILINE)
    version_m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not name_m or not version_m:
        raise RuntimeError(f"Cannot parse name/version from {PYPROJECT}")
    return name_m.group(1), version_m.group(1)


def normalized_dist_name(name: str) -> str:
    """PyPI 文件名中包名使用下划线。"""
    return name.replace("-", "_")


def find_artifacts(dist_dir: Path, dist_name: str, version: str) -> dict[str, list[Path]]:
    prefix = f"{dist_name}-{version}"
    wheels = sorted(dist_dir.glob(f"{prefix}-*.whl"))
    sdists = sorted(dist_dir.glob(f"{prefix}.tar.gz"))
    return {"wheels": wheels, "sdists": sdists}


def resolve_token(explicit: str | None) -> str | None:
    """命令行 --token 优先，其次 TWINE_PASSWORD 环境变量。"""
    if explicit:
        return explicit
    return os.environ.get("TWINE_PASSWORD") or None


def pypirc_path() -> Path:
    return Path.home() / ".pypirc"


def pypirc_has_credentials(repository: str) -> bool:
    path = pypirc_path()
    if not path.is_file():
        return False
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    if not cfg.has_section(repository):
        return False
    username = cfg.get(repository, "username", fallback="").strip()
    password = cfg.get(repository, "password", fallback="").strip()
    return bool(username and password)


def detect_auth_source(repository: str, explicit_token: str | None) -> str | None:
    if resolve_token(explicit_token):
        return "API Token（--token 或 TWINE_PASSWORD）"
    if pypirc_has_credentials(repository):
        return str(pypirc_path())
    return None


def ensure_upload_credentials(repository: str, explicit_token: str | None) -> str:
    source = detect_auth_source(repository, explicit_token)
    if source:
        return source
    pypirc = pypirc_path()
    raise RuntimeError(
        "未配置 PyPI 认证，无法上传。请任选一种方式：\n"
        f"  1. 创建 {pypirc}（格式见 RELEASE_GUIDE.md）\n"
        "  2. 设置环境变量:\n"
        "       TWINE_USERNAME=__token__\n"
        "       TWINE_PASSWORD=pypi-你的Token\n"
        "  3. 命令行传入:\n"
        "       python tools/upload_pypi.py --token pypi-..."
    )


def ensure_twine() -> None:
    try:
        import twine  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "twine 未安装。\n"
            "  twine 在 optional-dependencies.dev 中，uv.lock 里有记录不代表已装进 .venv。\n"
            "  请运行: uv sync --extra dev\n"
            "  或:     pip install -e \".[dev]\""
        ) from exc


def format_size(size: int) -> str:
    if size > 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{size / 1024:.0f} KB"


def run_streaming(cmd: list[str], *, prefix: str = "") -> None:
    """运行子进程并逐行实时回显输出（避免长时间无输出像卡住）。"""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    print(f"  $ {' '.join(cmd)}", flush=True)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )
    assert proc.stdout is not None

    def _reader() -> None:
        for line in proc.stdout:
            text = line.rstrip()
            if text:
                print(f"{prefix}{text}", flush=True)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        raise

    t.join(timeout=5)

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def run_twine_check(files: list[Path]) -> None:
    cmd = [sys.executable, "-m", "twine", "check", *[str(f) for f in files]]
    run_streaming(cmd, prefix="  ")


def _twine_upload_cmd(
    files: list[Path],
    *,
    repository: str,
    token: str | None,
    skip_existing: bool,
) -> list[str]:
    cmd = [sys.executable, "-m", "twine", "upload", "--verbose"]
    if repository != "pypi":
        cmd.extend(["--repository", repository])
    if skip_existing:
        cmd.append("--skip-existing")
    resolved = resolve_token(token)
    if resolved:
        cmd.extend(["-u", "__token__", "-p", resolved])
    cmd.extend(str(f) for f in files)
    return cmd


def run_twine_upload(
    files: list[Path],
    *,
    repository: str,
    token: str | None,
    skip_existing: bool,
    auth_source: str,
) -> None:
    total = len(files)
    total_bytes = sum(f.stat().st_size for f in files)
    repo_url = REPOSITORY_URLS[repository]

    print(f"\n目标: {repo_url}")
    print(f"认证: {auth_source}")
    print(f"共 {total} 个文件，合计 {format_size(total_bytes)}")
    print(
        "提示: 大文件 HTTPS 上传可能需要数分钟；"
        "若出现 trusted publishing 警告，表示未使用 CI 可信发布，"
        "将改用上述 API Token 认证，可忽略。\n",
        flush=True,
    )

    for index, path in enumerate(files, start=1):
        size = path.stat().st_size
        print(f"[{index}/{total}] 正在上传 {path.name} ({format_size(size)}) ...", flush=True)
        cmd = _twine_upload_cmd(
            [path],
            repository=repository,
            token=token,
            skip_existing=skip_existing,
        )
        run_streaming(cmd, prefix="  ")
        print(f"[{index}/{total}] ✓ 完成: {path.name}\n", flush=True)


def confirm_upload(files: list[Path], repository: str, version: str) -> bool:
    print(f"\n即将上传到 {repository} (v{version}):")
    for f in files:
        print(f"  - {f.name}  ({format_size(f.stat().st_size)})")
    answer = input("\n确认上传? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=DEFAULT_DIST_DIR,
        help=f"发行包目录（默认: {DEFAULT_DIST_DIR}）",
    )
    parser.add_argument(
        "--repository",
        choices=sorted(REPOSITORY_URLS),
        default="pypi",
        help="上传目标（默认: pypi）",
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="要求 dist/ 中有 sdist + 1 个 py3-none-any wheel",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查并列出文件，不上传",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="跳过 twine check",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="已存在的文件跳过（twine --skip-existing）",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过交互确认",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="PyPI API Token（也可用 TWINE_PASSWORD 环境变量）",
    )
    args = parser.parse_args()

    name, version = read_project_meta()
    dist_name = normalized_dist_name(name)
    dist_dir = args.dist_dir.resolve()

    print(f"Package : {name}")
    print(f"Version : {version}")
    print(f"Dist dir: {dist_dir}")

    if not dist_dir.is_dir():
        print(f"\n错误: dist/ 目录不存在: {dist_dir}", file=sys.stderr)
        print("请先构建: python tools/build_wheel.py --clean", file=sys.stderr)
        sys.exit(1)

    artifacts = find_artifacts(dist_dir, dist_name, version)
    try:
        files = validate_artifacts(artifacts, require_all=args.require_all)
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n错误: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\n找到 {len(files)} 个发行包:")
    for f in files:
        print(f"  ✓ {f.name}  ({format_size(f.stat().st_size)})")

    if args.dry_run:
        print("\n[dry-run] 未上传。")
        return

    ensure_twine()

    try:
        auth_source = ensure_upload_credentials(args.repository, args.token)
    except RuntimeError as exc:
        print(f"\n错误: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\nPyPI 认证: {auth_source}")

    if not args.skip_check:
        print("\nRunning twine check ...")
        run_twine_check(files)

    if not args.yes and not confirm_upload(files, args.repository, version):
        print("已取消。")
        return

    print(f"\nUploading to {args.repository} ...")
    run_twine_upload(
        files,
        repository=args.repository,
        token=args.token,
        skip_existing=args.skip_existing,
        auth_source=auth_source,
    )

    project_url = (
        f"https://test.pypi.org/project/{name}/"
        if args.repository == "testpypi"
        else f"https://pypi.org/project/{name}/"
    )
    print(f"\n✓ 上传完成。查看: {project_url}")


if __name__ == "__main__":
    main()
