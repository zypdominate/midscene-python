"""
单元测试：不依赖真实设备和 Node.js 服务。
通过 mock 覆盖核心模块的关键路径。
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from midscene_android.config import MidsceneConfig, _is_base64, _to_base64, _from_base64
from midscene_android.agent import MidsceneAgent, MidsceneRPCError
from midscene_android.mixin import MidsceneMixin
from midscene_android.exceptions import MidsceneError


# ─── 测试工具：内存 RPC 服务器 ────────────────────────────────────────────────

class MockRPCHandler(BaseHTTPRequestHandler):
    """轻量级 mock RPC 服务器，用于测试 MidsceneAgent 的网络交互。"""

    # 每个测试可以覆盖此字典来自定义响应
    responses: dict[str, Any] = {}
    requests_received: list[dict] = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        self.__class__.requests_received.append(body)

        method = body.get("method")
        result = self.__class__.responses.get(method, {"ok": True})

        response = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response.encode())

    def log_message(self, *args): pass  # 静默


@pytest.fixture
def mock_rpc_server():
    """启动 mock RPC 服务器，返回 (port, handler_class)。"""
    MockRPCHandler.responses = {}
    MockRPCHandler.requests_received = []
    # 注入 createSession 的默认响应
    MockRPCHandler.responses["createSession"] = {"sessionId": "test_session_001"}

    server = HTTPServer(("127.0.0.1", 0), MockRPCHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port, MockRPCHandler
    server.shutdown()


@pytest.fixture
def mock_node_manager(mock_rpc_server):
    """返回一个指向 mock RPC 服务器的 NodeServiceManager 替代品。"""
    port, handler = mock_rpc_server
    manager = MagicMock()
    manager.port = port
    return manager, handler


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
        # 应该识别为已是 base64，不再二次编码
        assert config._api_key_b64 == b64_key

    def test_to_node_env_decodes_key(self):
        config = MidsceneConfig(
            base_url="https://example.com/v1",
            api_key="sk-my-key",
            model_name="qwen-vl-max",
            model_family="qwen",
        )
        env = config.to_node_env()
        assert env["MIDSCENE_MODEL_API_KEY"] == "sk-my-key"  # 解码为明文
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

    def test_creates_session_on_init(self, mock_node_manager):
        manager, handler = mock_node_manager
        agent = MidsceneAgent("emulator-5554", manager)
        assert agent._session_id == "test_session_001"

        # 验证 createSession 被调用，且传入了正确的 deviceId
        create_calls = [r for r in handler.requests_received if r["method"] == "createSession"]
        assert len(create_calls) == 1
        assert create_calls[0]["params"]["deviceId"] == "emulator-5554"

    def test_act_sends_correct_rpc(self, mock_node_manager):
        manager, handler = mock_node_manager
        agent = MidsceneAgent("emulator-5554", manager)
        agent.act("点击登录按钮")

        act_calls = [r for r in handler.requests_received if r["method"] == "aiAct"]
        assert len(act_calls) == 1
        assert act_calls[0]["params"]["prompt"] == "点击登录按钮"
        assert act_calls[0]["params"]["sessionId"] == "test_session_001"

    def test_tap_sends_correct_rpc(self, mock_node_manager):
        manager, handler = mock_node_manager
        agent = MidsceneAgent("emulator-5554", manager)
        agent.tap("确认按钮")

        tap_calls = [r for r in handler.requests_received if r["method"] == "aiTap"]
        assert tap_calls[0]["params"]["locate"] == "确认按钮"

    def test_assert_passes_when_node_returns_true(self, mock_node_manager):
        manager, handler = mock_node_manager
        handler.responses["aiAssert"] = {"pass": True, "reason": None}
        agent = MidsceneAgent("emulator-5554", manager)
        agent.assert_("页面显示欢迎信息")  # 不应抛出

    def test_assert_raises_assertion_error_when_fails(self, mock_node_manager):
        manager, handler = mock_node_manager
        handler.responses["aiAssert"] = {"pass": False, "reason": "未找到欢迎信息"}
        agent = MidsceneAgent("emulator-5554", manager)

        with pytest.raises(AssertionError) as exc_info:
            agent.assert_("页面显示欢迎信息")
        assert "页面显示欢迎信息" in str(exc_info.value)
        assert "未找到欢迎信息" in str(exc_info.value)

    def test_query_returns_data(self, mock_node_manager):
        manager, handler = mock_node_manager
        handler.responses["aiQuery"] = {"data": {"username": "testuser", "level": 5}}
        agent = MidsceneAgent("emulator-5554", manager)

        result = agent.query('{"username": string, "level": number}')
        assert result["username"] == "testuser"
        assert result["level"] == 5

    def test_destroy_sends_rpc_and_marks_closed(self, mock_node_manager):
        manager, handler = mock_node_manager
        agent = MidsceneAgent("emulator-5554", manager)
        agent.destroy()

        assert agent._closed is True
        destroy_calls = [r for r in handler.requests_received if r["method"] == "destroySession"]
        assert len(destroy_calls) == 1

    def test_rpc_error_raises_midscene_rpc_error(self, mock_rpc_server):
        port, handler = mock_rpc_server

        # 让 aiAct 返回错误
        class ErrorHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                if body["method"] == "createSession":
                    result = json.dumps({"jsonrpc": "2.0", "id": body["id"],
                                         "result": {"sessionId": "s1"}})
                else:
                    result = json.dumps({"jsonrpc": "2.0", "id": body["id"],
                                         "error": {"code": -1, "message": "Device disconnected"}})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(result.encode())

            def log_message(self, *args): pass

        server = HTTPServer(("127.0.0.1", 0), ErrorHandler)
        p = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        manager = MagicMock()
        manager.port = p
        agent = MidsceneAgent("emulator-5554", manager)

        with pytest.raises(MidsceneRPCError, match="Device disconnected"):
            agent.act("点击按钮")

        server.shutdown()


# ─── MidsceneMixin 测试 ───────────────────────────────────────────────────────

class TestMidsceneMixin:

    def test_ai_property_raises_without_config(self):
        class MyDevice(MidsceneMixin):
            def __init__(self):
                self.init_midscene("emulator-5554", config=None)

        device = MyDevice()
        with pytest.raises(RuntimeError, match="midscene_config is required"):
            _ = device.ai

    def test_ai_property_raises_without_init(self):
        class BadDevice(MidsceneMixin):
            pass  # 忘记调用 init_midscene

        device = BadDevice()
        with pytest.raises(RuntimeError, match="init_midscene"):
            _ = device.ai

    def test_close_midscene_safe_when_not_initialized(self):
        class MyDevice(MidsceneMixin):
            def __init__(self):
                self.init_midscene("emulator-5554")

        device = MyDevice()
        device.close_midscene()  # 不应抛出

    def test_close_midscene_calls_agent_destroy(self, mock_node_manager):
        manager, _ = mock_node_manager

        class MyDevice(MidsceneMixin):
            def __init__(self):
                config = MidsceneConfig("http://x.com", "key", "model")
                self.init_midscene("emulator-5554", config=config)

        device = MyDevice()
        with patch.object(MidsceneMixin, "ai", new_callable=lambda: property(
            lambda self: MagicMock(destroy=MagicMock())
        )):
            pass  # 简化测试：直接 mock agent

        mock_agent = MagicMock()
        device._midscene_agent = mock_agent
        device.close_midscene()
        mock_agent.destroy.assert_called_once()
        assert device._midscene_agent is None