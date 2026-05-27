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
class TestLoginFlow:
    def test_login_with_valid_credentials(self, agent: MidsceneAgent):
        """测试正常登录流程。"""

        # Auto Planning：描述目标，AI 自动规划步骤
        agent.run_adb_shell("am start -n com.android.settings/.Settings")
        agent.ai_action("等待启动页动画结束，进入 App 首页")

        # Instant Actions：精确描述单个动作，更快更稳定
        agent.ai_tap("登录 / 注册 按钮")
        agent.ai_input("手机号输入框", "13800138000")
        agent.ai_input("密码输入框", "Test@123456")
        agent.ai_tap("登录按钮")

        # 等待异步操作
        agent.ai_wait_for("登录成功，显示用户首页", timeout_ms=10000)

        # AI 断言
        agent.ai_assert("当前页面是用户首页，顶部显示欢迎信息")

    def test_extract_user_info(self, agent: MidsceneAgent):
        """测试数据提取。"""
        agent.run_adb_shell("am start -n com.android.settings/.Settings")
        agent.ai_action("进入用户个人资料页面")

        # 结构化数据提取
        user_info = agent.ai_query(
            '{"username": string, "level": number, "avatar_visible": boolean}'
        )
        assert user_info["username"] != ""
        assert user_info["level"] >= 1
        assert user_info["avatar_visible"] is True

    def test_agent_can_be_used_with_existing_device_wrapper(self, agent: MidsceneAgent):
        """现有设备封装继续负责原生操作，MidsceneAgent 只负责 AI 层。"""
        agent.ai_tap("接受条款按钮")
        agent.ai_assert("输入框中显示 Hello World")
