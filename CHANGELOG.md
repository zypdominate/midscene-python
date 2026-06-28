# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
并采用 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-06-28

首个以 **`midscene`** 名义发布到 PyPI 的版本：Android 与 Web 自动化合并为单一包，内部按模块划分，同时新增网页自动化能力。

### 新增

- **网页自动化**：`MidsceneWebAgent(BaseAgent)`，支持 `goto` / `new_tab` / `set_viewport` / `ai_hover` 及全部跨平台 `ai_*` 方法。
- **Web 驱动抽象**（`drivers.py`）：默认 `PuppeteerDriver`（`@midscene/web` + puppeteer）；`PlaywrightDriver` / `BridgeDriver` 占位预留。
- **共享底层模块**（`src/midscene/` 扁平布局）：`BaseAgent`、`ServiceSpec` 参数化运行时、进程级多实例 `NodeServiceManager`、pytest 共享支持（`_pytest_support`）。
- **pytest 插件扩展**：合并为单一入口 `midscene._pytest_plugin`，新增 `midscene_web_agent` fixture 及 `--midscene-url` / `--midscene-headed` CLI 选项。
- 单 wheel 同时打包 Android / Web 两套 Node 服务源码（`_node_driver/android/service`、`_node_driver/web/service`），npm 依赖仍按平台懒安装。

### 变更

- **包名与导入路径（破坏性）**：PyPI 包名由 `midscene-android` 改为 **`midscene`**（`pip install midscene`，`import midscene`）；`from midscene_android import ...` 不再可用。
- **运行时缓存目录**：由 `~/.midscene_android/` 统一迁移至 `~/.midscene/`（`node_runtime/` 共享，`android/` / `web/` 各自 `node_service/`）。
- **`NodeServiceManager`**：由全局单例改为按 `ServiceSpec.name` 键控的多实例注册表，Android 与 Web 可并存、互不干扰。
- 构建/发布脚本（`build_wheel.py` / `upload_pypi.py`）回归单包；CI 合并为单 `test` 矩阵 + `build` 任务，缓存路径更新为 `~/.midscene`。
- 移除 monorepo 结构（`packages/midscene-core` / `midscene-android` / `midscene-web`）及 Android 兼容 shim 模块。

### 修复

- **`.env` 加载路径**：`MidsceneConfig` 改用 `find_dotenv(usecwd=True)` 从业务工程工作目录向上查找 `.env`，修复 pip 安装后在 pytest 等场景下配置变量读不到的问题（裸 `load_dotenv()` 会从 `site-packages/midscene/` 向上搜索）。
- 创建 `MidsceneConfig` 时按当前 cwd 重新加载 `.env`，避免仅在 `import midscene` 时加载失败。

### 文档

- README 更新为单包说明，补充 Web 自动化用法、pytest 双 fixture 及 `src/midscene/` 项目结构。
- CHANGELOG 记录包合并与 Web 新特性。

## [0.0.4] - 2026-06-20

### 新增

- `MidsceneConfigError` 异常类型，并通过包顶层导出。
- 打包类型标记 `py.typed`（PEP 561），消费者可获得类型提示。
- `LICENSE`（MIT）文件，并在 `pyproject.toml` 中通过文件引用声明。
- `CONTRIBUTING.md` 贡献指南。
- PyPI 包上传脚本（`tools/upload_pypi.py`）。
- 构建临时文件自动清理功能。

### 变更

- 异常处理与配置验证机制重构：配置类校验逻辑集中化，错误语义更清晰。
- 测试模块导入路径调整，与 `src/` 布局保持一致。
- 项目配置与依赖管理更新（`pyproject.toml`、开发工具链）。
- 代码格式化（`ruff format`）。

### 修复

- **stdout 管道死锁**：Node 服务的 stdout 现在会被独立线程持续消费，避免长会话中
  `console.log` 写满管道导致 Node 进程阻塞。
- **RPC 传输层异常包装**：`NodeServiceManager.rpc` 不再裸泄露 `requests` 异常，统一包装为
  `MidsceneNodeServiceError`；当 Node 进程崩溃时自动重启一次并重试。
- **配置异常语义**：缺少必填环境变量时抛出新的 `MidsceneConfigError`（继承自
  `MidsceneSetupError`），不再抛 `OSError`。
- `runtime.py` 移除了 `NPM_DONE_FLAG` / `VERSION_FILE` 的重复定义。
- Node 服务：`ping` 返回的版本号改为从 `package.json` 读取；设备日志使用 `JSON.stringify`；
  日志文件新增 5MB 大小上限并自动轮转。

### 文档

