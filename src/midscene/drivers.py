"""
Web 自动化驱动抽象。

每个驱动负责把自身配置序列化为传给 Node 服务 ``createSession`` 的参数
（``to_create_params``）。当前 Puppeteer 已实现，Playwright / Bridge 为占位，
对应的 service.js 分支会抛出 not-implemented，便于后续逐步接入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class WebDriver:
    """Web 驱动基类。"""

    #: 驱动标识，传给 Node 服务用于分支选择
    driver_name: str = ""

    def to_create_params(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class PuppeteerDriver(WebDriver):
    """Puppeteer 驱动（默认）。

    Args:
        headless: 是否无头模式运行（默认 True）。
        viewport: 视口尺寸，如 ``{"width": 1280, "height": 800}``。
        cdp_endpoint: 若提供，则通过 ``puppeteer.connect({browserURL})`` 连接到
            已存在的浏览器（如 ``http://127.0.0.1:9222``），而非启动新实例。
    """

    headless: bool = True
    viewport: dict[str, int] | None = None
    cdp_endpoint: str | None = None

    driver_name = "puppeteer"

    def to_create_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"driver": self.driver_name, "headless": self.headless}
        if self.viewport:
            params["viewport"] = self.viewport
        if self.cdp_endpoint:
            params["cdpEndpoint"] = self.cdp_endpoint
        return params


@dataclass
class PlaywrightDriver(WebDriver):
    """Playwright 驱动（占位，service.js 分支暂未实现）。"""

    headless: bool = True

    driver_name = "playwright"

    def to_create_params(self) -> dict[str, Any]:
        return {"driver": self.driver_name, "headless": self.headless}


@dataclass
class BridgeDriver(WebDriver):
    """Bridge 模式驱动（Chrome 扩展，占位，service.js 分支暂未实现）。"""

    driver_name = "bridge"

    def to_create_params(self) -> dict[str, Any]:
        return {"driver": self.driver_name}
