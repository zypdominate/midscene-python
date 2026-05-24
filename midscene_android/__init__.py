"""
midscene_android
================

将 Midscene.js AI 驱动的 Android 自动化能力桥接到 Python 测试框架。

公开 API
--------
MidsceneConfig   - AI 模型配置
MidsceneMixin    - 混入类，为设备类添加 .ai property
MidsceneAgent    - AI 操作接口（通常通过 device.ai 访问，不直接实例化）
MidsceneError    - 基础异常
MidsceneRPCError - RPC 通信异常

快速开始
--------
    from midscene_android import MidsceneMixin, MidsceneConfig

    class MyDevice(MidsceneMixin):
        def __init__(self, device_id, *, midscene_config=None):
            self.init_midscene(device_id, config=midscene_config)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close_midscene()

    config = MidsceneConfig(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-xxxxxx",
        model_name="qwen-vl-max",
        model_family="qwen",
    )

    with MyDevice("emulator-5554", midscene_config=config) as device:
        device.ai.act("点击登录按钮")
        device.ai.assert_("已进入用户首页")
"""

from .midscene_agent import MidsceneAgent
from .config import MidsceneConfig
from .exceptions import MidsceneError, MidsceneRPCError, MidsceneSetupError
from .mixin import MidsceneMixin

__all__ = [
    "MidsceneAgent",
    "MidsceneConfig",
    "MidsceneMixin",
    "MidsceneError",
    "MidsceneRPCError",
    "MidsceneSetupError",
]

__version__ = "0.1.0"