"""
测试层级 1：Node 服务启动 + RPC ping
- 不需要 Android 设备
- 不需要 AI Key（ping 不调用 AI）
- 需要内置 Node 二进制 + 内置 npm（即 _runtime/ 已填充）

运行：
  pytest tests/test_node_service.py -v -s
"""

import sys
import time
import uuid
from pathlib import Path

import requests

from midscene_android.service import NodeServiceManager

# 确保从项目根导入，而非已安装的包
sys.path.insert(0, str(Path(__file__).parent.parent))

from midscene_android._runtime import (
    _get_node_bin,
    _ensure_node_service,
    _NODE_SVC_CACHE,
)
from midscene_android.config import MidsceneConfig


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_dummy_config() -> MidsceneConfig:
    """Node 服务本身启动不需要真实 AI Key，用占位值即可。"""
    return MidsceneConfig(
        base_url="https://placeholder.example.com/v1",
        api_key="dummy-key-for-node-service-test",
        model_name="placeholder-model",
        model_family="openai",
    )


def _reset_singleton():
    """每个测试前重置单例，避免状态污染。"""
    mgr = NodeServiceManager._instance
    if mgr:
        mgr._shutdown()
    NodeServiceManager._instance = None


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestNodeBinary:
    """验证内置 Node 二进制可用，且不依赖系统 node。"""

    def test_node_bin_exists(self):
        path = _get_node_bin()
        assert path.exists(), f"Node binary not found: {path}"
        print(f"\n  Node binary : {path}")
        print(f"  Size        : {path.stat().st_size // 1024 // 1024} MB")

    def test_node_bin_is_bundled_not_system(self):
        """内置 Node 路径必须在本库 _runtime/bin/ 下，不能是系统 node。"""
        import shutil
        bundled = _get_node_bin()
        system_node = shutil.which("node")

        # 内置路径必须包含 _runtime/bin
        assert "_runtime" in str(bundled), (
            f"Node binary is not from _runtime/bin: {bundled}"
        )
        if system_node:
            assert str(bundled) != system_node, (
                f"Bundled node resolves to system node: {system_node}"
            )
        print(f"\n  Bundled node : {bundled}")
        print(f"  System node  : {system_node or '(not found - good)'}")

    def test_node_bin_executable(self):
        import subprocess
        node = _get_node_bin()
        result = subprocess.run(
            [str(node), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"node --version failed: {result.stderr}"
        version = result.stdout.strip()
        print(f"\n  Node version: {version}")
        assert version.startswith("v"), f"Unexpected version output: {version}"

    def test_node_env_prepends_bundled_dir(self):
        """_make_node_env 必须把内置 Node 目录放在 PATH 最前面。"""
        from midscene_android._runtime import _make_node_env
        import platform as _platform

        node_bin = _get_node_bin()
        env = _make_node_env(node_bin)
        sep = ";" if _platform.system().lower() == "windows" else ":"
        first_path = env["PATH"].split(sep)[0]

        assert first_path == str(node_bin.parent), (
            f"Expected bundled node dir first in PATH.\n"
            f"  Expected : {node_bin.parent}\n"
            f"  Got      : {first_path}"
        )
        print(f"\n  PATH[0]: {first_path}  ✓")


class TestNpmInstall:
    """验证 npm install 能正常执行（首次或已有缓存）。"""

    def test_npm_cli_exists(self):
        from midscene_android._runtime import _get_npm_cli
        path = _get_npm_cli()
        assert path.exists(), f"npm-cli.js not found: {path}"
        print(f"\n  npm-cli.js: {path}")

    def test_ensure_node_service_idempotent(self):
        """多次调用 _ensure_node_service 应该幂等（第二次直接跳过）。"""
        node_bin = _get_node_bin()
        # 第一次（若已有 flag 直接跳过；若无则真正安装）
        t0 = time.monotonic()
        _ensure_node_service(node_bin)
        elapsed_first = time.monotonic() - t0

        # 第二次必须立即返回（<1s）
        t1 = time.monotonic()
        _ensure_node_service(node_bin)
        elapsed_second = time.monotonic() - t1

        assert elapsed_second < 1.0, (
            f"Second call should be instant (cached), but took {elapsed_second:.2f}s"
        )
        print(f"\n  First call:  {elapsed_first:.1f}s")
        print(f"  Second call: {elapsed_second:.3f}s (cached)")

    def test_node_service_files_exist_after_install(self):
        """npm install 完成后，node_modules/@midscene/android 应存在。"""
        node_bin = _get_node_bin()
        _ensure_node_service(node_bin)

        midscene_pkg = _NODE_SVC_CACHE / "node_modules" / "@midscene" / "android"
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

    def test_service_starts_and_pings(self):
        config = _make_dummy_config()
        mgr = NodeServiceManager(config)
        mgr.ensure_started()

        assert mgr.port > 0, "Service port should be > 0"
        print(f"\n  Node service port: {mgr.port}")

        # 发送 ping RPC，验证服务响应
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

    def test_service_singleton(self):
        """同一 Python 进程内两次 ensure_started 应返回同一端口。"""
        config = _make_dummy_config()
        mgr1 = NodeServiceManager(config)
        mgr1.ensure_started()
        port1 = mgr1.port

        mgr2 = NodeServiceManager(config)
        mgr2.ensure_started()
        port2 = mgr2.port

        assert port1 == port2, "Singleton should return same port"
        assert mgr1 is mgr2, "Should be same instance"
        print(f"\n  Singleton port: {port1}")

    def test_service_survives_multiple_rpc_calls(self):
        """连续发送多次 ping，服务应保持稳定。"""
        config = _make_dummy_config()
        mgr = NodeServiceManager(config)
        mgr.ensure_started()

        for i in range(5):
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
