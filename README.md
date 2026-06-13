# midscene-android

将 [Midscene.js](https://github.com/web-infra-dev/midscene) AI 驱动的 Android 自动化能力桥接到 Python 测试框架。

无需自行安装 Node.js；无需维护 UI 选择器——用自然语言描述操作，AI 负责定位和执行。

---

## 目录

- [架构](#架构)
- [安装](#安装)
- [快速开始](#快速开始)
- [配置](#配置)
- [API 参考](#api-参考)
- [异常处理](#异常处理)
- [开发者指南](#开发者指南)

---

## 架构

```
Python 测试代码
└── agent.ai_action("点击登录按钮")
    │
    │  JSON-RPC 2.0（本地回环，无网络开销）
    ▼
Node.js 微服务（进程级单例，首次使用自动启动）
├── 内置 Node 二进制  ← 随 wheel 分发，无需用户安装 Node
├── @midscene/android ← 首次使用时自动 npm install 到缓存
│     └── AI 视觉模型（调用你配置的 API Key）
└── ADB
      └── Android 设备 / 模拟器
```

**关键特性：**

- Python 进程与 Node 进程 1:1，多个 `MidsceneAgent` 共享同一 Node 进程（通过 sessionId 隔离）
- Python 进程退出时 Node 子进程自动清理
- 无需系统已安装 `node` 或 `npm`

---

## 安装

```bash
pip install midscene-android
```

> **首次使用**：会自动执行 `npm install @midscene/android`，需要访问 npm registry，约需 1～2 分钟。之后版本升级时会自动重新安装，无需手动干预。

**系统要求：**

| 条件 | 说明 |
|------|------|
| Python | 3.9 及以上 |
| ADB | 已安装并在 PATH 中（`adb devices` 能看到目标设备） |
| AI API | 支持 OpenAI 兼容接口的视觉模型（如 qwen-vl-max、GPT-4o） |
| Node.js | **无需安装**，wheel 内已内置 |

---

## 快速开始

### 1. 配置 AI 模型

推荐使用 `.env` 文件（自动加载，无需 `export`）：

```ini
# .env
MIDSCENE_MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MIDSCENE_MODEL_API_KEY=sk-your-api-key
MIDSCENE_MODEL_NAME=qwen-vl-max
MIDSCENE_MODEL_FAMILY=qwen
```

### 2. 编写测试

```python
from midscene_android import MidsceneAgent

# 从 .env 或环境变量自动读取配置
agent = MidsceneAgent("emulator-5556")

with MidsceneAgent("emulator-5556") as agent:
    agent.ai_action("等待应用首页加载完成")
    agent.ai_tap("登录按钮")
    agent.ai_input("用户名输入框", "testuser")
    agent.ai_input("密码输入框", "Test@123456")
    agent.ai_tap("确认登录")
    agent.ai_wait_for("登录成功，显示用户首页", timeout_ms=10000)
    agent.ai_assert("当前页面是用户首页")
```

### 3. 在 pytest 中使用

```python
# conftest.py
import pytest
from midscene_android import MidsceneAgent

@pytest.fixture
def agent():
    ag = MidsceneAgent("emulator-5556")
    yield ag
    ag.destroy()


# test_login.py
def test_login(agent: MidsceneAgent):
    agent.ai_action("打开登录页面")
    agent.ai_input("用户名", "testuser")
    agent.ai_input("密码", "password")
    agent.ai_tap("登录")
    agent.ai_assert("登录成功，显示用户名 testuser")
```

---

## 配置

### MidsceneConfig

可以通过环境变量、`.env` 文件或代码直接传入配置：

```python
from midscene_android import MidsceneAgent, MidsceneConfig

# 方式一：从 .env / 环境变量自动读取（推荐）
agent = MidsceneAgent("emulator-5556")

# 方式二：代码直接传入
config = MidsceneConfig(
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key="sk-your-api-key",
    model_name="qwen-vl-max",
    model_family="qwen",          # 可选，默认 "openai"
)
agent = MidsceneAgent("emulator-5556", config)
```

### 支持的模型家族

| `model_family` | 适用模型 | 示例 `model_name` |
|---|---|---|
| `openai` | OpenAI GPT 系列 | `gpt-4o` |
| `qwen` | 阿里通义千问 | `qwen-vl-max` |
| `doubao` | 字节豆包 | `doubao-vision-pro-32k` |
| `gemini` | Google Gemini | `gemini-2.0-flash` |
| `claude` | Anthropic Claude | `claude-opus-4-5` |

### 环境变量说明

| 变量 | 必填 | 说明 |
|------|------|------|
| `MIDSCENE_MODEL_BASE_URL` | ✅ | AI API 的 base URL |
| `MIDSCENE_MODEL_API_KEY` | ✅ | API Key |
| `MIDSCENE_MODEL_NAME` | ✅ | 模型名称 |
| `MIDSCENE_MODEL_FAMILY` | ❌ | 模型家族，默认 `openai` |

---

## API 参考

所有方法均为同步调用，内部通过 JSON-RPC 与 Node.js 微服务通信。

### 初始化与销毁

```python
agent = MidsceneAgent(device_id, config=None)
# device_id : ADB 设备 ID，如 "emulator-5556" 或 "192.168.1.100:5555"
# config    : MidsceneConfig 实例，可选，默认从环境变量读取

agent.destroy()        # 释放 session，进程退出时自动调用
agent.is_closed()      # 返回 True/False
```

### Auto Planning

```python
agent.ai_action(prompt: str) -> None
```

AI 自动规划并执行多步操作。适合描述复合目标：

```python
agent.ai_action("打开设置，找到蓝牙选项并开启")
agent.ai_action("滑动到页面底部，点击'加载更多'")
```

### Instant Actions — 精确单步操作

比 `ai_action` 更快、更稳定，适合已知元素的直接操作：

```python
agent.ai_tap(locate: str) -> None
# 点击元素
agent.ai_tap("屏幕右上角的关闭按钮")
agent.ai_tap("文字为'立即购买'的按钮")

agent.ai_input(locate: str, value: str) -> None
# 在指定输入框中输入文本（先清空再输入）
agent.ai_input("搜索框", "midscene python")

agent.ai_clear_input(locate: str) -> None
# 清空输入框内容
agent.ai_clear_input("用户名输入框")

agent.ai_scroll(
    locate: str = None,
    direction: str = "down",        # "up" | "down" | "left" | "right"
    scroll_type: str = None,
    distance: int = None,
) -> None
# 滚动操作
agent.ai_scroll("商品列表", direction="down", distance=3)

agent.ai_long_press(locate: str, duration: int = None) -> None
# 长按，duration 单位毫秒
agent.ai_long_press("消息列表第一条")

agent.ai_double_click(locate: str) -> None
# 双击
agent.ai_double_click("图片预览区域")

agent.ai_keyboard_press(key_name: str, locate: str = None) -> None
# 模拟按键，如 "Enter"、"Back"、"Home"
agent.ai_keyboard_press("Enter")
agent.ai_keyboard_press("Back")

agent.ai_pinch(
    direction: str,                 # "in"（缩小）| "out"（放大）
    locate: str = None,
    distance: int = None,
    duration: int = None,
) -> None
# 捏合/张开手势
agent.ai_pinch("out", locate="地图区域")
```

### Utility — 断言与数据提取

```python
agent.ai_assert(assertion: str) -> None
# AI 视觉断言，失败时抛出 AssertionError
agent.ai_assert("当前页面显示用户名 testuser")
agent.ai_assert("购物车商品数量为 3")

agent.ai_wait_for(assertion: str, timeout_ms: int = 15000) -> None
# 等待条件满足，超时抛出异常
agent.ai_wait_for("加载动画消失", timeout_ms=10000)
agent.ai_wait_for("弹窗出现", timeout_ms=5000)

agent.ai_query(data_demand) -> Any
# 从当前屏幕提取结构化数据
products = agent.ai_query({"name": "string", "price": "number", "in_stock": "boolean"})
title = agent.ai_query("页面标题文字")

agent.ai_ask(prompt: str) -> Any
# 自由问答，返回 AI 对当前屏幕的理解
answer = agent.ai_ask("当前页面的主要功能是什么？")

agent.ai_boolean(prompt: str) -> bool
# 返回布尔值
is_logged_in = agent.ai_boolean("用户是否已登录？")

agent.ai_number(prompt: str) -> Any
# 返回数字
count = agent.ai_number("购物车中的商品数量")

agent.ai_string(prompt: str) -> str
# 返回字符串
username = agent.ai_string("当前登录的用户名")

agent.ai_locate(locate_prompt: str) -> Any
# 定位元素，返回位置信息（坐标等）
pos = agent.ai_locate("确认按钮")
```

### 原生 ADB

```python
agent.run_adb_shell(command: str, timeout_ms: int = None) -> str
# 执行 adb shell 命令，返回输出文本；timeout_ms 单位为毫秒
output = agent.run_adb_shell("dumpsys activity top | grep 'ACTIVITY'")
output = agent.run_adb_shell("pm list packages | grep com.example", timeout_ms=5000)
```

---

## 异常处理

```python
from midscene_android import MidsceneRPCError

try:
    agent.ai_assert("某个不存在的条件")
except AssertionError as e:
    # AI 断言失败（pass=False），包含失败原因
    print(f"断言失败: {e}")

try:
    agent.ai_action("点击某个按钮")
except MidsceneRPCError as e:
    # Node.js 侧报错（如设备断开、ADB 错误）
    print(f"RPC 错误 [code={e.code}]: {e}")
```

| 异常 | 触发场景 |
|------|---------|
| `AssertionError` | `ai_assert()` 条件不满足 |
| `MidsceneRPCError` | Node.js 侧业务错误（ADB 断开、元素找不到等） |
| `MidsceneSetupError` | Node 二进制缺失、npm install 失败、环境变量未配置 |
| `MidsceneNodeServiceError` | Node.js 服务启动失败或意外退出 |
| `MidsceneError` | 使用已 `destroy()` 的 Agent |

---

## 开发者指南

### 本地开发

```bash
git clone <repo>
cd midscene_python

# 安装开发依赖
pip install -e ".[dev]"

# 下载内置 Node 二进制（仅当前平台）
python tools/fetch_node_binaries.py --platform win32-x64   # Windows
python tools/fetch_node_binaries.py --platform linux-x64   # Linux
python tools/fetch_node_binaries.py --platform darwin-arm64  # macOS Apple Silicon
```

### 运行测试

```bash
# 集成测试（无需 Android 设备）
pytest tests/ -m "not device" -v

# 需要真实 Android 设备的测试（需配置好 .env 并连接设备）
pytest tests/ -m device -v -s
```

### 构建发行包

```bash
# 构建当前平台的 wheel + sdist
python tools/build_platform_wheel.py

# 构建指定平台 wheel
python tools/build_platform_wheel.py --platform linux-x64

# 构建全部 5 个平台 wheel + sdist（需要先下载所有 Node 二进制）
python tools/build_platform_wheel.py --all

# dist/ 目录结果示例：
# midscene_android-0.2.0.tar.gz                               ← 源码包
# midscene_android-0.2.0-py3-none-win_amd64.whl               ← Windows
# midscene_android-0.2.0-py3-none-manylinux_2_17_x86_64.whl  ← Linux x64
# midscene_android-0.2.0-py3-none-manylinux_2_17_aarch64.whl ← Linux ARM
# midscene_android-0.2.0-py3-none-macosx_10_14_x86_64.whl    ← macOS Intel
# midscene_android-0.2.0-py3-none-macosx_11_0_arm64.whl      ← macOS Apple Silicon
```

### 项目结构

```
midscene_android/
├── __init__.py          # 公开 API 入口
├── config.py            # MidsceneConfig（环境变量 / .env 支持）
├── midscene_agent.py    # MidsceneAgent（所有 AI 操作方法）
├── node_service.py      # NodeServiceManager（进程级单例）
├── runtime.py           # Node 二进制管理、npm install、版本缓存
├── exceptions.py        # 异常类
└── _node_driver/
    ├── bin/             # 各平台 Node 二进制（5 平台，wheel 打包时按平台选一）
    ├── npm/             # 内置 npm（用于首次 npm install，无需系统 npm）
    └── service/
        ├── service.js   # Node.js RPC 服务（JSON-RPC 2.0）
        └── package.json # @midscene/android 依赖声明

tests/
├── conftest.py                 # 共享 fixture（dummy_config、singleton 清理、device marker）
├── test_node_service.py        # Node 二进制与服务启动测试
├── test_agent_integration.py   # 集成测试（Level 1/2 无需设备，Level 3 需要设备）
└── test_example_integration.py # 示例集成测试

tools/
├── fetch_node_binaries.py      # 下载 Node 二进制（开发时使用）
└── build_platform_wheel.py     # 构建平台差异化 wheel
```

---

## License

MIT
