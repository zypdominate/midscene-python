# midscene-android

将 [Midscene.js](https://github.com/web-infra-dev/midscene) AI 驱动的 Android 自动化能力集成到 Python 测试框架的桥接库。

## 架构

```
Python 测试代码
└── device.ai.act("点击登录按钮")
    ↓ JSON-RPC 2.0 (localhost)
Node.js 微服务（进程级单例）
├── 内置 Node 二进制（wheel 中已包含，无需用户安装）
├── @midscene/android（首次使用时 npm install 到缓存目录）
└── ADB → Android 设备
```

## 安装

```bash
pip install midscene-android
```

首次使用时会自动执行 `npm install @midscene/android`（需要访问 npm registry）。

## 快速开始

```python
from midscene_android import MidsceneConfig
from my_framework import MyDevice  # 你的现有框架

config = MidsceneConfig(
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key="your-api-key",          # 支持明文，内部自动 base64 处理
    model_name="qwen-vl-max",
    model_family="qwen",
)

with MyDevice("emulator-5554", midscene_config=config) as device:
    device.ai.act("等待首页加载完成")
    device.ai.tap("登录按钮")
    device.ai.input("用户名输入框", "testuser")
    device.ai.assert_("当前页面显示欢迎信息")
    result = device.ai.query('{"username": str, "level": int}')
```

## API 参考

### Auto Planning
- `device.ai.act(prompt)` — AI 自动规划并执行多步操作

### Instant Actions
- `device.ai.tap(locate)` — 点击元素
- `device.ai.input(locate, text)` — 输入文本
- `device.ai.scroll(locate, direction, distance)` — 滚动
- `device.ai.long_press(locate)` — 长按
- `device.ai.key_press(key)` — 按键
- `device.ai.double_click(locate)` — 双击

### Utility
- `device.ai.assert_(assertion)` — AI 视觉断言
- `device.ai.query(schema)` — 结构化数据提取
- `device.ai.wait_for(condition, timeout_ms)` — 等待条件满足
- `device.ai.open_url(uri)` — 打开页面或 App

## 开发者：如何更新内置 Node 二进制

```bash
python scripts/fetch_node_binaries.py
```