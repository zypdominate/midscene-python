"""
测试层级 1：Node 服务启动 + RPC ping
- 不需要 Android 设备
- 不需要 AI Key（ping 不调用 AI）
- 首次运行需联网：自动下载 Node/npm 到 ~/.midscene/node_runtime/

运行：
  pytest tests/test_node_service.py -v -s
"""

import time
import uuid
from pathlib import Path

import requests

from midscene import MidsceneConfig, node_bootstrap, runtime
from midscene.agent_android import ANDROID_SERVICE_SPEC
from midscene.node_service import NodeServiceManager


# ── Helpers ────────────────────────────────────────────────────────────────────


def get_node_service(config: MidsceneConfig) -> NodeServiceManager:
    return NodeServiceManager.get(ANDROID_SERVICE_SPEC, config)


def _reset_singleton():
    """每个测试前重置 Android Node 服务实例，避免状态污染。"""
    NodeServiceManager.reset(ANDROID_SERVICE_SPEC.name)


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestNodeBinary:
    """验证缓存中的 Node 二进制可用，且不依赖系统 node。"""

    def test_node_bin_exists(self):
        path = runtime.get_node_bin()
        assert path.exists(), f"Node binary not found: {path}"
        print(f"\n  Node binary : {path}")
        print(f"  Size        : {path.stat().st_size // 1024 // 1024} MB")

    def test_node_bin_is_cached_not_system(self):
        """Node 路径必须在 ~/.midscene/node_runtime/bin 下。"""
        import shutil

        cached = runtime.get_node_bin()
        assert cached.parent.resolve() == node_bootstrap.NODE_RUNTIME_BIN.resolve()

        system_node = shutil.which("node")
        if system_node:
            assert str(cached.resolve()) != Path(system_node).resolve(), (
                f"Cached node resolves to system node: {system_node}"
            )
        print(f"\n  Cached node  : {cached}")
        print(f"  System node  : {system_node or '(not found - good)'}")

    def test_node_bin_executable(self):
        import subprocess

        node = runtime.get_node_bin()
        result = subprocess.run(
            [str(node), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"node --version failed: {result.stderr}"
        version = result.stdout.strip()
        print(f"\n  Node version: {version}")
        assert version.startswith("v"), f"Unexpected version output: {version}"

    def test_node_env_prepends_bundled_dir(self):
        """make_node_env 必须把 Node 缓存目录放在 PATH 最前面。"""
        import platform as _platform

        node_bin = runtime.get_node_bin()
        env = runtime.make_node_env(node_bin)
        sep = ";" if _platform.system().lower() == "windows" else ":"
        first_path = env["PATH"].split(sep)[0]

        assert first_path == str(node_bin.parent), (
            f"Expected cached node dir first in PATH.\n"
            f"  Expected : {node_bin.parent}\n"
            f"  Got      : {first_path}"
        )
        print(f"\n  PATH[0]: {first_path}  ✓")


class TestNpmInstall:
    """验证 npm install 能正常执行（首次或已有缓存）。"""

    def test_npm_cli_exists(self):
        path = runtime.get_npm_cli()
        assert path.exists(), f"npm-cli.js not found: {path}"
        print(f"\n  npm-cli.js: {path}")

    def test_ensure_node_service_idempotent(self):
        """多次调用 runtime.ensure_node_service 应该幂等（第二次直接跳过）。"""
        node_bin = runtime.get_node_bin()
        t0 = time.monotonic()
        runtime.ensure_node_service(ANDROID_SERVICE_SPEC, node_bin)
        elapsed_first = time.monotonic() - t0

        t1 = time.monotonic()
        runtime.ensure_node_service(ANDROID_SERVICE_SPEC, node_bin)
        elapsed_second = time.monotonic() - t1

        assert elapsed_second < 1.0, (
            f"Second call should be instant (cached), but took {elapsed_second:.2f}s"
        )
        print(f"\n  First call:  {elapsed_first:.1f}s")
        print(f"  Second call: {elapsed_second:.3f}s (cached)")

    def test_node_service_files_exist_after_install(self):
        """npm install 完成后，node_modules/@midscene/android 应存在。"""
        node_bin = runtime.get_node_bin()
        runtime.ensure_node_service(ANDROID_SERVICE_SPEC, node_bin)

        midscene_pkg = ANDROID_SERVICE_SPEC.cache_dir / "node_modules" / "@midscene" / "android"
        assert midscene_pkg.exists(), (
            f"@midscene/android not found after npm install: {midscene_pkg}"
        )
        print(f"\n  @midscene/android: {midscene_pkg}  ✓")


class TestNodeServiceStartup:
    """验证 Node RPC 服务能正常启动并响应 ping。"""

    def setup_method(self):
        _reset_singleton()

    def teardown_method(self):
        _reset_singleton()

    def test_service_starts_and_pings(self, fixture_dummy_config):
        mgr = get_node_service(fixture_dummy_config)
        mgr.ensure_started()

        assert mgr.port > 0, "Service port should be > 0"
        print(f"\n  Node service port: {mgr.port}")

        resp = requests.post(
            f"http://127.0.0.1:{mgr.port}/rpc",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "ping",
                "params": {},
            },
            timeout=10,
        )
        data = resp.json()

        assert "result" in data, f"Unexpected response: {data}"
        assert data["result"]["pong"] is True
        print(f"  ping response: {data['result']}")

    def test_service_singleton(self, fixture_dummy_config):
        """同一 Python 进程内两次 ensure_started 应返回同一端口。"""
        config = fixture_dummy_config
        mgr1 = get_node_service(config)
        mgr1.ensure_started()
        port1 = mgr1.port

        mgr2 = get_node_service(config)
        mgr2.ensure_started()
        port2 = mgr2.port

        assert port1 == port2, "Singleton should return same port"
        assert mgr1 is mgr2, "Should be same instance"
        print(f"\n  Singleton port: {port1}")

    def test_service_survives_multiple_rpc_calls(self, fixture_dummy_config):
        """连续发送多次 ping，服务应保持稳定。"""
        config = fixture_dummy_config
        mgr = get_node_service(config)
        mgr.ensure_started()

        for _ in range(5):
            resp = requests.post(
                f"http://127.0.0.1:{mgr.port}/rpc",
                json={
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "ping",
                    "params": {},
                },
                timeout=10,
            )
            data = resp.json()
            assert data["result"]["pong"] is True

        print(f"\n  5x ping OK on port {mgr.port}")
