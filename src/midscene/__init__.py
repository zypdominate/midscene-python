"""
midscene
========

将 [Midscene.js](https://github.com/web-infra-dev/midscene) AI 驱动的 UI 自动化
能力桥接到 Python 测试框架。单包内按模块划分：

- Android 自动化：:class:`MidsceneAgent`（``agent_android``）
- 网页自动化：:class:`MidsceneWebAgent` + 驱动（``agent_web`` / ``drivers``）
- 共享底层：配置、异常、Node 运行时桥接、RPC 服务管理、:class:`BaseAgent`

快速开始（Android）
-------------------
    from midscene import MidsceneAgent

    agent = MidsceneAgent("emulator-5554")
    agent.ai_action("点击登录按钮")
    agent.ai_assert("已进入用户首页")
    agent.destroy()

快速开始（Web）
---------------
    from midscene import MidsceneWebAgent

    agent = MidsceneWebAgent("https://example.com")
    agent.ai_action("点击更多信息链接")
    agent.ai_assert("页面已跳转")
    agent.destroy()
"""

from __future__ import annotations

from .agent_android import ANDROID_SERVICE_SPEC, MidsceneAgent
from .agent_web import WEB_SERVICE_SPEC, MidsceneWebAgent
from .base_agent import BaseAgent
from .config import MidsceneConfig
from .drivers import BridgeDriver, PlaywrightDriver, PuppeteerDriver, WebDriver
from .exceptions import (
    MidsceneConfigError,
    MidsceneError,
    MidsceneNodeServiceError,
    MidsceneRPCError,
    MidsceneSetupError,
)
from .node_service import NodeServiceManager
from .runtime import ServiceSpec

__all__ = [
    "ANDROID_SERVICE_SPEC",
    "WEB_SERVICE_SPEC",
    "BaseAgent",
    "BridgeDriver",
    "MidsceneAgent",
    "MidsceneConfig",
    "MidsceneConfigError",
    "MidsceneError",
    "MidsceneNodeServiceError",
    "MidsceneRPCError",
    "MidsceneSetupError",
    "MidsceneWebAgent",
    "NodeServiceManager",
    "PlaywrightDriver",
    "PuppeteerDriver",
    "ServiceSpec",
    "WebDriver",
]

try:
    from importlib.metadata import version

    __version__ = version("midscene")
except Exception:
    __version__ = "dev"
