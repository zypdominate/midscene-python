"""
Node.js 服务进程管理。

职责：
1. 首次使用时，用内置 Node 二进制执行 npm install（缓存到 ~/.midscene_android/）
2. 以进程级单例模式启动/维护 Node.js 微服务
3. Python 进程退出时通过 atexit 自动关闭 Node 子进程
"""

from __future__ import annotations

import atexit
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .config import MidsceneConfig

logger = logging.getLogger(__name__)

# ─── 路径常量 ──────────────────────────────────────────────────────────────────

# 库内 _runtime/bin/ 目录（开发者预置 Node 二进制的位置）
_PACKAGE_DIR = Path(__file__).parent
_NODE_BIN_DIR = _PACKAGE_DIR / "_runtime" / "bin"

# Node.js 服务源码目录（随包分发）
_NODE_SERVICE_SRC = _PACKAGE_DIR / "_node_service"

# 用户缓存目录（npm install 的目标位置）
_CACHE_DIR = Path.home() / ".midscene_android"
_NODE_SERVICE_CACHE = _CACHE_DIR / "node_service"
_NPM_DONE_FLAG = _NODE_SERVICE_CACHE / ".npm_install_done"

# npm install 超时（秒）
_NPM_INSTALL_TIMEOUT = 300


# ─── 平台检测 ──────────────────────────────────────────────────────────────────

def _get_node_bin_path() -> Path:
    """
    返回库内置的 Node 可执行文件路径。

    命名规范（与 scripts/fetch_node_binaries.py 保持一致）：
      node-linux-x64
      node-linux-arm64
      node-darwin-x64
      node-darwin-arm64
      node-win32-x64.exe
    """
    system = platform.system().lower()   # 'linux' | 'darwin' | 'windows'
    machine = platform.machine().lower() # 'x86_64' | 'aarch64' | 'arm64' | ...

    # 统一 arch 标识
    if machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = "x64"

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
            f"If you are a developer, run: python scripts/fetch_node_binaries.py"
        )
    return path


def _get_npm_path(node_bin: Path) -> Path:
    """
    返回与内置 Node 配套的 npm 脚本路径。
    Node.js 发行版中 npm 位于 node 同级目录（解压后的 bin/ 下），
    但我们只捆绑了 node 可执行文件本身，因此通过 node 执行内置 npm module。
    node 自带 npm，可以用 `node <path_to_npm_cli.js>` 调用。
    """
    # Node 发行版自带 npm，路径为 <node_dir>/lib/node_modules/npm/bin/npm-cli.js
    # 由于我们只打包了单个 node 可执行文件，npm 通过 node 内置模块调用
    # 这里返回一个哨兵值，实际在 _run_npm_install 中特殊处理
    return node_bin  # 占位，实际通过 `node -e "require('npm')"` 方式调用


# ─── npm install ───────────────────────────────────────────────────────────────

def _ensure_node_service(node_bin: Path) -> None:
    """
    确保 Node.js 服务依赖已安装到缓存目录。
    首次调用时执行 npm install，后续通过 flag 文件跳过。
    """
    if _NPM_DONE_FLAG.exists():
        logger.debug("npm install already done, skipping. (%s)", _NODE_SERVICE_CACHE)
        return

    logger.info(
        "First time setup: installing @midscene/android via npm...\n"
        "This may take a few minutes and requires internet access to npm registry.\n"
        "Installation path: %s",
        _NODE_SERVICE_CACHE,
    )

    # 将 Node 服务源码复制到缓存目录（package.json + service.js）
    _NODE_SERVICE_CACHE.mkdir(parents=True, exist_ok=True)
    for src_file in _NODE_SERVICE_SRC.iterdir():
        dst = _NODE_SERVICE_CACHE / src_file.name
        if not dst.exists():
            shutil.copy2(src_file, dst)

    # 用内置 Node 执行 npm install
    # Node.js 自带 corepack/npm，通过 `node --version` 确认可用
    # npm 的 CLI 入口在 node 内置模块路径中，用以下方式调用：
    #   <node_bin> <npm_cli_path> install --production
    # 实际上更简单：直接用 node 执行 npm（Node 18+ 自带 npm）

    # 找到内置 npm：Node 发行包解压后 bin/npm 在同目录，但我们只拷贝了 node 本体。
    # 解决方案：先检测系统 npm，若无则通过 node 执行 npx 拉取 npm。
    # 最稳健的方案：打包时同时把 npm-cli.js 也放进来。
    # 这里实现为：优先用内置 npm_cli.js（开发者打包时放置），fallback 到系统 npm。
    npm_cli = _PACKAGE_DIR / "_runtime" / "npm" / "npm-cli.js"
    if npm_cli.exists():
        npm_cmd = [str(node_bin), str(npm_cli), "install", "--production", "--prefer-offline"]
    else:
        # fallback：使用系统 npm（不推荐，违背设计原则，仅作开发期兜底）
        system_npm = shutil.which("npm")
        if not system_npm:
            raise RuntimeError(
                "npm-cli.js not found in bundled runtime and system npm is not available.\n"
                "Please run: python scripts/fetch_node_binaries.py\n"
                "to bundle npm-cli.js into the package."
            )
        logger.warning(
            "Bundled npm-cli.js not found, falling back to system npm: %s", system_npm
        )
        npm_cmd = [system_npm, "install", "--production"]

    _run_subprocess(
        npm_cmd,
        cwd=_NODE_SERVICE_CACHE,
        timeout=_NPM_INSTALL_TIMEOUT,
        error_prefix="npm install failed",
    )

    # 写入完成标记
    _NPM_DONE_FLAG.touch()
    logger.info("npm install completed successfully.")


