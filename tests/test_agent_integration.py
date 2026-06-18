"""
集成测试：NodeServiceManager + MidsceneAgent 真实场景

测试分三个层次，从内向外逐层覆盖：

  Level 1 - 缓存与版本管理（操作真实 ~/.midscene_android/node_service 目录）
    通过备份/还原缓存元数据，验证 _runtime.is_cache_stale / _invalidate_cache 等行为。

  Level 2 - Node 服务 + Agent 初始化（需要内置 Node 二进制，无需 Android 设备）
    真实启动 Node RPC 服务，验证 MidsceneAgent 的初始化路径和错误处理。
    createSession 在无设备时会返回 MidsceneRPCError，这属于预期行为。

  Level 3 - 完整 AI 操作（需要 Android 设备 + AI Key）
    设备 ID 通过 ADB 自动获取（需设置 MIDSCENE_* 环境变量）。
    使用 pytest.mark.device 标记，CI 中默认跳过，连接设备时手动运行。

运行方式：
  # Level 1 + 2（无需设备）
  pytest tests/test_agent_integration.py -v -s -k "not device"

  # Level 3（需要连接 Android 设备并配置 AI Key）
  pytest tests/test_agent_integration.py -v -s -m device
"""

import threading
import uuid

import pytest
import requests

from midscene_android import runtime, MidsceneNodeServiceError
from midscene_android.config import MidsceneConfig
from midscene_android.midscene_agent import MidsceneAgent
from midscene_android.node_service import NodeServiceManager

# ─── 标记定义 ─────────────────────────────────────────────────────────────────

device_mark = pytest.mark.device

# 缓存目录中会被 invalidate_cache 删除的元数据文件（不含 node_modules）
_CACHE_METADATA_FILES = (
    "service.js",
    "package.json",
    runtime.NPM_DONE_FLAG.name,
    runtime.VERSION_FILE.name,
)


def _reset_singleton() -> None:
    """在 teardown 中重置 NodeServiceManager 单例，避免测试间状态污染。"""
    mgr = NodeServiceManager._instance
    if mgr is not None:
        mgr._shutdown()
    NodeServiceManager._instance = None


def _require_connected_device_id(config: MidsceneConfig) -> str:
    mgr = NodeServiceManager(config)
    mgr.ensure_started()
    resp = requests.post(
        f"http://127.0.0.1:{mgr.port}/rpc",
        json={
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "getConnectedDevices",
            "params": {},
        },
        timeout=60,
    )
    devices = _extract_connected_devices(resp.json())
    device_id = _pick_ready_device_id(devices)
    if not device_id:
        pytest.skip("No Android device connected via ADB")
    return device_id


def _extract_connected_devices(body: dict) -> list[dict]:
    if "error" in body:
        raise RuntimeError(
            body["error"].get("message", "getConnectedDevices RPC failed")
        )
    return body.get("result", {}).get("devices", [])


def _pick_ready_device_id(devices: list[dict]) -> str | None:
    ready = [d for d in devices if d.get("state") == "device"] or devices
    if not ready or not ready[0].get("udid"):
        return None
    return ready[0]["udid"]


@pytest.fixture
def node_cache_snapshot():
    """
    备份真实 node_service 缓存中的元数据文件，测试结束后还原。

    仅备份 service.js / package.json / flag / version，不备份 node_modules。
    """
    runtime.NODE_SVC_CACHE.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, bytes | None] = {}
    for name in _CACHE_METADATA_FILES:
        path = runtime.NODE_SVC_CACHE / name
        snapshot[name] = path.read_bytes() if path.is_file() else None

    yield snapshot

    for name, content in snapshot.items():
        path = runtime.NODE_SVC_CACHE / name
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(content)


@pytest.fixture(scope="module")
def node_service():
    """
    Module 级别的 NodeServiceManager fixture。

    整个模块共享同一个 Node 子进程，避免重复的冷启动开销。
    模块测试结束后自动关闭子进程。
    """
    _reset_singleton()
    config = MidsceneConfig.from_env()
    mgr = NodeServiceManager(config)
    mgr.ensure_started()
    yield mgr
    _reset_singleton()


# ─── Level 1：缓存与版本管理（真实缓存目录）──────────────────────────────────


