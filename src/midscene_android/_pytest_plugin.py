"""
midscene-android pytest 插件
=============================

通过 pip 安装 midscene-android 后，pytest 会自动加载本插件，无需任何配置。

提供两项能力：

1. midscene_agent fixture：开箱即用的 MidsceneAgent，不需要在 conftest.py
   中重复声明。设备 ID 与 AI 配置从 CLI 参数或环境变量自动读取。

2. 失败自动截图 / 报告：使用 midscene_agent 的测试用例失败时，插件会自动
   调用 get_screenshot() 和 get_report_file()，将截图保存为 PNG 并把路径附加
   到 pytest 报告的 sections，无需手动编写清理逻辑。
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from .midscene_agent import MidsceneAgent

logger = logging.getLogger(__name__)

# 挂在 pytest.Item 上用于跨 hook/fixture 传递数据的属性名
_ATTR_AGENT = "_midscene_agent"
_ATTR_ARTIFACT_DIR = "_midscene_artifact_dir"

_SCREENSHOT_DATA_URI_PREFIX = "data:image/png;base64,"


# ── CLI 选项 ──────────────────────────────────────────────────────────────────


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("midscene-android", "midscene-android 选项")
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
        "--midscene-artifact-dir",
        action="store",
        default="midscene_artifacts",
        metavar="DIR",
        help="失败时保存截图和 Midscene 报告路径的目录（默认：midscene_artifacts/）",
    )


# ── 核心 hook：失败时抓取截图并写入报告 sections ──────────────────────────────


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
        item: pytest.Item,
        call: pytest.CallInfo,  # noqa: ARG001
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """
    在 call 阶段失败时，自动从 midscene_agent 抓取截图和报告路径，
    附加到 TestReport.sections，在 pytest 输出和第三方报告（如 pytest-html）中可见。

    使用 wrapper=True（pytest ≥8.1）以避免已弃用的 hookwrapper 警告。
    """
    rep: pytest.TestReport = yield

    if rep.when == "call" and rep.failed:
        agent: MidsceneAgent | None = item.__dict__.get(_ATTR_AGENT)
        if agent is not None and not agent.is_closed():
            artifact_dir = Path(item.__dict__.get(_ATTR_ARTIFACT_DIR, "midscene_artifacts"))
            artifact_dir.mkdir(parents=True, exist_ok=True)
            safe = _safe_filename(item.nodeid)
            _try_capture_screenshot(agent, artifact_dir, safe, rep)
            _try_attach_report_path(agent, rep)

    return rep


# ── midscene_agent fixture ────────────────────────────────────────────────────


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

    使用示例（无需在 conftest.py 中重复声明）::

        def test_login(midscene_agent):
            midscene_agent.ai_action("点击登录按钮")
            midscene_agent.ai_assert("已成功登录")

    失败时，截图自动保存至 ``--midscene-artifact-dir``（默认 ``midscene_artifacts/``），
    路径显示在 pytest 终端输出和 HTML 报告中。
    """
    from .config import MidsceneConfig
    from .midscene_agent import MidsceneAgent

    device_id: str | None = (
            request.config.getoption("--midscene-device", default=None)
            or os.environ.get("MIDSCENE_DEVICE_ID")
            or os.environ.get("ANDROID_DEVICE_ID")
    )
    artifact_dir: str = request.config.getoption(
        "--midscene-artifact-dir", default="midscene_artifacts"
    )

    config = MidsceneConfig.from_env()
    agent = MidsceneAgent(device_id, config)

    # 挂在 item 上，让 makereport hook 能在 teardown 前访问到
    item = request.node
    item.__dict__[_ATTR_AGENT] = agent
    item.__dict__[_ATTR_ARTIFACT_DIR] = artifact_dir

    yield agent

    agent.destroy()


# ── 内部工具 ──────────────────────────────────────────────────────────────────


def _safe_filename(nodeid: str) -> str:
    """将 pytest node ID 转换为适合作为文件名的字符串。"""
    return (
        nodeid.replace("/", "_")
        .replace("\\", "_")
        .replace("::", "__")
        .replace(" ", "_")
        .replace("[", "_")
        .replace("]", "_")
    )


def _try_capture_screenshot(
        agent: MidsceneAgent,
        artifact_dir: Path,
        safe_name: str,
        rep: pytest.TestReport,
) -> None:
    """抓取截图、保存为 PNG，并将路径写入 TestReport.sections。"""
    try:
        raw = agent.get_screenshot()
        if not raw:
            return

        if raw.startswith(_SCREENSHOT_DATA_URI_PREFIX):
            png_bytes = base64.b64decode(raw[len(_SCREENSHOT_DATA_URI_PREFIX):])
        else:
            png_bytes = base64.b64decode(raw)

        screenshot_path = artifact_dir / f"{safe_name}.png"
        screenshot_path.write_bytes(png_bytes)
        rep.sections.append(
            ("midscene | 失败截图", f"已保存至：{screenshot_path.resolve()}")
        )
        logger.info("midscene: 截图已保存 → %s", screenshot_path.resolve())
    except Exception as exc:
        logger.debug("midscene: 截图失败: %s", exc)
        rep.sections.append(("midscene | 截图失败", str(exc)))


def _try_attach_report_path(
        agent: MidsceneAgent,
        rep: pytest.TestReport,
) -> None:
    """将 Midscene HTML 报告路径写入 TestReport.sections。"""
    try:
        report_path = agent.get_report_file()
        if report_path:
            rep.sections.append(
                ("midscene | 执行报告", f"已保存至：{Path(report_path).resolve()}")
            )
    except Exception as exc:
        logger.debug("midscene: 获取报告路径失败: %s", exc)
