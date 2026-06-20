"""
Node.js 服务

职责：
1. 以进程级单例模式启动/维护 Node.js 微服务
2. Python 进程退出时通过 atexit 自动关闭 Node 子进程

首次使用时，用缓存 Node 二进制 + 缓存 npm 执行 npm install
   （Node/npm 首次自动下载到 ~/.midscene_android/node_runtime/；
    @midscene/android 安装到 ~/.midscene_android/node_service/）

核心原则：
  所有 Node 相关子进程（npm install、Node 微服务本身）都必须使用内置的 Node 二进制，不依赖系统 PATH 中的 node。
  确保 npm install 期间 npm 内部 fork 的子进程也走内置 Node。

"""
import atexit
import subprocess
import threading
import time
import uuid
from typing import Any, Optional

import requests

from . import runtime
from .config import MidsceneConfig
from .exceptions import MidsceneNodeServiceError, MidsceneRPCError

# ─── 进程级单例 ────────────────────────────────────────────────────────────────

class NodeServiceManager:
    """
    Node.js 微服务的进程级单例。

    - 整个 Python 进程内只启动一个 Node 子进程
    - 多个 MidsceneAgent 通过 sessionId 共享该进程
    - Python 退出时由 atexit 自动关闭子进程
    - 启动 Node 微服务时同样用内置 Node，PATH 置顶保证一致性
    """

    _instance: Optional["NodeServiceManager"] = None
    _lock = threading.Lock()

    def __new__(cls, config: MidsceneConfig):
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
            return cls._instance

    def __init__(self, config: MidsceneConfig) -> None:
        """Initialize the singleton Node service manager.

        Note: Only the **first** call's ``config`` takes effect. Subsequent
        calls with a different config are silently ignored because the Node
        process (and its environment variables, including API keys) is already
        running. If you need a different config, restart the Python process.
        """
        if self._initialized:
            return
        self._config = config
        self._proc: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._start_lock = threading.Lock()
        self._initialized = True
        atexit.register(self._shutdown)

    # ── 公开接口 ────────────────────────────────────────────────────────────────

    @property
    def port(self) -> int:
        if self._port is None:
            raise MidsceneNodeServiceError("NodeServiceManager not started yet")
        return self._port

    def ensure_started(self) -> None:
        """启动 Node 服务，幂等，线程安全。"""
        if self._is_running():
            return
        with self._start_lock:
            if self._is_running():
                return
            self._start()

    def rpc(self, method: str, timeout: int = 10, **params: Any) -> dict[str, Any]:
        """通用 RPC 调用方法。

        - JSON-RPC 业务错误包装为 ``MidsceneRPCError``。
        - 传输层错误包装为 ``MidsceneNodeServiceError``，不再裸泄露 requests 异常。
        - Node 进程崩溃（连接被拒）时自动重启一次并重试。注意：重启后旧
          session 已失效，对有状态调用会得到清晰的 "Session not found" 业务错误。
        """
        try:
            return self._do_rpc(method, timeout, **params)
        except requests.ConnectionError as exc:
            if self._is_running():
                msg = f"Failed to reach Node service for method {method!r}: {exc}"
                raise MidsceneNodeServiceError(msg) from exc
            warn_msg = (
                f"Node service appears down during {method!r}; "
                "restarting and retrying once."
            )
            runtime.logger.warning(warn_msg)
            self.ensure_started()
            try:
                return self._do_rpc(method, timeout, **params)
            except requests.RequestException as exc2:
                msg = f"Node service unavailable after restart for method {method!r}: {exc2}"
                raise MidsceneNodeServiceError(msg) from exc2
        except requests.RequestException as exc:
            msg = f"RPC transport error for method {method!r}: {exc}"
            raise MidsceneNodeServiceError(msg) from exc

    def _do_rpc(self, method: str, timeout: int, **params: Any) -> dict[str, Any]:
        resp = requests.post(
            f"http://127.0.0.1:{self.port}/rpc",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": method,
                "params": params,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            err = body["error"]
            raise MidsceneRPCError(
                err.get("message", "RPC error"),
                err.get("code", -1),
                err.get("stack"),
            )
        return body.get("result", {})

    def get_connected_devices(self) -> list[dict[str, str]]:
        """获取当前已连接的 Android 设备列表。"""
        self.ensure_started()
        result = self.rpc("getConnectedDevices")
        return result.get("devices", [])

    # ── 内部实现 ────────────────────────────────────────────────────────────────

    def _is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        node_bin = runtime.get_node_bin()
        runtime.ensure_node_service(node_bin)

        service_js = runtime.NODE_SVC_CACHE / "service.js"

        # PATH 置顶 + AI 模型配置 + Node 运行时配置，全部不依赖系统 node
        env = runtime.make_node_env(
            node_bin,
            extra={
                **self._config.to_node_env(),
                "PORT": "0",  # OS 分配空闲端口，避免冲突
                "NODE_PATH": str(runtime.NODE_SVC_CACHE / "node_modules"),
            },
        )

        runtime.logger.debug("Spawning Node service: %s %s", node_bin.name, service_js)
        self._proc = subprocess.Popen(
            [str(node_bin), str(service_js)],
            cwd=str(runtime.NODE_SVC_CACHE),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        self._port = self._wait_ready()
        # service.js 的 console.log 会持续写 stdout；必须 drain，否则管道写满会阻塞 Node。
        threading.Thread(target=self._drain_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        runtime.logger.info(
            "Midscene Node service ready  port=%d  pid=%d  node=%s",
            self._port, self._proc.pid, node_bin.name,
        )

    def _wait_ready(self, timeout: float = 30.0) -> int:
        """
        读取 stdout 直到看到就绪信号行：
          MIDSCENE_SERVICE_READY:{port}
        """
        assert self._proc and self._proc.stdout
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                stderr = self._proc.stderr.read() if self._proc.stderr else ""
                raise MidsceneNodeServiceError(
                    f"Node service exited unexpectedly "
                    f"(code={self._proc.returncode}).\nstderr:\n{stderr}"
                )
            line = self._proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            line = line.strip()
            runtime.logger.debug("[node] %s", line)
            if line.startswith("MIDSCENE_SERVICE_READY:"):
                return int(line.split(":", 1)[1])

        raise MidsceneNodeServiceError(
            f"Midscene Node service did not become ready within {timeout}s"
        )

    def _drain_stdout(self) -> None:
        """持续消费 stdout，防止管道满阻塞子进程（_wait_ready 之后 service.js 仍会写 stdout）。"""
        proc = self._proc
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                runtime.logger.debug("[node] %s", line.rstrip())
        except (ValueError, OSError):
            # 进程关闭后管道被关闭，迭代可能抛错，忽略即可。
            pass

    def _drain_stderr(self) -> None:
        """持续消费 stderr，防止管道满阻塞子进程。"""
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            for line in proc.stderr:
                runtime.logger.debug("[node stderr] %s", line.rstrip())
        except (ValueError, OSError):
            pass

    def _shutdown(self) -> None:
        if self._proc and self._proc.poll() is None:
            runtime.logger.debug("Terminating Node service pid=%d", self._proc.pid)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._port = None
        NodeServiceManager._instance = None
