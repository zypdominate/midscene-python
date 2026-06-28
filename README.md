# Midscene Python

[![PyPI version](https://img.shields.io/pypi/v/midscene.svg)](https://pypi.org/project/midscene/)
[![Python](https://img.shields.io/pypi/pyversions/midscene.svg)](https://pypi.org/project/midscene/)
[![CI](https://github.com/zypdominate/midscene-python/actions/workflows/ci.yml/badge.svg)](https://github.com/zypdominate/midscene-python/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

将 [Midscene.js](https://github.com/web-infra-dev/midscene) AI 驱动的 UI 自动化能力桥接到 Python 测试框架。

无需自行安装 Node.js；无需维护 UI 选择器——用自然语言描述操作，AI 负责定位和执行。

单一 `midscene` 包，工程代码按模块划分，同时支持：

| 模块 | 能力 | 入口 |
|------|------|------|
| `agent_android` | Android 自动化（ADB + `@midscene/android`） | `from midscene import MidsceneAgent` |
| `agent_web` / `drivers` | 网页自动化（Puppeteer + `@midscene/web`，预留 Playwright/Bridge） | `from midscene import MidsceneWebAgent` |
| 共享底层 | 配置、异常、Node 运行时桥接、RPC 服务管理、`BaseAgent` | `from midscene import MidsceneConfig, BaseAgent` |

> 本 README 以 Android 为主线说明；网页用法见 [网页自动化](#网页自动化)。

---

## 目录

- [架构](#架构)
- [安装](#安装)
- [快速开始](#快速开始)
- [网页自动化](#网页自动化)
- [pytest 插件](#pytest-插件)
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
midscene（共享底层）
├── Node 运行时（首次使用自动下载到 ~/.midscene/node_runtime/，android/web 共享）
├── NodeServiceManager（按平台 ServiceSpec 多实例：android / web 各一个 Node 进程）
└── BaseAgent（跨平台 ai_action / ai_tap / ai_query / ai_assert …）
        │
        ├── MidsceneAgent     → @midscene/android → ADB → Android 设备 / 模拟器
        └── MidsceneWebAgent  → @midscene/web → Puppeteer → Chromium 浏览器
```

**关键特性：**

- 每个平台的 Python 进程与其 Node 进程 1:1；同平台多个 Agent 共享一个 Node 进程（通过 sessionId 隔离）
- android 与 web 各自拥有独立的 Node 服务与缓存命名空间，可并存
- Python 进程退出时 Node 子进程自动清理
- 无需系统已安装 `node` 或 `npm`

---

## 安装

```bash
pip install midscene
```

> **首次使用**：会按需自动执行 `npm install`（Android 用 `@midscene/android`，Web 用 `@midscene/web` + puppeteer），需要访问 npm registry。只有实际使用的平台才会触发对应安装。

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

推荐使用 `.env` 文件（存放项目根目录，自动加载，无需 `export`）：

```ini
# .env
MIDSCENE_MODEL_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/
MIDSCENE_MODEL_API_KEY=ark-your-api-key
MIDSCENE_MODEL_NAME=doubao-seed-1-6-vision-250815
MIDSCENE_MODEL_FAMILY=doubao-seed
```

### 2. 编写测试

```python
from midscene import MidsceneAgent

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
from midscene import MidsceneAgent

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

## 网页自动化

网页自动化由 `MidsceneWebAgent` 提供，默认使用 Puppeteer 驱动（首次使用会自动安装 `@midscene/web` 与 puppeteer，并下载 Chromium）。

```python
from midscene import MidsceneWebAgent

agent = MidsceneWebAgent("https://example.com")
agent.ai_action("在搜索框输入 midscene 并回车")
agent.ai_assert("搜索结果已展示")
agent.destroy()
```

选择 / 配置驱动：

```python
from midscene import MidsceneWebAgent, PuppeteerDriver

# 有头模式 + 指定视口
agent = MidsceneWebAgent(
    "https://example.com",
    driver=PuppeteerDriver(headless=False, viewport={"width": 1440, "height": 900}),
)

# 连接已运行的 Chrome（chrome --remote-debugging-port=9222）
agent = MidsceneWebAgent(driver=PuppeteerDriver(cdp_endpoint="http://127.0.0.1:9222"))
```

网页专有方法：`goto(url)`、`new_tab(url=None)`、`set_viewport(width, height)`、`ai_hover(locate)`，以及全部跨平台 `ai_*` 方法。`PlaywrightDriver` / `BridgeDriver` 为占位，后续接入。

---

## pytest 插件

安装 `midscene` 后，pytest 会**自动加载**内置插件，无需额外配置。提供 `midscene_agent`（Android）与 `midscene_web_agent`（Web）两个 fixture。

### 内置 fixture：`midscene_agent`

无需在 `conftest.py` 中自行声明 fixture，直接在测试函数参数中使用即可：

```python
# test_my_app.py
import pytest

@pytest.mark.device
def test_login(midscene_agent):
    midscene_agent.ai_action("点击登录按钮")
    midscene_agent.ai_input("用户名", "testuser")
    midscene_agent.ai_input("密码", "Test@123456")
    midscene_agent.ai_assert("登录成功，显示用户首页")
```

设备 ID 解析顺序：

| 优先级 | 来源 |
|--------|------|
| 1 | `--midscene-device` CLI 参数 |
| 2 | `MIDSCENE_DEVICE_ID` 环境变量 |
| 3 | `ANDROID_DEVICE_ID` 环境变量 |
| 4 | 自动选取第一台已连接设备 |

### 失败自动截图与报告

使用 `midscene_agent` 的测试用例失败时，插件会自动：

1. 调用 `get_screenshot()` 将当前屏幕保存为 PNG。
2. 调用 `get_report_file()` 获取 Midscene HTML 报告路径。
3. 将上述路径附加到 pytest 报告的 sections（终端 `-v` 输出和 pytest-html 均可见）。

截图保存路径示例：

```
midscene_artifacts/tests__test_login__test_login.png
```

### CLI 选项

```bash
# 指定设备
pytest --midscene-device emulator-5556 tests/ -m device

# 自定义截图保存目录
pytest --midscene-artifact-dir /tmp/ci_artifacts tests/ -m device
```

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--midscene-device` | 自动检测 | `midscene_agent` 使用的 Android 设备 ID |
| `--midscene-url` | 无 | `midscene_web_agent` 的起始页面 URL（或 `MIDSCENE_WEB_URL`） |
| `--midscene-headed` | 关闭 | `midscene_web_agent` 以有头模式启动浏览器 |
| `--midscene-artifact-dir` | `midscene_artifacts/` | 失败截图与报告的保存目录 |

`midscene_web_agent` 用法：

```python
def test_search(midscene_web_agent):
    midscene_web_agent.goto("https://example.com")
    midscene_web_agent.ai_action("点击更多信息链接")
    midscene_web_agent.ai_assert("页面已跳转")
```

---

## 配置

### MidsceneConfig

可以通过环境变量、`.env` 文件或代码直接传入配置：

```python
from midscene import MidsceneAgent, MidsceneConfig

# 方式一：从 .env / 环境变量自动读取（推荐）
agent = MidsceneAgent("emulator-5556")

# 方式二：代码直接传入
config = MidsceneConfig(
    base_url="https://ark.cn-beijing.volces.com/api/v3/",
    api_key="ark-your-api-key",
    model_name="doubao-seed-1-6-vision-250815",
    model_family="doubao-seed",
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
| `MIDSCENE_MODEL_FAMILY` | ❌ | 模型家族 |

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
from midscene import MidsceneRPCError

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
git clone https://github.com/zypdominate/midscene-python
cd midscene_python

# 以可编辑方式安装（含开发工具）
pip install -e ".[dev]"

# 首次运行测试会自动下载 Node 到 ~/.midscene/node_runtime/
```

根目录 `pyproject.toml` 同时承载打包元数据与 ruff / pytest / mypy 配置，并把 `src` 加入 `pythonpath`，因此在根目录直接执行 `pytest` / `ruff check .` / `mypy` 即可。

### 运行测试

```bash
# 全部非真机/非浏览器测试（首次需联网下载 Node + npm 依赖）
pytest -m "not device and not web" -v

# 需要真实 Android 设备的测试（需配置好 .env 并连接设备）
pytest tests/ -m device -v -s

# 需要真实浏览器 + AI Key 的网页测试
pytest tests/ -m web -v -s
```

### 构建与发布

```bash
# 构建 py3-none-any wheel + sdist
python tools/build_wheel.py --clean

# 检查并上传 PyPI
python tools/upload_pypi.py --dry-run
python tools/upload_pypi.py --require-all --yes
```

### 项目结构

```
src/midscene/
├── __init__.py            # 顶层导出（MidsceneAgent / MidsceneWebAgent / 驱动 / 异常 …）
├── config.py              # MidsceneConfig（环境变量 / .env 支持）
├── exceptions.py
├── node_bootstrap.py      # 首次运行从 nodejs.org 下载 Node/npm
├── runtime.py             # ServiceSpec + 按平台参数化的 npm install / 缓存
├── node_service.py        # NodeServiceManager（按 spec 名称多实例）
├── base_agent.py          # BaseAgent（跨平台 ai_* 方法 + RPC）
├── agent_android.py       # MidsceneAgent(BaseAgent) + 设备/系统方法
├── agent_web.py           # MidsceneWebAgent(BaseAgent) + goto/new_tab/set_viewport
├── drivers.py             # PuppeteerDriver（实现）+ Playwright/Bridge（占位）
├── _pytest_plugin.py      # midscene_agent / midscene_web_agent fixture + pytest11 入口
├── _pytest_support.py     # pytest 插件共享逻辑（失败截图/报告）
├── py.typed
└── _node_driver/
    ├── android/service/   # package.json(@midscene/android) + service.js
    └── web/service/       # package.json(@midscene/web + puppeteer) + service.js

# 运行时缓存（不在 pip 包内，android/web 共享 Node 运行时）：
# ~/.midscene/node_runtime/          ← Node + npm
# ~/.midscene/android/node_service/  ← npm install @midscene/android
# ~/.midscene/web/node_service/      ← npm install @midscene/web + puppeteer

tests/                     # Android + Web 测试集中在根目录
tools/
├── build_wheel.py         # 构建 py3-none-any wheel + sdist
└── upload_pypi.py         # 检查 dist/ 并上传 PyPI
```

---

## License

MIT
