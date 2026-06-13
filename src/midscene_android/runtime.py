import hashlib
import logging
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path

from .exceptions import MidsceneSetupError

logger = logging.getLogger(__name__)

# ─── 路径常量 ──────────────────────────────────────────────────────────────────

PACKAGE_DIR = Path(__file__).parent
NODE_BIN_DIR = PACKAGE_DIR / "_node_driver" / "bin"
NPM_CLI = PACKAGE_DIR / "_node_driver" / "npm" / "bin" / "npm-cli.js"
NODE_SVC_SRC = PACKAGE_DIR / "_node_driver" / "src"  # package.json + service.js

CACHE_DIR = Path.home() / ".midscene_android"
NODE_SVC_CACHE = CACHE_DIR / "node_service"  # npm install 目标目录
NPM_DONE_FLAG = NODE_SVC_CACHE / ".npm_install_done"
VERSION_FILE = NODE_SVC_CACHE / ".package_version"  # 缓存版本戳，用于失效检测

NPM_INSTALL_TIMEOUT = 300  # 秒

# 随 wheel 分发的 Node 服务源码（package.json 变更需重新 npm install）
SERVICE_SOURCE_FILES = ("package.json", "service.js")
PACKAGE_JSON_HASH_FILE = NODE_SVC_CACHE / ".package_json.sha256"


# ─── 平台检测 ──────────────────────────────────────────────────────────────────

def get_node_bin() -> Path:
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

    path = NODE_BIN_DIR / name
    if not path.exists():
        raise MidsceneSetupError(
            f"Bundled Node binary not found: {path}\n"
            f"Run: python tools/fetch_node_binaries.py"
        )

    if system != "windows":
        # 确保二进制文件在非 Windows 系统下具有可执行权限
        # （防止 pip install 或解压 tar 包时丢失 +x 权限）
        if not os.access(path, os.X_OK):
            try:
                path.chmod(0o755)
                logger.debug("Added executable permission to %s", path)
            except OSError as e:
                logger.warning("Failed to add executable permission to %s: %s", path, e)

    return path


def get_npm_cli() -> Path:
    """返回内置 npm-cli.js 路径，不存在时给出明确提示。"""
    if not NPM_CLI.exists():
        raise MidsceneSetupError(
            f"Bundled npm-cli.js not found: {NPM_CLI}\n"
            f"Run: python tools/fetch_node_binaries.py"
        )
    return NPM_CLI


# ─── 环境变量构造 ──────────────────────────────────────────────────────────────