class TestVersionCache:
    """
    在真实 ~/.midscene_android/node_service 目录上验证缓存失效逻辑。
    每个测试通过 node_cache_snapshot fixture 在结束后还原缓存状态。
    """

    def test_get_current_version_returns_string(self):
        """get_current_version 应始终返回非空字符串。"""
        ver = runtime.get_current_version()
        assert isinstance(ver, str)
        assert len(ver) > 0
        print(f"\n  Current package version: {ver}")

    def test_cache_fresh_after_ensure_node_service(self, node_cache_snapshot):
        """npm install 完成后，缓存版本应与当前包一致，视为新鲜。"""
        runtime.ensure_node_service(runtime.get_node_bin())
        assert runtime.NPM_DONE_FLAG.exists(), "npm install should create done flag"
        assert runtime.VERSION_FILE.exists(), "npm install should write version file"
        assert (
                runtime.VERSION_FILE.read_text(encoding="utf-8").strip()
                == runtime.get_current_version()
        )
        assert runtime.is_cache_stale() is False

    def test_cache_stale_when_install_flag_missing(self, node_cache_snapshot):
        """done flag 不存在时，缓存应被视为过期。"""
        runtime.NPM_DONE_FLAG.unlink(missing_ok=True)
        assert runtime.is_cache_stale() is True

    def test_cache_stale_when_version_file_missing(self, node_cache_snapshot):
        """done flag 存在但 version file 不存在（旧版缓存），应被视为过期。"""
        runtime.NPM_DONE_FLAG.touch()
        runtime.VERSION_FILE.unlink(missing_ok=True)
        assert runtime.is_cache_stale() is True

    def test_cache_stale_when_version_mismatch(self, node_cache_snapshot):
        """缓存版本与当前包版本不一致时，应被视为过期。"""
        runtime.NPM_DONE_FLAG.touch()
        runtime.VERSION_FILE.write_text("0.0.1", encoding="utf-8")
        assert runtime.is_cache_stale() is True

    def test_invalidate_cache_removes_metadata_files(self, node_cache_snapshot):
        """invalidate_cache 应删除 service.js / package.json / flag / version。"""
        runtime.NODE_SVC_CACHE.mkdir(parents=True, exist_ok=True)
        (runtime.NODE_SVC_CACHE / "service.js").write_text("// temp", encoding="utf-8")
        (runtime.NODE_SVC_CACHE / "package.json").write_text("{}", encoding="utf-8")
        runtime.NPM_DONE_FLAG.touch()
        runtime.VERSION_FILE.write_text("0.1.0", encoding="utf-8")

        runtime.invalidate_cache()

        for name in _CACHE_METADATA_FILES:
            assert not (runtime.NODE_SVC_CACHE / name).exists(), (
                f"{name} should be removed"
            )

    def test_invalidate_cache_preserves_node_modules(self, node_cache_snapshot):
        """invalidate_cache 必须保留 node_modules/，以便快速重装。"""
        runtime.ensure_node_service(runtime.get_node_bin())
        nm = runtime.NODE_SVC_CACHE / "node_modules"
        assert nm.is_dir(), "node_modules must exist before invalidation test"

        runtime.invalidate_cache()

        assert nm.is_dir(), "node_modules should be preserved after cache invalidation"


# ─── Level 2：Node 服务 + Agent 初始化（无 Android 设备）────────────────────


class TestNodeServiceManagerLifecycle:
    """
    验证 NodeServiceManager 的完整生命周期。
    需要内置 Node 二进制已就绪（_runtime/ 目录已填充）。
    """

    def setup_method(self):
        _reset_singleton()

    def teardown_method(self):
        _reset_singleton()

    def test_port_before_start_raises_node_service_error(self):
        """访问 .port 必须在 ensure_started() 之前抛出 MidsceneNodeServiceError。"""
        config = MidsceneConfig.from_env()
        mgr = NodeServiceManager(config)
        with pytest.raises(MidsceneNodeServiceError, match="not started"):
            _ = mgr.port

    def test_ensure_started_assigns_valid_port(self):
        """ensure_started() 成功后，port 应是一个合法端口号。"""
        config = MidsceneConfig.from_env()
        mgr = NodeServiceManager(config)
        mgr.ensure_started()

        assert isinstance(mgr.port, int)
        assert 1024 <= mgr.port <= 65535
        print(f"\n  Node service listening on port: {mgr.port}")

    def test_singleton_returns_same_instance(self):
        """同一 Python 进程内多次构造应返回同一实例。"""
        config = MidsceneConfig.from_env()
        mgr1 = NodeServiceManager(config)
        mgr2 = NodeServiceManager(config)
        assert mgr1 is mgr2, "NodeServiceManager must be a singleton"

    def test_ensure_started_idempotent(self):
        """多次调用 ensure_started() 不应启动多个进程，端口保持不变。"""
        config = MidsceneConfig.from_env()
        mgr = NodeServiceManager(config)
        mgr.ensure_started()
        port_first = mgr.port

        mgr.ensure_started()
        port_second = mgr.port

        assert port_first == port_second

    def test_ensure_started_thread_safe(self):
        """并发调用 ensure_started() 不应导致多进程或竞态条件。"""
        config = MidsceneConfig.from_env()
        mgr = NodeServiceManager(config)
        errors: list[Exception] = []

        def _start_worker():
            try:
                mgr.ensure_started()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_start_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert not errors, f"Concurrent ensure_started raised: {errors}"
        assert 1024 <= mgr.port <= 65535

    def test_service_process_is_running_after_start(self):
        """ensure_started() 后，内部 Popen 进程应处于运行状态。"""
        config = MidsceneConfig.from_env()
        mgr = NodeServiceManager(config)
        mgr.ensure_started()

        assert mgr._proc is not None
        assert mgr._proc.poll() is None, "Node process should still be running"

    def test_shutdown_clears_port_and_instance(self):
        """_shutdown() 后，_port 应清零，单例应被清除。"""
        config = MidsceneConfig.from_env()
        mgr = NodeServiceManager(config)
        mgr.ensure_started()

        mgr._shutdown()

        assert mgr._port is None
        assert NodeServiceManager._instance is None