- 添加 `RELEASE_GUIDE.md` 发布指南，说明运行时 Node Bootstrap 设计。
- 更新 README 文档注释与说明。

## [0.0.3] - 2026-06-16

首个发布到 PyPI 的版本：通过 Midscene.js 将 AI 驱动的 Android 自动化能力桥接到 Python。

### 新增

- **运行时 Node Bootstrap**（`node_bootstrap` 模块）：首次运行时从 nodejs.org 自动下载
  Node.js 与 npm，无需用户预装 Node 环境。
- `build_wheel.py` 构建纯 Python wheel，分发包不再捆绑 Node 二进制，显著减小体积。
- `tests/conftest.py`：测试前自动预下载 Node.js 运行时。
- `fetch_node_binaries.py` 复用 bootstrap 下载逻辑，供开发环境使用。

### 变更

- 项目模块迁移至 `src/midscene_android/` 标准布局。
- Node.js 服务源码目录由 `js` 重命名为 `service`。
- Node.js 运行时环境与依赖管理重构（`_node_driver` → `_runtime` 目录结构）。
- 统一模块导入路径。
- 源码包格式由 `.tar` 改为 `.tar.gz`（`MANIFEST.in` 排除 Node 二进制）。
- RPC 调用逻辑统一到 `NodeServiceManager._rpc` 方法，`MidsceneAgent` 初始化与清理逻辑简化。

### 文档

- 更新 AI 模型配置示例与 README 说明。

## [0.0.2] - 2026-06-03

版本号重置后的内部里程碑（2025-05-27 ~ 2026-06-03），聚焦核心能力稳定与测试完善。

### 新增

- `MidsceneAgent` 支持上下文管理器（`with` 语句），退出时自动清理会话。
- 改进 ADB 命令处理逻辑。
- 优化环境变量加载（`python-dotenv`）。
- 支持可选设备 ID，新增设备控制功能（导航、应用管理、截图、YAML 执行、报告获取）。
- 增强 Android 设备服务：内置日志、`getConnectedDevices`、AI 操作上下文支持。
- 集成测试配置改为环境变量读取，简化测试维护。

### 变更

- 版本号重置为 `0.0.2`，为 PyPI 首发做准备。
- `NodeServiceManager` 接管全部 RPC 调用，`MidsceneAgent` 职责进一步精简。
- 重构 Android 集成测试用例。

### 修复

- `MidsceneError` 错误处理逻辑修正。
- `aiScroll` 滚动操作修复。
- `aiScroll`、`aiPinch` 参数处理：新增 `cleanOptions` 过滤 `null`/`undefined`，
  防止 Agent 参数校验失败。
- `aiInput` 参数传递错误（`text` → `value`）。
- Android 设备连接检测逻辑修复。
- 集成测试用例修复。

### 文档

- 更新滚动功能（`aiScroll`）文档说明。

## [0.0.1] - 2025-05-20

项目初始版本。

### 新增

- **核心架构**：Python 通过 JSON-RPC 2.0 与 Node.js 微服务通信，桥接 Midscene.js
  Android 自动化能力。
- `MidsceneAgent`：AI 驱动操作（`ai_action`、`ai_query`、`ai_assert` 等）的 Python 入口。
- `NodeServiceManager`：Node.js 子进程生命周期管理（单例、自动启动、退出清理）。
- Node.js 服务（`service.js`）：ADB 路径解析、设备连接、AI 操作代理。
- 缓存版本管理机制：Node 依赖变更时自动触发 `npm install`。
- 构建脚本与跨平台 wheel 构建支持（`build_wheel.py`）。
- 模型配置环境变量（`MIDSCENE_MODEL_*`）。
- 完整集成测试套件（`NodeServiceManager`、`MidsceneAgent` 真实 HTTP 通信）。

### 变更

- 移除 Mixin 模式，改为直接使用 `Agent` 类。
- 重构 AI 操作方法命名与参数配置。
- 简化配置类与 Node.js 服务 Android 设备管理逻辑。
- Node.js 服务管理模块结构重构（`node_service.py`、`runtime.py`）。
- 优化 Agent 会话管理与错误处理。

### 文档

- 初始 README 与项目说明。

[0.1.0]: https://github.com/zypdominate/midscene-python/compare/v0.0.4...v0.1.0

[0.0.4]: https://github.com/zypdominate/midscene-python/compare/v0.0.3...v0.0.4

[0.0.3]: https://github.com/zypdominate/midscene-python/releases/tag/v0.0.3

[0.0.2]: https://github.com/zypdominate/midscene-python/compare/v0.0.1...v0.0.2

[0.0.1]: https://github.com/zypdominate/midscene-python/releases/tag/v0.0.1
