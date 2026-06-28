"""
pytest 插件共享支持（platform-agnostic）

android / web 各自的 pytest 插件复用这里的失败截图 / 报告采集逻辑，
仅需在各包内提供 CLI 选项、``midscene_agent`` / ``midscene_web_agent`` fixture
以及一个调用 :func:`capture_on_failure` 的 ``pytest_runtest_makereport`` hook。

为避免 midscene-core 强依赖 pytest，本模块不在顶层 import pytest，
所有参数（item / rep / agent）按鸭子类型使用。
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("midscene.pytest")

_SCREENSHOT_DATA_URI_PREFIX = "data:image/png;base64,"

# 挂在 pytest.Item 上用于跨 hook/fixture 传递数据的属性名
ATTR_AGENT = "_midscene_agent"
ATTR_ARTIFACT_DIR = "_midscene_artifact_dir"
DEFAULT_ARTIFACT_DIR = "midscene_artifacts"


def safe_filename(nodeid: str) -> str:
    """将 pytest node ID 转换为适合作为文件名的字符串。"""
    return (
        nodeid.replace("/", "_")
        .replace("\\", "_")
        .replace("::", "__")
        .replace(" ", "_")
        .replace("[", "_")
        .replace("]", "_")
    )


def bind_agent(item: Any, agent: Any, artifact_dir: str) -> None:
    """在测试 item 上记录 agent 与产物目录，供 makereport hook 在失败时访问。"""
    item.__dict__[ATTR_AGENT] = agent
    item.__dict__[ATTR_ARTIFACT_DIR] = artifact_dir


def capture_on_failure(item: Any, rep: Any) -> None:
    """call 阶段失败时，自动抓取截图并把截图/报告路径写入 TestReport.sections。"""
    if getattr(rep, "when", None) != "call" or not getattr(rep, "failed", False):
        return
    agent = item.__dict__.get(ATTR_AGENT)
    if agent is None or agent.is_closed():
        return
    artifact_dir = Path(item.__dict__.get(ATTR_ARTIFACT_DIR, DEFAULT_ARTIFACT_DIR))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    safe = safe_filename(item.nodeid)
    _try_capture_screenshot(agent, artifact_dir, safe, rep)
    _try_attach_report_path(agent, rep)


def _try_capture_screenshot(
        agent: Any,
        artifact_dir: Path,
        safe_name: str,
        rep: Any,
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


def _try_attach_report_path(agent: Any, rep: Any) -> None:
    """将 Midscene HTML 报告路径写入 TestReport.sections。"""
    try:
        report_path = agent.get_report_file()
        if report_path:
            rep.sections.append(
                ("midscene | 执行报告", f"已保存至：{Path(report_path).resolve()}")
            )
    except Exception as exc:
        logger.debug("midscene: 获取报告路径失败: %s", exc)