class TestNodeServiceRPC:
    """
    通过真实 HTTP 请求验证 Node RPC 服务行为。
    使用 module 级 node_service fixture，仅启动一次进程。
    """

    def test_ping_returns_pong(self, node_service):
        """ping 是最基本的健康检查，不需要设备或 AI Key。"""
        resp = requests.post(
            f"http://127.0.0.1:{node_service.port}/rpc",
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
        assert "pid" in data["result"]
        print(f"\n  ping → pong, Node pid={data['result']['pid']}")

    def test_unknown_method_returns_rpc_error(self, node_service):
        """调用未定义方法应返回 JSON-RPC -32601 错误，而非 HTTP 4xx/5xx。"""
        resp = requests.post(
            f"http://127.0.0.1:{node_service.port}/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "test-unknown",
                "method": "nonExistentMethod",
                "params": {},
            },
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32601
        print(f"\n  Unknown method error: {data['error']['message']}")

    def test_invalid_json_returns_400(self, node_service):
        """发送非 JSON 请求体应返回 HTTP 400。"""
        resp = requests.post(
            f"http://127.0.0.1:{node_service.port}/rpc",
            data=b"not-json",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_get_request_returns_404(self, node_service):
        """RPC 端点只接受 POST，GET 应返回 404。"""
        resp = requests.get(
            f"http://127.0.0.1:{node_service.port}/rpc",
            timeout=10,
        )
        assert resp.status_code == 404

    def test_concurrent_pings_all_succeed(self, node_service):
        """并发 RPC 请求应全部正常返回，不出现竞态。"""
        results: list[bool] = []
        errors: list[Exception] = []

        def _do_ping():
            try:
                resp = requests.post(
                    f"http://127.0.0.1:{node_service.port}/rpc",
                    json={
                        "jsonrpc": "2.0",
                        "id": str(uuid.uuid4()),
                        "method": "ping",
                        "params": {},
                    },
                    timeout=10,
                )
                results.append(resp.json()["result"]["pong"] is True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_do_ping) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Concurrent pings raised: {errors}"
        assert all(results), "All concurrent pings should succeed"
        print("\n  10 concurrent pings: all OK")


class TestMidsceneAgentInit:
    """Level 2：MidsceneAgent 仅需 device_id，配置来自环境变量。"""

    """
    验证 MidsceneAgent 的初始化路径与 Node 服务的交互。

    createSession 需要真实 Android 设备；在无设备的 CI 环境中，
    预期行为是 Node 侧返回错误，Python 侧将其包装为 MidsceneRPCError。
    这正是我们要验证的错误传播链路。
    """

    def test_agent_node_manager_port_used(self, node_service):
        """
        验证 MidsceneAgent 确实向 NodeServiceManager 提供的端口发送请求。
        通过观察 RPC 请求是否到达正确端口（间接验证：ping 可达即证明端口正确）。
        """
        port = node_service.port
        resp = requests.post(
            f"http://127.0.0.1:{port}/rpc",
            json={"jsonrpc": "2.0", "id": "port-check", "method": "ping", "params": {}},
            timeout=5,
        )
        assert resp.status_code == 200
        print(f"\n  Agent will use port {port}, verified reachable")

    def test_destroy_nonexistent_session_is_graceful(self, node_service):
        """
        destroySession 传入不存在的 sessionId 应正常返回，不抛出异常。
        这覆盖了 agent.destroy() 在异常状态下的健壮性。
        """
        resp = requests.post(
            f"http://127.0.0.1:{node_service.port}/rpc",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "destroySession",
                "params": {"sessionId": "ghost-session-does-not-exist"},
            },
            timeout=10,
        )
        data = resp.json()
        assert "result" in data, f"Unexpected error: {data}"
        assert data["result"]["ok"] is True
        print("\n  destroySession with unknown sessionId → ok (graceful)")


# ─── Level 3：完整 AI 操作（需要真实 Android 设备 + AI Key）────────────────


@pytest.fixture(scope="module")
def real_agent():
    """
    完整初始化流程：
      1. NodeServiceManager 启动 Node 子进程
      2. MidsceneAgent 创建 Android session
    模块内所有 device 测试共享同一个 session。
    """
    _reset_singleton()

    ai_config = MidsceneConfig.from_env()
    device_id = _require_connected_device_id(ai_config)
    agent = MidsceneAgent(device_id)
    print(f"\n  Using Android device: {agent._device_id}")
    print(f"  Session created: {agent._session_id}")

    yield agent

    agent.destroy()
    _reset_singleton()


@device_mark
class TestAIActionsOnRealDevice:
    """
    在真实 Android 设备上验证所有 AI 操作接口。

    运行方式（需 ADB 已连接设备，多设备时可设 ANDROID_DEVICE_ID）：
      MIDSCENE_MODEL_BASE_URL=... \\
      MIDSCENE_MODEL_API_KEY=...  \\
      MIDSCENE_MODEL_NAME=...     \\
      pytest tests/test_agent_integration.py -m device -v -s
    """

    def test_session_created_successfully(self, real_agent):
        """会话创建成功，sessionId 应为非空字符串。"""
        assert real_agent._session_id
        assert isinstance(real_agent._session_id, str)
        assert real_agent.is_closed() is False
        print(f"\n  Session ID: {real_agent._session_id}")

    def test_ping_via_agent_rpc(self, real_agent):
        """通过 agent._rpc 调用 ping，验证 RPC 通道正常。"""
        result = real_agent._rpc("ping")
        assert result["pong"] is True
        print(f"\n  Ping via agent._rpc OK, Node pid={result.get('pid')}")

    def test_act_auto_planning(self, real_agent):
        """
        aiAct：AI 自动规划并执行。
        目标描述：等待设备处于稳定状态（不要求特定 App，兼容所有设备）。
        """
        real_agent.ai_action("等待当前页面完全加载，不要做任何操作")

    def test_tap_element(self, real_agent):
        """
        aiTap：AI 定位并点击屏幕上的元素。
        """
        real_agent.ai_tap("屏幕中央区域")

    def test_assert_screen_visible(self, real_agent):
        """
        aiAssert：AI 视觉断言。
        验证设备屏幕当前是可见的（通用断言，适用于任何设备状态）。
        """
        real_agent.ai_assert("设备屏幕已亮起，可以看到 UI 内容")

    def test_assert_fails_with_wrong_condition(self, real_agent):
        """
        aiAssert 失败时应抛出 AssertionError，而非 MidsceneRPCError。
        验证 Python 侧正确区分了"AI 返回 pass=False"与"RPC 调用失败"。
        """
        with pytest.raises(AssertionError) as exc_info:
            real_agent.ai_assert("屏幕上有一只独角兽在飞翔")
        assert "AI assertion failed" in str(exc_info.value)
        print(f"\n  Expected assertion failure: {exc_info.value}")

    def test_query_extracts_structured_data(self, real_agent):
        """
        aiQuery：从当前屏幕提取结构化数据。
        schema 描述期望的数据结构，AI 返回 JSON。
        """
        result = real_agent.ai_query(
            '"当前屏幕上可见的主要文字内容，如果没有则返回空字符串"'
        )
        assert isinstance(result, str), f"Expected str from ai_query, got {type(result)}: {result!r}"
        print(f"\n  Query result: {result!r}")

    def test_scroll_down(self, real_agent):
        """aiScroll：向下滚动当前页面。"""
        real_agent.ai_scroll(direction="down", scroll_type='singleAction')
        real_agent.ai_scroll(direction="up", scroll_type='singleAction')
        real_agent.ai_scroll(scroll_type='ScrollToBottom')

    def test_wait_for_condition(self, real_agent):
        """
        aiWaitFor：等待条件满足。
        等待屏幕稳定（最多 5 秒），这在大多数设备上应该立即成立。
        """
        real_agent.ai_wait_for("屏幕 UI 处于稳定状态，没有加载动画", timeout_ms=5000)

    def test_session_lifecycle_create_and_destroy(self):
        """
        完整的会话生命周期：创建 → 使用 → 销毁。
        这个测试独立创建自己的 session，验证完整的 init/destroy 流程。
        """
        ai_config = MidsceneConfig.from_env()
        device_id = _require_connected_device_id(ai_config)
        agent = MidsceneAgent(device_id)
        session_id = agent._session_id

        assert session_id is not None
        assert agent.is_closed() is False

        agent._rpc("ping")

        agent.destroy()

        assert agent.is_closed() is True
        assert agent._session_id is None
        print(f"\n  Session {session_id} created and destroyed successfully")
