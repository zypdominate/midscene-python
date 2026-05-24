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
    agent.ai_action("点击登录按钮")
    agent.ai_assert("已进入用户首页")
    agent.destroy()
"""

from .config import MidsceneConfig
from .exceptions import MidsceneError, MidsceneRPCError, MidsceneSetupError
from .midscene_agent import MidsceneAgent

__all__ = [
    "MidsceneAgent",
    "MidsceneConfig",
    "MidsceneError",
    "MidsceneRPCError",
    "MidsceneSetupError",
]

__version__ = "0.1.0"
