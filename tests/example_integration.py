"""
示例：如何将 midscene_android 集成到现有 Python 自动化测试框架。

直接创建 MidsceneAgent，与现有设备封装并行使用。
"""

from midscene_android import MidsceneAgent, MidsceneConfig


# ─────────────────────────────────────────────────────────────────────────────
# conftest.py 示例
# ─────────────────────────────────────────────────────────────────────────────

import pytest


@pytest.fixture(scope="session")
def midscene_config() -> MidsceneConfig:
    """session 级别的 AI 配置（整个测试会话共享一个 Node 进程）。"""
    # AI 模型配置（实际项目中从环境变量或配置文件读取）
    MIDSCENE_CONFIG = MidsceneConfig(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-your-api-key-here",  # 明文或 base64 均可
        model_name="qwen-vl-max",
        model_family="qwen",
    )
    return MIDSCENE_CONFIG


@pytest.fixture
def agent(midscene_config: MidsceneConfig):
    session = MidsceneAgent("emulator-5554", midscene_config)
    try:
        yield session
    finally:
        session.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# 测试用例示例
# ─────────────────────────────────────────────────────────────────────────────

class TestLoginFlow:

    def test_login_with_valid_credentials(self, agent: MidsceneAgent):
        """测试正常登录流程。"""

        # Auto Planning：描述目标，AI 自动规划步骤
        agent.launch("com.example.myapp/.MainActivity")
        agent.act("等待启动页动画结束，进入 App 首页")

        # Instant Actions：精确描述单个动作，更快更稳定
        agent.tap("登录 / 注册 按钮")
        agent.input("手机号输入框", "13800138000")
        agent.input("密码输入框", "Test@123456")
        agent.tap("登录按钮")

        # 等待异步操作
        agent.wait_for("登录成功，显示用户首页", timeout_ms=10000)

        # AI 断言
        agent.assert_("当前页面是用户首页，顶部显示欢迎信息")

    def test_extract_user_info(self, agent: MidsceneAgent):
        """测试数据提取。"""
        agent.launch("com.example.myapp/.MainActivity")
        agent.act("进入用户个人资料页面")

        # 结构化数据提取
        user_info = agent.query(
            '{"username": string, "level": number, "avatar_visible": boolean}'
        )
        assert user_info["username"] != ""
        assert user_info["level"] >= 1
        assert user_info["avatar_visible"] is True

    def test_agent_can_be_used_with_existing_device_wrapper(self, agent: MidsceneAgent):
        """现有设备封装继续负责原生操作，MidsceneAgent 只负责 AI 层。"""
        agent.tap("接受条款按钮")
        agent.assert_("输入框中显示 Hello World")
