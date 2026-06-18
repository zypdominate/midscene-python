"""
示例：如何将 midscene_android 集成到现有 Python 自动化测试框架。

直接创建 MidsceneAgent，与现有设备封装并行使用。
"""

import pytest

from midscene_android import MidsceneAgent


# ─────────────────────────────────────────────────────────────────────────────
# conftest.py 示例
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def agent():
    session = MidsceneAgent()
    try:
        yield session
    finally:
        session.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# 测试用例示例
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.device
class TestBasicAndroidActions:
    """
    通用 Android 操作测试。
    这些用例旨在任何 Android 设备上都能运行，不依赖特定 App。
    """

    def test_system_navigation(self, agent: MidsceneAgent):
        """测试基础系统导航操作。"""
        agent.home()
        agent.ai_assert("我正处于手机主屏幕或桌面")

        # 各厂商多任务 UI 差异大，断言「离开桌面」比识别卡片列表更稳定
        agent.recent_apps()
        agent.ai_assert("当前界面不是主屏幕桌面，而是多任务或应用切换界面")

        agent.home()
        agent.ai_assert("我回到了手机主屏幕或桌面")

    def test_settings_interaction(self, agent: MidsceneAgent):
        """测试系统设置页面的基本操作。"""
        # 通过 ADB 启动设置应用 (所有 Android 通用)
        agent.run_adb_shell("am start -a android.settings.SETTINGS")

        # 使用 AI 定位并点击设置项
        agent.ai_tap("显示 或 屏幕设置")

        # 向上滚动以查找更多内容
        agent.ai_scroll(direction="down")

        # 返回上一级
        agent.back()
        agent.ai_assert("回到了设置主页面")

    def test_extract_system_info(self, agent: MidsceneAgent):
        """测试从设置界面提取结构化数据。"""
        # 确保在设置主页
        agent.run_adb_shell("am start -a android.settings.SETTINGS")

        # 提取页面上的设置分类名称
        # 这里演示了如何获取列表中的多个项
        items = agent.ai_query(
            'string[] // 页面上可见的所有设置选项标题'
        )
        assert isinstance(items, list)
        assert len(items) > 0
        print(f"\n  Detected settings: {items}")

    def test_screenshot_and_status(self, agent: MidsceneAgent):
        """测试截图获取和状态检查。"""
        # 获取 Base64 截图
        base64_data = agent.get_screenshot()
        assert base64_data.startswith("data:image/png;base64,iVBORw")  # PNG 文件的 Base64 开头
        print(f"\n  Screenshot received, length: {len(base64_data)}")

        # 获取当前会话状态
        status = agent.get_status()
        assert status["status"] == "connected"
        assert "sessionId" in status
        print(f"  Session status: {status}")