def make_node_env(node_bin: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
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


def ensure_node_shim(node_bin: Path) -> None:
    """
    在内置 Node bin 目录创建裸名称的 shim，
    使 npm 内部 fork 调用 "node"（无后缀/无平台名）时能正确找到内置二进制。

    Windows：node.cmd + node.exe（cmd.exe 生命周期脚本优先找 node.exe）
    Linux/macOS：node 符号链接
    """
    system = platform.system().lower()
    bin_dir = node_bin.parent

    if system == "windows":
        shim = bin_dir / "node.cmd"
        expected_shim = f'@echo off\n"{node_bin.resolve()}" %*\n'
        if not shim.exists() or shim.read_text(encoding="utf-8") != expected_shim:
            shim.write_text(expected_shim, encoding="utf-8")
            logger.debug("Created/updated node.cmd shim: %s", shim)

        node_exe = bin_dir / "node.exe"
        if not node_exe.exists() or node_exe.stat().st_size != node_bin.stat().st_size:
            shutil.copy2(node_bin, node_exe)
            logger.debug("Created/updated node.exe copy: %s", node_exe)
    else:
        symlink = bin_dir / "node"
        if symlink.is_symlink():
            if symlink.resolve() != node_bin.resolve():
                symlink.unlink()
                symlink.symlink_to(node_bin.name)
                logger.debug("Updated node symlink: %s → %s", symlink, node_bin.name)
        elif not symlink.exists():
            symlink.symlink_to(node_bin.name)
            logger.debug("Created node symlink: %s → %s", symlink, node_bin.name)


# ─── npm install ───────────────────────────────────────────────────────────────

def get_current_version() -> str:
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


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundled_package_json_hash() -> str:
    return _sha256_file(NODE_SVC_SRC / "package.json")


def is_bundled_source_newer_than_cache() -> bool:
    """检查 _node_driver/src 中的 package.json / service.js 是否与缓存不一致。"""
    for name in SERVICE_SOURCE_FILES:
        src = NODE_SVC_SRC / name
        dst = NODE_SVC_CACHE / name
        if not src.is_file():
            raise MidsceneSetupError(
                f"Missing bundled Node service source: {src}\n"
                f"Run: python tools/fetch_node_binaries.py"
            )
        if not dst.is_file():
            return True
        if src.read_bytes() != dst.read_bytes():
            return True
    return False


def _package_json_changed_since_install() -> bool:
    """package.json 相对上次 npm install 是否有变化。"""
    current = _bundled_package_json_hash()
    if not PACKAGE_JSON_HASH_FILE.exists():
        return True
    return PACKAGE_JSON_HASH_FILE.read_text(encoding="utf-8").strip() != current


def is_cache_stale() -> bool:
    """
    检查缓存是否需要刷新。

    当以下任一条件成立时认为缓存已过期：
    - npm 安装 flag 不存在（从未安装）
    - 版本文件不存在（旧版缓存，无版本记录）
    - 版本文件中记录的版本与当前包版本不一致（pip upgrade 后）
    - 内置 package.json 相对上次 install 有变化
    """
    if not NPM_DONE_FLAG.exists():
        return True
    if not VERSION_FILE.exists():
        return True
    if _package_json_changed_since_install():
        return True
    try:
        cached_ver = VERSION_FILE.read_text(encoding="utf-8").strip()
        return cached_ver != get_current_version()
    except OSError:
        return True


def sync_node_service_sources() -> None:
    """将 _node_driver/src 源码同步到缓存目录（不触发 npm install）。"""
    NODE_SVC_CACHE.mkdir(parents=True, exist_ok=True)
    for name in SERVICE_SOURCE_FILES:
        src = NODE_SVC_SRC / name
        dst = NODE_SVC_CACHE / name
        shutil.copy2(src, dst)
        logger.debug("Synced %s → %s", src.name, dst)


def sync_node_service_sources_if_needed() -> bool:
    """
    若 bundled 源码比缓存新或内容不同，则同步。

    Returns:
        True 表示发生了同步。
    """
    if not is_bundled_source_newer_than_cache():
        return False
    sync_node_service_sources()
    return True


def invalidate_cache() -> None:
    """
    清除缓存中的 Node 服务文件（保留 node_modules 以加速重装）。

    删除：service.js、package.json、done flag、version file、package.json hash。
    保留：node_modules/（npm install 速度快很多）。
    """
    for name in (
        "service.js",
        "package.json",
        NPM_DONE_FLAG.name,
        VERSION_FILE.name,
        PACKAGE_JSON_HASH_FILE.name,
    ):
        target = NODE_SVC_CACHE / name
        try:
            target.unlink(missing_ok=True)
            logger.debug("Cache invalidated: removed %s", name)
        except OSError as e:
            logger.warning("Failed to remove cache file %s: %s", name, e)


def ensure_node_service(node_bin: Path) -> None:
    """
    确保 Node 服务依赖已安装到缓存目录，并与当前包版本一致。

    - 每次运行先检查 bundled package.json / service.js 是否最新并同步
    - 首次运行：执行完整的 npm install
    - pip upgrade 或 package.json 变更后：重新 npm install
    - 无变化：跳过 install
    """
    ensure_node_shim(node_bin)
    sync_node_service_sources_if_needed()

    if not is_cache_stale():
        logger.debug(
            "Node service cache is up-to-date (v%s), skipping install. cache=%s",
            get_current_version(),
            NODE_SVC_CACHE,
        )
        return

    current_version = get_current_version()
    invalidate_cache()
    sync_node_service_sources()

    print_banner(
        "Setting up @midscene/android Node service",
        f"Package version : {current_version}",
        f"Target          : {NODE_SVC_CACHE}",
        f"Node            : {node_bin}",
        "This may take a few minutes (requires npm registry access).",
    )

    # 内置 Node + 内置 npm（_node_driver/npm），PATH 置顶确保不走系统 node/npm
    npm_cli = get_npm_cli()
    cmd = [str(node_bin), str(npm_cli), "install", "--omit=dev"]
    env = make_node_env(node_bin)

    logger.debug("npm install: %s", " ".join(cmd))

    run_subprocess(
        cmd,
        cwd=NODE_SVC_CACHE,
        timeout=NPM_INSTALL_TIMEOUT,
        error_prefix="npm install failed",
        env=env,
    )

    NPM_DONE_FLAG.touch()
    VERSION_FILE.write_text(current_version, encoding="utf-8")
    PACKAGE_JSON_HASH_FILE.write_text(_bundled_package_json_hash(), encoding="utf-8")
    print(f"[midscene-android] npm install completed (v{current_version}).", flush=True)


def run_subprocess(
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
        raise MidsceneSetupError(f"{error_prefix}: timed out after {timeout}s")

    t.join(timeout=5)

    if proc.returncode != 0:
        tail = "\n".join(lines[-30:])
        raise MidsceneSetupError(f"{error_prefix} (exit={proc.returncode}):\n{tail}")


def print_banner(*lines: str) -> None:
    sep = "=" * 60
    print(f"\n{sep}", flush=True)
    for line in lines:
        print(f"[midscene-android] {line}", flush=True)
    print(f"{sep}\n", flush=True)