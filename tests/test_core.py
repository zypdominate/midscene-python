"""
核心功能测试：使用真实 HTTP 通信，无 unittest.mock 依赖。

通过内存中的轻量 RPC stub 服务器模拟 Node.js 微服务，
所有 HTTP/JSON-RPC 交互均为真实网络调用。
"""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from midscene_android.agent import MidsceneAgent, MidsceneRPCError
from midscene_android.config import MidsceneConfig, _is_base64, _to_base64, _from_base64
from midscene_android.mixin import MidsceneMixin


# ─── 本地 RPC Stub 服务器 ─────────────────────────────────────────────────────

class StubRPCHandler(BaseHTTPRequestHandler):
    """
    内存中的轻量 RPC stub 服务器，模拟 Node.js JSON-RPC 2.0 微服务。

    每个测试通过 responses 字典自定义方法响应；
    requests_received 记录所有收到的请求，供断言使用。
    """

    responses: dict[str, Any] = {}
    requests_received: list[dict] = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        self.__class__.requests_received.append(body)

        method = body.get("method")
        result = self.__class__.responses.get(method, {"ok": True})

        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload.encode())

    def log_message(self, *args):
        pass


class ErrorRPCHandler(BaseHTTPRequestHandler):
    """
    总是返回 JSON-RPC error 的 stub 服务器。
    createSession 正常响应，其余方法均返回业务错误。
    """

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))

        if body["method"] == "createSession":
            payload = json.dumps({
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"sessionId": "err-session-001"},
            })
        else:
            payload = json.dumps({
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32000, "message": "Device disconnected"},
            })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload.encode())

    def log_message(self, *args):
        pass


