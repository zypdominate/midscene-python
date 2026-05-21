import logging
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── 路径常量 ──────────────────────────────────────────────────────────────────

_PACKAGE_DIR = Path(__file__).parent
_NODE_BIN_DIR = _PACKAGE_DIR / "_runtime" / "bin"
_NPM_CLI = _PACKAGE_DIR / "_runtime" / "npm" / "bin" / "npm-cli.js"
_NODE_SVC_SRC = _PACKAGE_DIR / "_node_service"  # package.json + service.js

_CACHE_DIR = Path.home() / ".midscene_android"
_NODE_SVC_CACHE = _CACHE_DIR / "node_service"  # npm install 目标目录
_NPM_DONE_FLAG = _NODE_SVC_CACHE / ".npm_install_done"
_VERSION_FILE = _NODE_SVC_CACHE / ".package_version"  # 缓存版本戳，用于失效检测

_NPM_INSTALL_TIMEOUT = 300  # 秒


# ─── 平台检测 ──────────────────────────────────────────────────────────────────

def _get_node_bin() -> Path:
    """返回内置 Node 可执行文件的绝对路径。"""
    system = platform.system().lower()  # windows / darwin / linux
    machine = platform.machine().lower()  # x86_64 / aarch64 / arm64

    arch = "arm64" if machine in ("aarch64", "arm64") else "x64"

    if system == "windows":
        name = "node-win32-x64.exe"
    elif system == "darwin":
        name = f"node-darwin-{arch}"
    else:
        name = f"node-linux-{arch}"

    path = _NODE_BIN_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Bundled Node binary not found: {path}\n"
            f"Run: python scripts/fetch_node_binaries.py"
        )
    return path


def _get_npm_cli() -> Path:
    """返回内置 npm-cli.js 路径，不存在时给出明确提示。"""
    if not _NPM_CLI.exists():
        raise FileNotFoundError(
            f"Bundled npm-cli.js not found: {_NPM_CLI}\n"
            f"Run: python scripts/fetch_node_binaries.py"
        )
    return _NPM_CLI


# ─── 环境变量构造 ──────────────────────────────────────────────────────────────

