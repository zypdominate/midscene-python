"""MidsceneWebAgent：Python 侧网页 AI 操作接口（基于 midscene 共享底层）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base_agent import BaseAgent
from .config import MidsceneConfig
from .drivers import PuppeteerDriver, WebDriver
from .runtime import ServiceSpec

#: Web 平台的 Node 服务定义（缓存在 ~/.midscene/web/node_service/）
WEB_SERVICE_SPEC = ServiceSpec(
    name="web",
    dist_name="midscene",
    source_dir=Path(__file__).parent / "_node_driver" / "web" / "service",
    label="@midscene/web",
)


class MidsceneWebAgent(BaseAgent):
    """AI 驱动的网页操作接口。

    继承自 :class:`midscene.BaseAgent`，复用全部跨平台 ``ai_*`` 方法，
    并扩展网页导航专有操作。默认使用 Puppeteer 驱动（首次运行会自动下载 Chromium）。
    """

    SERVICE_SPEC = WEB_SERVICE_SPEC

    def __init__(
            self,
            url: str | None = None,
            driver: WebDriver | None = None,
            config: MidsceneConfig | None = None,
    ):
        self._driver = driver or PuppeteerDriver()
        self._url = url
        create_params: dict[str, Any] = self._driver.to_create_params()
        if url:
            create_params["url"] = url
        super().__init__(config, create_params=create_params)

    # ── 网页专有方法 ──────────────────────────────────────────────────────────────

    def goto(self, url: str) -> None:
        """导航到指定 URL。"""
        self._rpc("goto", url=url)

    def new_tab(self, url: str | None = None) -> None:
        """打开新标签页并切换为当前操作对象（可选直接导航到 url）。"""
        self._rpc("newTab", url=url)

    def set_viewport(self, width: int, height: int) -> None:
        """设置视口尺寸。"""
        self._rpc("setViewport", width=width, height=height)

    def ai_hover(self, locate: str) -> None:
        """AI 定位并将鼠标悬停到元素上。"""
        self._rpc("aiHover", locate=locate)