class _NodeManagerStub:
    """
    最小化的 NodeServiceManager 替代品。
    仅暴露 port 属性，无需启动真实 Node.js 子进程。
    """

    def __init__(self, port: int) -> None:
        self.port = port


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def stub_rpc_server():
    """
    启动本地 stub RPC 服务器。
    返回 (port, StubRPCHandler 类)，测试结束后自动关闭。
    """
    StubRPCHandler.responses = {"createSession": {"sessionId": "test_session_001"}}
    StubRPCHandler.requests_received = []

    server = HTTPServer(("127.0.0.1", 0), StubRPCHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port, StubRPCHandler
    server.shutdown()


@pytest.fixture
def stub_node_manager(stub_rpc_server, monkeypatch):
    port, handler = stub_rpc_server
    nm = _NodeManagerStub(port)
    monkeypatch.setattr("midscene_android.agent.NodeServiceManager", lambda config: nm)
    monkeypatch.setenv("MIDSCENE_MODEL_BASE_URL", "http://test/v1")
    monkeypatch.setenv("MIDSCENE_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("MIDSCENE_MODEL_NAME", "test-model")
    return nm, handler


@pytest.fixture
def error_rpc_server():
    """启动总是返回业务错误的 RPC stub 服务器。"""
    server = HTTPServer(("127.0.0.1", 0), ErrorRPCHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


# ─── MidsceneConfig 测试 ──────────────────────────────────────────────────────

class TestMidsceneConfig:

    def test_plaintext_key_converted_to_base64(self):
        config = MidsceneConfig(
            base_url="https://example.com/v1",
            api_key="sk-plaintext-key",
            model_name="qwen-vl-max",
        )
        assert config._api_key_b64 != "sk-plaintext-key"
        assert _from_base64(config._api_key_b64) == "sk-plaintext-key"

    def test_base64_key_not_double_encoded(self):
        b64_key = base64.b64encode(b"sk-plaintext-key").decode()
        config = MidsceneConfig(
            base_url="https://example.com/v1",
            api_key=b64_key,
            model_name="qwen-vl-max",
        )
        assert config._api_key_b64 == b64_key

    def test_to_node_env_decodes_key(self):
        config = MidsceneConfig(
            base_url="https://example.com/v1",
            api_key="sk-my-key",
            model_name="qwen-vl-max",
            model_family="qwen",
        )
        env = config.to_node_env()
        assert env["MIDSCENE_MODEL_API_KEY"] == "sk-my-key"
        assert env["MIDSCENE_MODEL_BASE_URL"] == "https://example.com/v1"
        assert env["MIDSCENE_MODEL_NAME"] == "qwen-vl-max"
        assert env["MIDSCENE_MODEL_FAMILY"] == "qwen"

    def test_from_dict(self):
        config = MidsceneConfig.from_dict({
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "model_name": "gpt-4o",
            "model_family": "openai",
        })
        assert config.model_name == "gpt-4o"
        assert _from_base64(config._api_key_b64) == "sk-test"

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MIDSCENE_MODEL_BASE_URL", "https://env.example.com/v1")
        monkeypatch.setenv("MIDSCENE_MODEL_API_KEY", "sk-env-key")
        monkeypatch.setenv("MIDSCENE_MODEL_NAME", "env-model")
        monkeypatch.setenv("MIDSCENE_MODEL_FAMILY", "qwen")

        config = MidsceneConfig.from_env()
        assert config.base_url == "https://env.example.com/v1"
        assert config.model_name == "env-model"

    def test_from_env_missing_required(self, monkeypatch):
        monkeypatch.delenv("MIDSCENE_MODEL_BASE_URL", raising=False)
        monkeypatch.delenv("MIDSCENE_MODEL_API_KEY", raising=False)
        monkeypatch.delenv("MIDSCENE_MODEL_NAME", raising=False)
        with pytest.raises(EnvironmentError, match="Missing required"):
            MidsceneConfig.from_env()


class TestBase64Helpers:

    def test_is_base64_valid(self):
        assert _is_base64(base64.b64encode(b"hello").decode()) is True

    def test_is_base64_plaintext(self):
        assert _is_base64("sk-plaintext") is False

    def test_roundtrip(self):
        original = "sk-very-secret-key-12345"
        encoded = _to_base64(original)
        assert _from_base64(encoded) == original


# ─── MidsceneAgent 测试 ───────────────────────────────────────────────────────

class TestMidsceneAgent:

    def test_creates_session_on_init(self, stub_node_manager):
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")

        assert agent._session_id == "test_session_001"

        create_calls = [r for r in handler.requests_received if r["method"] == "createSession"]
        assert len(create_calls) == 1
        assert create_calls[0]["params"]["deviceId"] == "emulator-5554"

    def test_act_sends_correct_rpc(self, stub_node_manager):
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")
        agent.act("点击登录按钮")

        act_calls = [r for r in handler.requests_received if r["method"] == "aiAct"]
        assert len(act_calls) == 1
        assert act_calls[0]["params"]["prompt"] == "点击登录按钮"
        assert act_calls[0]["params"]["sessionId"] == "test_session_001"

    def test_tap_sends_correct_rpc(self, stub_node_manager):
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")
        agent.tap("确认按钮")

        tap_calls = [r for r in handler.requests_received if r["method"] == "aiTap"]
        assert len(tap_calls) == 1
        assert tap_calls[0]["params"]["locate"] == "确认按钮"
        assert tap_calls[0]["params"]["sessionId"] == "test_session_001"

    def test_input_sends_locate_and_text(self, stub_node_manager):
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")
        agent.input("用户名输入框", "testuser")

        input_calls = [r for r in handler.requests_received if r["method"] == "aiInput"]
        assert len(input_calls) == 1
        assert input_calls[0]["params"]["locate"] == "用户名输入框"
        assert input_calls[0]["params"]["text"] == "testuser"

    def test_scroll_sends_direction_and_locate(self, stub_node_manager):
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")
        agent.scroll("商品列表", direction="up", distance="large")

        scroll_calls = [r for r in handler.requests_received if r["method"] == "aiScroll"]
        assert len(scroll_calls) == 1
        params = scroll_calls[0]["params"]
        assert params["locate"] == "商品列表"
        assert params["direction"] == "up"
        assert params["distance"] == "large"

    def test_key_press_sends_key(self, stub_node_manager):
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")
        agent.key_press("Back")

        key_calls = [r for r in handler.requests_received if r["method"] == "aiKeyboardPress"]
        assert len(key_calls) == 1
        assert key_calls[0]["params"]["key"] == "Back"

    def test_assert_passes_when_node_returns_true(self, stub_node_manager):
        _, handler = stub_node_manager
        handler.responses["aiAssert"] = {"pass": True, "reason": None}
        agent = MidsceneAgent("emulator-5554")
        agent.assert_("页面显示欢迎信息")  # 不应抛出

    def test_assert_raises_assertion_error_when_fails(self, stub_node_manager):
        _, handler = stub_node_manager
        handler.responses["aiAssert"] = {"pass": False, "reason": "未找到欢迎信息"}
        agent = MidsceneAgent("emulator-5554")

        with pytest.raises(AssertionError) as exc_info:
            agent.assert_("页面显示欢迎信息")

        assert "页面显示欢迎信息" in str(exc_info.value)
        assert "未找到欢迎信息" in str(exc_info.value)

    def test_query_returns_data(self, stub_node_manager):
        _, handler = stub_node_manager
        handler.responses["aiQuery"] = {"data": {"username": "testuser", "level": 5}}
        agent = MidsceneAgent("emulator-5554")

        result = agent.query('{"username": string, "level": number}')
        assert result["username"] == "testuser"
        assert result["level"] == 5

    def test_destroy_sends_rpc_and_marks_closed(self, stub_node_manager):
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")
        agent.destroy()

        assert agent._session_id is None
        destroy_calls = [r for r in handler.requests_received if r["method"] == "destroySession"]
        assert len(destroy_calls) == 1

    def test_destroy_idempotent(self, stub_node_manager):
        """多次 destroy 不应抛出异常，也不应重复发送 RPC。"""
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")
        agent.destroy()
        agent.destroy()  # 第二次应静默跳过

        destroy_calls = [r for r in handler.requests_received if r["method"] == "destroySession"]
        assert len(destroy_calls) == 1

    def test_rpc_error_raises_midscene_rpc_error(self, error_rpc_server, monkeypatch):
        nm = _NodeManagerStub(error_rpc_server)
        monkeypatch.setattr("midscene_android.agent.NodeServiceManager", lambda config: nm)
        monkeypatch.setenv("MIDSCENE_MODEL_BASE_URL", "http://test/v1")
        monkeypatch.setenv("MIDSCENE_MODEL_API_KEY", "test-key")
        monkeypatch.setenv("MIDSCENE_MODEL_NAME", "test-model")
        agent = MidsceneAgent("emulator-5554")

        with pytest.raises(MidsceneRPCError, match="Device disconnected"):
            agent.act("点击按钮")

    def test_rpc_error_carries_error_code(self, error_rpc_server, monkeypatch):
        nm = _NodeManagerStub(error_rpc_server)
        monkeypatch.setattr("midscene_android.agent.NodeServiceManager", lambda config: nm)
        monkeypatch.setenv("MIDSCENE_MODEL_BASE_URL", "http://test/v1")
        monkeypatch.setenv("MIDSCENE_MODEL_API_KEY", "test-key")
        monkeypatch.setenv("MIDSCENE_MODEL_NAME", "test-model")
        agent = MidsceneAgent("emulator-5554")

        try:
            agent.act("点击按钮")
            pytest.fail("Expected MidsceneRPCError")
        except MidsceneRPCError as exc:
            assert exc.code == -32000

    def test_session_id_injected_in_all_rpc_calls(self, stub_node_manager):
        """确保每次 RPC 调用都自动附带 sessionId。"""
        _, handler = stub_node_manager
        agent = MidsceneAgent("emulator-5554")
        agent.tap("任意按钮")
        agent.act("任意操作")

        non_create = [
            r for r in handler.requests_received
            if r["method"] not in ("createSession",)
        ]
        for req in non_create:
            assert req["params"].get("sessionId") == "test_session_001", (
                f"sessionId missing in {req['method']}"
            )

# ─── MidsceneMixin 测试 ───────────────────────────────────────────────────────

class TestMidsceneMixin:

    def test_ai_property_raises_without_init(self):
        class BadDevice(MidsceneMixin):
            pass

        device = BadDevice()
        with pytest.raises(RuntimeError, match="init_midscene"):
            _ = device.ai

    def test_close_midscene_safe_when_not_initialized(self):
        class MyDevice(MidsceneMixin):
            def __init__(self):
                self.init_midscene("emulator-5554")

        device = MyDevice()
        device.close_midscene()  # 不应抛出

    def test_close_midscene_calls_agent_destroy(self, stub_node_manager):
        """close_midscene 应调用 agent.destroy() 并置空引用。"""
        _, handler = stub_node_manager

        class MyDevice(MidsceneMixin):
            def __init__(self):
                self.init_midscene("emulator-5554")

        device = MyDevice()
        agent = MidsceneAgent("emulator-5554")
        device._midscene_agent = agent

        device.close_midscene()

        assert agent._session_id is None
        assert device._midscene_agent is None

        destroy_calls = [r for r in handler.requests_received if r["method"] == "destroySession"]
        assert len(destroy_calls) == 1

    def test_close_midscene_idempotent(self, stub_node_manager):
        """多次 close_midscene 不应抛出异常。"""
        _, handler = stub_node_manager

        class MyDevice(MidsceneMixin):
            def __init__(self):
                self.init_midscene("emulator-5554")

        device = MyDevice()
        device._midscene_agent = MidsceneAgent("emulator-5554")

        device.close_midscene()
        device.close_midscene()

    def test_ai_caches_agent_instance(self, stub_node_manager):
        """多次访问 .ai 应返回同一个 agent 实例。"""
        class MyDevice(MidsceneMixin):
            def __init__(self):
                self.init_midscene("emulator-5554")

        device = MyDevice()
        agent = MidsceneAgent("emulator-5554")
        device._midscene_agent = agent

        assert device.ai is agent
        assert device.ai is agent