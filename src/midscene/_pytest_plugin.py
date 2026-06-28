"""
midscene pytest 插件
====================

通过 pip 安装 midscene 后，pytest 会自动加载本插件，无需任何配置。

提供：

1. ``midscene_agent`` fixture（Android）：开箱即用的 :class:`MidsceneAgent`，
   设备 ID 与 AI 配置从 CLI 参数或环境变量自动读取。
2. ``midscene_web_agent`` fixture（Web）：开箱即用的 :class:`MidsceneWebAgent`
   （默认 Puppeteer 无头）。
3. 失败自动截图 / 报告：使用上述任一 fixture 的测试用例失败时，插件会自动抓取
   截图并把截图/报告路径附加到 pytest 报告的 sections（复用 ``_pytest_support``）。
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from . import _pytest_support as support

if TYPE_CHECKING:
    from .agent_android import MidsceneAgent
    from .agent_web import MidsceneWebAgent


# ── CLI 选项 ──────────────────────────────────────────────────────────────────


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("midscene", "midscene 选项")
    group.addoption(
        "--midscene-device",
        action="store",
        default=None,
        metavar="DEVICE_ID",
        help=(
            "midscene_agent fixture 使用的 Android 设备 ID。"
            "优先级高于 MIDSCENE_DEVICE_ID / ANDROID_DEVICE_ID 环境变量。"
        ),
    )
    group.addoption(
        "--midscene-url",
        action="store",
        default=None,
        metavar="URL",
        help=(
            "midscene_web_agent fixture 的起始页面 URL。"
            "优先级高于 MIDSCENE_WEB_URL 环境变量。"
        ),
    )
    group.addoption(
        "--midscene-headed",
        action="store_true",
        default=False,
        help="midscene_web_agent 以有头（非 headless）模式启动浏览器（默认无头）。",
    )
    group.addoption(
        "--midscene-artifact-dir",
        action="store",
        default=support.DEFAULT_ARTIFACT_DIR,
        metavar="DIR",
        help="失败时保存截图和 Midscene 报告路径的目录（默认：midscene_artifacts/）",
    )


# ── 核心 hook：失败时抓取截图并写入报告 sections（仅注册一次）────────────────


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
        item: pytest.Item,
        call: pytest.CallInfo,  # noqa: ARG001
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """call 阶段失败时，自动从已绑定的 agent 抓取截图与报告路径。"""
    rep: pytest.TestReport = yield
    support.capture_on_failure(item, rep)
    return rep


# ── midscene_agent fixture（Android）─────────────────────────────────────────


@pytest.fixture
def midscene_agent(
        request: pytest.FixtureRequest,
) -> Generator[MidsceneAgent, None, None]:
    """
    提供已就绪的 MidsceneAgent；测试失败时自动保存截图与 Midscene HTML 报告。

    设备 ID 解析顺序

    1. ``--midscene-device`` CLI 参数
    2. ``MIDSCENE_DEVICE_ID`` 环境变量
    3. ``ANDROID_DEVICE_ID`` 环境变量
    4. 自动选取第一台已连接设备（传 ``None``，由 Node 服务端决定）

    AI 配置: 从 ``MIDSCENE_MODEL_*`` 环境变量 / ``.env`` 文件自动读取。
    """
    from .agent_android import MidsceneAgent
    from .config import MidsceneConfig

    device_id: str | None = (
            request.config.getoption("--midscene-device", default=None)
            or os.environ.get("MIDSCENE_DEVICE_ID")
            or os.environ.get("ANDROID_DEVICE_ID")
    )
    artifact_dir: str = request.config.getoption(
        "--midscene-artifact-dir", default=support.DEFAULT_ARTIFACT_DIR
    )

    config = MidsceneConfig.from_env()
    agent = MidsceneAgent(device_id, config)

    support.bind_agent(request.node, agent, artifact_dir)

    yield agent

    agent.destroy()


# ── midscene_web_agent fixture（Web）─────────────────────────────────────────


@pytest.fixture
def midscene_web_agent(
        request: pytest.FixtureRequest,
) -> Generator[MidsceneWebAgent, None, None]:
    """
    提供已就绪的 MidsceneWebAgent（默认 Puppeteer）；失败时自动保存截图与报告。

    起始 URL 解析顺序

    1. ``--midscene-url`` CLI 参数
    2. ``MIDSCENE_WEB_URL`` 环境变量
    3. 不导航（保持 about:blank，由测试自行 ``goto``）

    无头模式：默认无头，可用 ``--midscene-headed`` 切换为有头。

    AI 配置: 从 ``MIDSCENE_MODEL_*`` 环境变量 / ``.env`` 文件自动读取。
    """
    from .agent_web import MidsceneWebAgent
    from .config import MidsceneConfig
    from .drivers import PuppeteerDriver

    url: str | None = (
            request.config.getoption("--midscene-url", default=None)
            or os.environ.get("MIDSCENE_WEB_URL")
    )
    headed: bool = request.config.getoption("--midscene-headed", default=False)
    artifact_dir: str = request.config.getoption(
        "--midscene-artifact-dir", default=support.DEFAULT_ARTIFACT_DIR
    )

    config = MidsceneConfig.from_env()
    driver = PuppeteerDriver(headless=not headed)
    agent = MidsceneWebAgent(url=url, driver=driver, config=config)

    support.bind_agent(request.node, agent, artifact_dir)

    yield agent

    agent.destroy()
