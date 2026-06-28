"""
midscene-web 测试

  Level 1 - Node 服务启动 + RPC ping（无需浏览器、无需 AI Key）
    首次运行需联网：下载 Node/npm，并 npm install @midscene/web + puppeteer
    （puppeteer 会下载约 150MB Chromium）。

  Level 2 - 完整网页 AI 操作（需要 AI Key + 已安装 Chromium）
    使用 pytest.mark.web 标记，CI 中按需运行。

运行：
  pytest packages/midscene-web/tests/test_web_service.py -v -s -k "not web"
"""

from __future__ import annotations

import uuid

import pytest
import requests

from midscene import MidsceneConfig
from midscene.agent_web import WEB_SERVICE_SPEC
from midscene.node_service import NodeServiceManager

web_mark = pytest.mark.web


def _make_dummy_config() -> MidsceneConfig:
    """Node 服务本身启动不需要真实 AI Key，用占位值即可。"""
    return MidsceneConfig(
        base_url="https://placeholder.example.com/v1",
        api_key="dummy-key-for-web-service-test",
        model_name="placeholder-model",
        model_family="openai",
    )


def _get_service(config: MidsceneConfig) -> NodeServiceManager:
    return NodeServiceManager.get(WEB_SERVICE_SPEC, config)


def _reset_service() -> None:
    NodeServiceManager.reset(WEB_SERVICE_SPEC.name)


class TestWebNodeServiceStartup:
    """验证 Web Node RPC 服务能正常启动并响应 ping（不创建浏览器会话）。"""

    def setup_method(self):
        _reset_service()

    def teardown_method(self):
        _reset_service()

    def test_service_starts_and_pings(self):
        config = _make_dummy_config()
        mgr = _get_service(config)
        mgr.ensure_started()

        assert mgr.port > 0
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
        print(f"\n  web service ping → {data['result']}")

    def test_unknown_method_returns_rpc_error(self):
        config = _make_dummy_config()
        mgr = _get_service(config)
        mgr.ensure_started()
        resp = requests.post(
            f"http://127.0.0.1:{mgr.port}/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "method": "nonExistentMethod",
                "params": {},
            },
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32601


@web_mark
class TestWebAgentOnBrowser:
    """完整网页 AI 操作（需要 AI Key + 已安装 Chromium）。"""

    def test_goto_and_assert(self):
        from midscene import MidsceneWebAgent

        agent = MidsceneWebAgent("https://example.com")
        try:
            agent.ai_assert("页面包含 Example Domain 字样")
        finally:
            agent.destroy()
