"""
示例：如何将 midscene_android 集成到现有 Python 自动化测试框架。

展示两种集成方式：
  1. 继承 MidsceneMixin（推荐）
  2. 手动组合（不改继承链时）
"""

# ─────────────────────────────────────────────────────────────────────────────
# 方式一：继承 MidsceneMixin（推荐）
# 在你现有的 Device 类中混入即可，改动最小。
# ─────────────────────────────────────────────────────────────────────────────

from midscene_android import MidsceneMixin, MidsceneConfig


class AndroidDevice(MidsceneMixin):
    """
    示例设备类：模拟你现有的 ADB 设备封装。
    实际使用时，将 MidsceneMixin 加入你现有类的继承链即可。
    """

    def __init__(
        self,
        device_id: str,
        *,
        midscene_config: MidsceneConfig | None = None,
        # 你的其他参数...
    ):
        # 初始化你现有的设备逻辑
        self.device_id = device_id
        self._connected = False

        # 初始化 Midscene（一行代码）
        self.init_midscene(
            device_id,
            config=midscene_config,
            # 可选：传递给 AndroidAgent 的选项
            agent_options={
                "generateReport": False,   # 是否生成 HTML 报告
                "aiActContext": None,      # 全局上下文提示
            },
            # 可选：传递给 AndroidDevice 的选项
            device_options={
                # "androidAdbPath": "/custom/adb",  # 自定义 adb 路径
            },
        )

    # ── 你现有的原生方法（保持不变）─────────────────────────────────────────

    def connect(self) -> "AndroidDevice":
        # 你的连接逻辑
        self._connected = True
        return self

    def disconnect(self) -> None:
        self._connected = False

    def click(self, x: int, y: int) -> None:
        """原生 ADB 点击（你现有的实现）。"""
        print(f"[Native] click({x}, {y})")

    def input_text(self, text: str) -> None:
        """原生文本输入。"""
        print(f"[Native] input_text({text!r})")

    def screenshot(self) -> bytes:
        """截图。"""
        ...

    def start_app(self, package_name: str) -> None:
        """启动 App。"""
        print(f"[Native] start_app({package_name})")

    # ── context manager ──────────────────────────────────────────────────────

    def __enter__(self) -> "AndroidDevice":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close_midscene()   # 销毁 Midscene session
        self.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
# conftest.py 示例
# ─────────────────────────────────────────────────────────────────────────────

import pytest

# AI 模型配置（实际项目中从环境变量或配置文件读取）
MIDSCENE_CONFIG = MidsceneConfig(
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key="sk-your-api-key-here",   # 明文或 base64 均可
    model_name="qwen-vl-max",
    model_family="qwen",
)


@pytest.fixture(scope="session")
def midscene_config() -> MidsceneConfig:
    """session 级别的 AI 配置（整个测试会话共享一个 Node 进程）。"""
    return MIDSCENE_CONFIG


@pytest.fixture
def device(midscene_config: MidsceneConfig):
    """
    function 级别的设备 fixture。
    每个测试用例独立的设备 session（Node 进程复用）。
    """
    with AndroidDevice("emulator-5554", midscene_config=midscene_config) as d:
        yield d


# ─────────────────────────────────────────────────────────────────────────────
# 测试用例示例
# ─────────────────────────────────────────────────────────────────────────────

class TestLoginFlow:

    def test_login_with_valid_credentials(self, device: AndroidDevice):
        """测试正常登录流程。"""

        # ── 原生操作（你现有的能力）──────────────────────────────────────────
        device.start_app("com.example.myapp")

        # ── AI 操作（通过 .ai property）─────────────────────────────────────

        # Auto Planning：描述目标，AI 自动规划步骤
        device.ai.act("等待启动页动画结束，进入 App 首页")

        # Instant Actions：精确描述单个动作，更快更稳定
        device.ai.tap("登录 / 注册 按钮")
        device.ai.input("手机号输入框", "13800138000")
        device.ai.input("密码输入框", "Test@123456")
        device.ai.tap("登录按钮")

        # 等待异步操作
        device.ai.wait_for("登录成功，显示用户首页", timeout_ms=10000)

        # AI 断言
        device.ai.assert_("当前页面是用户首页，顶部显示欢迎信息")

    def test_extract_user_info(self, device: AndroidDevice):
        """测试数据提取。"""
        device.start_app("com.example.myapp")
        device.ai.act("进入用户个人资料页面")

        # 结构化数据提取
        user_info = device.ai.query(
            '{"username": string, "level": number, "avatar_visible": boolean}'
        )
        assert user_info["username"] != ""
        assert user_info["level"] >= 1
        assert user_info["avatar_visible"] is True

    def test_mixed_native_and_ai(self, device: AndroidDevice):
        """原生操作与 AI 操作混合使用示例。"""
        # 用原生操作做精确坐标操作（速度快）
        device.click(540, 960)

        # 用 AI 操作处理动态 UI（无需维护 selector）
        device.ai.tap("接受条款按钮")

        # 回到原生操作
        device.input_text("Hello World")

        # AI 断言结果
        device.ai.assert_("输入框中显示 Hello World")


# ─────────────────────────────────────────────────────────────────────────────
# 方式二：手动组合（不修改继承链）
# ─────────────────────────────────────────────────────────────────────────────

class ExistingDevice:
    """假设这是你已有的设备类，无法修改继承链。"""

    def __init__(self, device_id: str):
        self.device_id = device_id

    def click(self, x, y): ...
    def __enter__(self): return self
    def __exit__(self, *_): ...


class ExistingDeviceWithAI(ExistingDevice, MidsceneMixin):
    """在不改动 ExistingDevice 的前提下，通过多继承添加 .ai 能力。"""

    def __init__(self, device_id: str, *, midscene_config=None):
        ExistingDevice.__init__(self, device_id)
        self.init_midscene(device_id, config=midscene_config)

    def __exit__(self, *_):
        self.close_midscene()
        ExistingDevice.__exit__(self)