def _make_node_env(node_bin: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """
    构造子进程环境变量，确保所有层级都使用内置 Node，不依赖系统 node。

    关键：把内置 Node bin 目录置顶 PATH。
    npm install 期间 npm 自己会 fork 子进程并调用 "node"，
    置顶 PATH 后这些 fork 出的子进程也会优先找到内置 Node，
    而不是系统 PATH 里的任何其他 node。
    """
    node_dir = str(node_bin.parent)
    old_path = os.environ.get("PATH", "")
    sep = ";" if platform.system().lower() == "windows" else ":"
    new_path = node_dir + sep + old_path

    env: dict[str, str] = {**os.environ, "PATH": new_path}
    if extra:
        env.update(extra)
    return env


def _ensure_node_shim(node_bin: Path) -> None:
    """
    在内置 Node bin 目录创建裸名称的 shim，
    使 npm 内部 fork 调用 "node"（无后缀/无平台名）时能正确找到内置二进制。

    Windows：创建 node.cmd（批处理跳板）
    Linux/macOS：创建 node 符号链接
    """
    system = platform.system().lower()

    if system == "windows":
        shim = node_bin.parent / "node.cmd"
        if not shim.exists():
            # %* 转发所有参数
            shim.write_text(
                f'@echo off\n"{node_bin}" %*\n',
                encoding="utf-8",
            )
            logger.debug("Created node.cmd shim: %s", shim)
    else:
        symlink = node_bin.parent / "node"
        if not symlink.exists():
            symlink.symlink_to(node_bin.name)
            logger.debug("Created node symlink: %s → %s", symlink, node_bin.name)


# ─── npm install ───────────────────────────────────────────────────────────────

def _get_current_version() -> str:
    """返回当前已安装的 Python 包版本号。"""
    try:
        from importlib.metadata import version
        return version("midscene-android")
    except Exception:
        # 开发模式下 importlib.metadata 可能找不到包，回退到读 __version__
        try:
            from midscene_android import __version__
            return __version__
        except Exception:
            return "unknown"


def _is_cache_stale() -> bool:
    """
    检查缓存是否需要刷新。

    当以下任一条件成立时认为缓存已过期：
    - npm 安装 flag 不存在（从未安装）
    - 版本文件不存在（旧版缓存，无版本记录）
    - 版本文件中记录的版本与当前包版本不一致（pip upgrade 后）
    """
    if not _NPM_DONE_FLAG.exists():
        return True
    if not _VERSION_FILE.exists():
        return True
    try:
        cached_ver = _VERSION_FILE.read_text(encoding="utf-8").strip()
        return cached_ver != _get_current_version()
    except OSError:
        return True


def _invalidate_cache() -> None:
    """
    清除缓存中的 Node 服务文件（保留 node_modules 以加速重装）。

    删除：service.js、package.json、done flag、version file。
    保留：node_modules/（npm install 速度快很多）。
    """
    for name in ("service.js", "package.json", _NPM_DONE_FLAG.name, _VERSION_FILE.name):
        target = _NODE_SVC_CACHE / name
        try:
            target.unlink(missing_ok=True)
            logger.debug("Cache invalidated: removed %s", name)
        except OSError as e:
            logger.warning("Failed to remove cache file %s: %s", name, e)


def _ensure_node_service(node_bin: Path) -> None:
    """
    确保 Node 服务依赖已安装到缓存目录，并与当前包版本一致。

    - 首次运行：执行完整的 npm install
    - pip upgrade 后：检测到版本变化，重新复制源码并重新 npm install
    - 无变化：跳过，直接返回
    """
    if not _is_cache_stale():
        logger.debug(
            "Node service cache is up-to-date (v%s), skipping install. cache=%s",
            _get_current_version(),
            _NODE_SVC_CACHE,
        )
        return

    current_version = _get_current_version()
    _invalidate_cache()

    _print_banner(
        "Setting up @midscene/android Node service",
        f"Package version : {current_version}",
        f"Target          : {_NODE_SVC_CACHE}",
        f"Node            : {node_bin}",
        "This may take a few minutes (requires npm registry access).",
    )

    # shim：让 npm install 期间内部 fork 也走内置 Node
    _ensure_node_shim(node_bin)

    # 将 Node 服务源码同步到缓存目录（package.json + service.js）
    _NODE_SVC_CACHE.mkdir(parents=True, exist_ok=True)
    for src in _NODE_SVC_SRC.iterdir():
        dst = _NODE_SVC_CACHE / src.name
        shutil.copy2(src, dst)
        logger.debug("Synced %s → %s", src.name, dst)

    # 用内置 Node 执行内置 npm-cli.js，PATH 置顶确保全链路不走系统 node
    npm_cli = _get_npm_cli()
    cmd = [str(node_bin), str(npm_cli), "install", "--production"]
    env = _make_node_env(node_bin)

    logger.debug("npm install: %s", " ".join(cmd))

    _run_subprocess(
        cmd,
        cwd=_NODE_SVC_CACHE,
        timeout=_NPM_INSTALL_TIMEOUT,
        error_prefix="npm install failed",
        env=env,
    )

    _NPM_DONE_FLAG.touch()
    _VERSION_FILE.write_text(current_version, encoding="utf-8")
    print(f"[midscene-android] npm install completed (v{current_version}).", flush=True)


def _run_subprocess(
        cmd: list[str],
        cwd: Path,
        timeout: int,
        error_prefix: str,
        env: dict[str, str] | None = None,
) -> None:
    """执行子进程，实时回显输出，超时/失败时抛异常。"""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,  # None 表示继承当前进程环境（内部调用不传 env 时）
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    lines: list[str] = []

    def _reader():
        for raw in proc.stdout:
            line = raw.rstrip()
            lines.append(line)
            logger.debug("[subprocess] %s", line)
            print(line, flush=True)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"{error_prefix}: timed out after {timeout}s")

    t.join(timeout=5)

    if proc.returncode != 0:
        tail = "\n".join(lines[-30:])
        raise RuntimeError(f"{error_prefix} (exit={proc.returncode}):\n{tail}")


def _print_banner(*lines: str) -> None:
    sep = "=" * 60
    print(f"\n{sep}", flush=True)
    for line in lines:
        print(f"[midscene-android] {line}", flush=True)
    print(f"{sep}\n", flush=True)
