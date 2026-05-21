"""
MidsceneMixin：为现有 Python 设备类提供 .ai property 的混入类。

使用方式：

    # 方式一：直接继承 MidsceneMixin（推荐）
    from midscene_android import MidsceneMixin, MidsceneConfig

    class MyDevice(MidsceneMixin, YourBaseDevice):
        def __init__(self, device_id: str, *, midscene_config=None, **kwargs):
            super().__init__(device_id, **kwargs)
            self.init_midscene(device_id, config=midscene_config)

    # 方式二：手动集成（不想改继承链时）
    # 将 MidsceneMixin 的逻辑直接复制到你的设备类中

用法示例：

    config = MidsceneConfig(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-xxxxxx",
        model_name="qwen-vl-max",
        model_family="qwen",
    )

    with MyDevice("emulator-5554", midscene_config=config) as device:
        device.click(100, 200)           # 原有能力
        device.ai.act("点击登录按钮")    # AI 能力
        device.ai.assert_("已进入首页")
"""

from __future__ import annotations

import logging
from typing import Optional

from .service import NodeServiceManager
from .agent import MidsceneAgent
from .config import MidsceneConfig

logger = logging.getLogger(__name__)


class MidsceneMixin:
    """
    混入类，为任意 Python 设备类添加 .ai property。

    子类需在 __init__ 中调用 self.init_midscene(device_id, config=...)。
    在 __exit__ 或 close() 中调用 self.close_midscene()。
    """

    def init_midscene(
            self,
            device_id: str,
            *,
            config: Optional[MidsceneConfig] = None,
            agent_options: Optional[dict] = None,
            device_options: Optional[dict] = None,
    ) -> None:
        """
        初始化 Midscene 相关状态。在子类 __init__ 中调用。

        Parameters
        ----------
        device_id:
            ADB 设备 ID
        config:
            MidsceneConfig 实例，若为 None 则调用 .ai 时抛出明确错误
        agent_options:
            传递给 AndroidAgent 的额外选项
        device_options:
            传递给 AndroidDevice 的额外选项（如自定义 adb 路径）
        """
        self._midscene_device_id = device_id
        self._midscene_config: Optional[MidsceneConfig] = config
        self._midscene_agent_options = agent_options or {}
        self._midscene_device_options = device_options or {}
        self._midscene_agent: Optional[MidsceneAgent] = None

    def close_midscene(self) -> None:
        """销毁 Midscene session。在子类 __exit__ 或 close() 中调用。"""
        if hasattr(self, "_midscene_agent") and self._midscene_agent is not None:
            try:
                self._midscene_agent.destroy()
            except Exception as e:
                logger.debug("Error closing Midscene agent: %s", e)
            finally:
                self._midscene_agent = None

    @property
    def ai(self) -> MidsceneAgent:
        """
        懒加载的 MidsceneAgent 实例。

        首次访问时：
          1. 确保 Node.js 服务已启动（进程级单例）
          2. 在 Node 侧创建设备 session
        后续访问直接返回缓存的 agent 实例。
        """
        if not hasattr(self, "_midscene_agent"):
            raise RuntimeError(
                "MidsceneMixin.init_midscene() was not called. "
                "Please call self.init_midscene(device_id, config=...) in your __init__."
            )

        if self._midscene_agent is not None:
            return self._midscene_agent

        if self._midscene_config is None:
            raise RuntimeError(
                "midscene_config is required to use device.ai.\n"
                "Pass a MidsceneConfig when initializing your device:\n"
                "  config = MidsceneConfig(base_url=..., api_key=..., model_name=...)\n"
                "  device = MyDevice('emulator-5554', midscene_config=config)"
            )

        # 启动/复用进程级 Node 服务
        node_manager = NodeServiceManager(self._midscene_config)
        node_manager.ensure_started()

        # 创建本设备的 session
        self._midscene_agent = MidsceneAgent(
            self._midscene_device_id,
            node_manager,
            agent_options=self._midscene_agent_options,
            device_options=self._midscene_device_options,
        )
        return self._midscene_agent