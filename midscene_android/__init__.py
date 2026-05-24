"""
midscene_android
================

将 Midscene.js AI 驱动的 Android 自动化能力桥接到 Python 测试框架。

公开 API
--------
MidsceneConfig   - AI 模型配置
MidsceneAgent    - AI 操作接口
MidsceneError    - 基础异常
MidsceneRPCError - RPC 通信异常

快速开始
--------
    from midscene_android import MidsceneAgent, MidsceneConfig

    config = MidsceneConfig(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-xxxxxx",
        model_name="qwen-vl-max",
        model_family="qwen",
    )

    agent = MidsceneAgent("emulator-5554", config)
    agent.act("点击登录按钮")
    agent.assert_("已进入用户首页")
    agent.destroy()
"""

from .midscene_agent import MidsceneAgent, get_connected_devices
from .config import MidsceneConfig
from .exceptions import MidsceneError, MidsceneRPCError, MidsceneSetupError

__all__ = [
    "MidsceneAgent",
    "get_connected_devices",
    "MidsceneConfig",
    "MidsceneError",
    "MidsceneRPCError",
    "MidsceneSetupError",
]

__version__ = "0.1.0"