def _run_subprocess(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    error_prefix: str,
) -> None:
    """执行子进程，实时打印输出，超时或失败时抛出异常。"""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines: list[str] = []
    assert proc.stdout is not None

    def _reader():
        for line in proc.stdout:
            line = line.rstrip()
            output_lines.append(line)
            logger.debug("[npm] %s", line)
            # 同时打印到 stderr 让用户看到进度（仅首次安装时）
            print(line, file=sys.stderr)

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"{error_prefix}: timed out after {timeout}s")

    reader_thread.join(timeout=5)

    if proc.returncode != 0:
        tail = "\n".join(output_lines[-30:])
        raise RuntimeError(f"{error_prefix} (exit code {proc.returncode}):\n{tail}")


# ─── 进程级单例 ────────────────────────────────────────────────────────────────

class NodeServiceManager:
    """
    Node.js 微服务的进程级单例管理器。

    - 整个 Python 进程内只启动一个 Node 子进程
    - 多个 MidsceneAgent 实例共享同一个 Node 服务（通过 sessionId 隔离）
    - Python 进程退出时通过 atexit 自动终止 Node 子进程
    """

    _instance: Optional["NodeServiceManager"] = None
    _lock = threading.Lock()

    def __new__(cls, config: MidsceneConfig) -> "NodeServiceManager":
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
            return cls._instance

    def __init__(self, config: MidsceneConfig) -> None:
        # __new__ 保证单例，__init__ 可能被多次调用，用 flag 防止重复初始化
        if self._initialized:
            return
        self._config = config
        self._proc: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._start_lock = threading.Lock()
        self._initialized = True
        atexit.register(self._shutdown)

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("NodeServiceManager not started yet")
        return self._port

    def ensure_started(self) -> None:
        """确保 Node 服务已启动，幂等，线程安全。"""
        if self._proc is not None and self._proc.poll() is None:
            return  # 已在运行
        with self._start_lock:
            # double-check
            if self._proc is not None and self._proc.poll() is None:
                return
            self._start()

    def _start(self) -> None:
        node_bin = _get_node_bin_path()
        # 确保依赖已安装
        _ensure_node_service(node_bin)

        service_js = _NODE_SERVICE_CACHE / "service.js"
        env = {
            **os.environ,
            **self._config.to_node_env(),
            "PORT": "0",  # 让 OS 分配空闲端口，避免冲突
            "NODE_PATH": str(_NODE_SERVICE_CACHE / "node_modules"),
        }

        logger.debug("Starting Node service: %s %s", node_bin, service_js)
        self._proc = subprocess.Popen(
            [str(node_bin), str(service_js)],
            cwd=str(_NODE_SERVICE_CACHE),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        self._port = self._wait_for_ready()
        # 启动 stderr 日志线程（持续消费，避免管道阻塞）
        threading.Thread(target=self._log_stderr, daemon=True).start()
        logger.info("Midscene Node service started on port %d (pid=%d)", self._port, self._proc.pid)

    def _wait_for_ready(self, timeout: float = 30.0) -> int:
        """
        等待 Node 服务输出就绪信号，解析实际监听端口。
        Node 侧输出格式：MIDSCENE_SERVICE_READY:{port}
        """
        assert self._proc is not None
        assert self._proc.stdout is not None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                stderr_output = self._proc.stderr.read() if self._proc.stderr else ""
                raise RuntimeError(
                    f"Node service exited unexpectedly (code={self._proc.returncode}).\n"
                    f"stderr: {stderr_output}"
                )
            line = self._proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            line = line.strip()
            logger.debug("[node stdout] %s", line)
            if line.startswith("MIDSCENE_SERVICE_READY:"):
                port = int(line.split(":", 1)[1])
                return port

        raise RuntimeError(
            f"Midscene Node service did not become ready within {timeout}s"
        )

    def _log_stderr(self) -> None:
        """持续消费 Node 子进程的 stderr，避免管道满导致阻塞。"""
        assert self._proc is not None
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            logger.debug("[node stderr] %s", line.rstrip())

    def _shutdown(self) -> None:
        """Python 进程退出时调用，优雅终止 Node 子进程。"""
        if self._proc and self._proc.poll() is None:
            logger.debug("Shutting down Midscene Node service (pid=%d)...", self._proc.pid)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._port = None
        # 重置单例，允许在同一进程中重新初始化（主要用于测试）
        NodeServiceManager._instance = None