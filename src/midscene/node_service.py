"""
Node.js 服务管理（平台无关）

职责：
1. 按 :class:`ServiceSpec` 启动/维护 Node.js 微服务，每个 spec（android / web）
   对应一个独立的 Node 子进程（各自的 node_modules）。
2. Python 进程退出时通过 atexit 自动关闭 Node 子进程。

首次使用时，用缓存 Node 二进制 + 缓存 npm 在该 spec 的缓存目录执行 npm install
   （Node/npm 首次自动下载到 ~/.midscene/node_runtime/；
    @midscene/* 安装到 ~/.midscene/<name>/node_service/）。

核心原则：
  所有 Node 相关子进程（npm install、Node 微服务本身）都必须使用内置的 Node 二进制，
  不依赖系统 PATH 中的 node。
"""

from __future__ import annotations

import atexit
import subprocess
import threading
import time
import uuid
from typing import Any

import requests

from . import runtime
from .config import MidsceneConfig
from .exceptions import MidsceneNodeServiceError, MidsceneRPCError
from .runtime import ServiceSpec


class NodeServiceManager:
    """
    Node.js 微服务管理器，按 :class:`ServiceSpec` 名称键控的进程级注册表。

    - 每个 spec（如 android / web）在进程内只启动一个 Node 子进程
    - 同一 spec 下多个 Agent 通过 sessionId 共享该进程
    - Python 退出时由 atexit 自动关闭所有子进程
    """

    _instances: dict[str, NodeServiceManager] = {}
    _registry_lock = threading.Lock()

    # ── 注册表接口 ───────────────────────────────────────────────────────────────

    @classmethod
    def get(cls, spec: ServiceSpec, config: MidsceneConfig) -> NodeServiceManager:
        """返回该 spec 对应的管理器（不存在则创建）。

        注意：仅 **首个** 调用的 ``config`` 生效。后续不同 config 会被忽略，
        因为 Node 进程（含 API Key 等环境变量）已在运行。需要更换配置请重启进程。
        """
        with cls._registry_lock:
            inst = cls._instances.get(spec.name)
            if inst is None:
                inst = cls(spec, config)
                cls._instances[spec.name] = inst
            return inst

    @classmethod
    def reset(cls, name: str) -> None:
        """关闭并移除指定 spec 的管理器（主要用于测试隔离）。"""
        with cls._registry_lock:
            inst = cls._instances.get(name)
        if inst is not None:
            inst._shutdown()

    @classmethod
    def reset_all(cls) -> None:
        """关闭并移除所有管理器。"""
        with cls._registry_lock:
            instances = list(cls._instances.values())
        for inst in instances:
            inst._shutdown()

    def __init__(self, spec: ServiceSpec, config: MidsceneConfig) -> None:
        self._spec = spec
        self._config = config
        self._proc: subprocess.Popen | None = None
        self._port: int | None = None
        self._start_lock = threading.Lock()
        atexit.register(self._shutdown)

    # ── 公开接口 ────────────────────────────────────────────────────────────────

    @property
    def spec(self) -> ServiceSpec:
        return self._spec

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
                f"Node service ({self._spec.name}) appears down during {method!r}; "
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

    # ── 内部实现 ────────────────────────────────────────────────────────────────

    def _is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        node_bin = runtime.get_node_bin()
        runtime.ensure_node_service(self._spec, node_bin)

        cache_dir = self._spec.cache_dir
        service_js = cache_dir / "service.js"

        # PATH 置顶 + AI 模型配置 + Node 运行时配置，全部不依赖系统 node
        env = runtime.make_node_env(
            node_bin,
            extra={
                **self._config.to_node_env(),
                "PORT": "0",  # OS 分配空闲端口，避免冲突
                "NODE_PATH": str(cache_dir / "node_modules"),
            },
        )

        runtime.logger.debug("Spawning Node service: %s %s", node_bin.name, service_js)
        self._proc = subprocess.Popen(
            [str(node_bin), str(service_js)],
            cwd=str(cache_dir),
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
            "Midscene Node service (%s) ready  port=%d  pid=%d  node=%s",
            self._spec.name, self._port, self._proc.pid, node_bin.name,
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
        with NodeServiceManager._registry_lock:
            if NodeServiceManager._instances.get(self._spec.name) is self:
                del NodeServiceManager._instances[self._spec.name]
