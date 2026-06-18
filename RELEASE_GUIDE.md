# midscene-android 发布指南

本文档描述 **本项目** 从构建到上传 PyPI 的完整流程。

> PyPI 包**不含** Node 二进制与 npm（避免 100MB 限制）。用户 `pip install` 后，**首次运行**会自动从 nodejs.org 下载到 `~/.midscene_android/node_runtime/`。

---

## 运行时 Node Bootstrap 设计

解释“为什么发布流程与普通 Python 包不同”。

### 1) 背景与约束

- PyPI 单文件默认上限为 **100 MB**
- Node 可执行文件（单平台约 80MB）+ npm 会导致 wheel/sdist 超限
- 因此改为：**包内仅放 Python 代码 + Node service 源码**，Node/npm 在运行时首次下载

### 2) 当前运行时架构

- pip 包内仅保留：
  - `src/midscene_android/_node_driver/service/package.json`
  - `src/midscene_android/_node_driver/service/service.js`
- 首次运行自动准备：
  - `~/.midscene_android/node_runtime/`：Node + npm
  - `~/.midscene_android/node_service/`：`npm install @midscene/android` 的缓存结果

### 3) 启动链路

1. `pip install midscene-android`
2. 首次调用 `MidsceneAgent` / `ensure_node_service()`
3. `node_bootstrap.ensure_node_runtime()`：
   - 若缓存存在：直接复用
   - 若本地开发目录已预填 `_node_driver`：优先 seed 到缓存
   - 否则从 nodejs.org 下载并解压
4. 执行 `npm install --omit=dev`，启动 Node RPC 服务

### 4) 发布与运维影响

- 发布产物固定为：**1 个 `py3-none-any.whl` + 1 个 `sdist`**
- `tools/upload_pypi.py --require-all` 会校验该组合和 100MB 限制
- 首次运行要求网络可达：
  - nodejs.org（下载 Node）
  - registry.npmjs.org（安装 `@midscene/android` 依赖）
- 离线场景可预热：
  - 先在联网环境准备 `~/.midscene_android/node_runtime/` 与 `~/.midscene_android/node_service/`
  - 或使用 `tools/fetch_node_binaries.py` 预填开发目录，再 seed 到缓存

---

## 一、准备工作

### 1. PyPI 账号与 Token

- 注册 [PyPI](https://pypi.org/account/register/) 并完成邮箱验证
- 在 [API Token 管理页](https://pypi.org/manage/account/token/) 创建 Token（格式 `pypi-AgE...`）

### 2. 配置认证（推荐）

创建 `~/.pypirc`（Windows: `%USERPROFILE%\.pypirc`）：

```ini
[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = pypi-你的完整Token

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-你的TestPyPIToken
```

也可用环境变量：`TWINE_USERNAME=__token__`、`TWINE_PASSWORD=pypi-...`

### 3. 安装开发依赖

```bash
uv sync --extra dev
# 或
pip install -e ".[dev]"
```

---

## 二、发布前检查

每次发布新版本：

1. **更新版本号** — `pyproject.toml` 的 `[project].version`
2. **同步 Node 服务版本**（如有变更）— `src/midscene_android/_node_driver/service/package.json`
3. **运行测试**（无需设备，首次需联网下载 Node）：

   ```bash
   pytest tests/ -m "not device" -v
   ```

4. **提交并打 tag**（可选但推荐）：

   ```bash
   git add .
   git commit -m "Release v0.0.3"
   git tag v0.0.3
   ```

---

## 三、构建发行包

```bash
python tools/build_wheel.py --clean
```

产物为 **1 个 py3-none-any wheel + sdist**，体积通常各 < 5 MB。

### dist/ 预期产物（以 v0.0.3 为例）

```
dist/
├── midscene_android-0.0.3-py3-none-any.whl   # 全平台通用
└── midscene_android-0.0.3.tar.gz             # 源码包
```

`upload_pypi.py` 会在上传前检查单文件不超过 100 MB。

---

## 四、上传到 PyPI

```bash
# 1. dry-run
python tools/upload_pypi.py --dry-run

# 2. 正式发布（要求 sdist + 1 个 py3-none-any wheel）
python tools/upload_pypi.py --require-all --yes

# 3. TestPyPI
python tools/upload_pypi.py --require-all --repository testpypi --token pypi-...
```

认证未配置时脚本会提前报错并说明如何设置 `.pypirc` 或 `--token`。

---

## 五、发布后验证

```bash
python -m venv .venv-release-test
# Linux/macOS:
source .venv-release-test/bin/activate
# Windows:
# .\.venv-release-test\Scripts\activate

pip install midscene-android
pytest tests/ -m "not device" -v
```

首次运行测试或 import 会下载 Node（~80MB，需访问 nodejs.org）。

PyPI：https://pypi.org/project/midscene-android/

---

## 六、完整发布清单

```bash
# 1. 更新 pyproject.toml 版本号
# 2. pytest tests/ -m "not device" -v
# 3. python tools/build_wheel.py --clean
# 4. python tools/upload_pypi.py --dry-run
# 5. python tools/upload_pypi.py --require-all --yes
# 6. git push origin main && git push origin v0.0.3
```

---

## 七、FAQ

**Q: 400 File too large？**

- 旧版 wheel 打包了 Node/npm。确认 `pyproject.toml` 的 `package-data` 仅含 `_node_driver/service/*`，重新 `build_wheel.py --clean`。

**Q: 403 Forbidden？**

- 邮箱未验证、Token 错误，或用户名不是 `__token__`。

**Q: 用户离线环境怎么办？**

- 手动预填 `~/.midscene_android/node_runtime/` 与 `~/.midscene_android/node_service/`，或在内网镜像 nodejs.org / npm registry。

**Q: 本地 git 开发还要 fetch_node_binaries 吗？**

- 可选。正常运行会通过 `node_bootstrap` 自动下载到缓存；`tools/fetch_node_binaries.py` 仅用于预填 `src/.../_node_driver/` 方便离线开发。

**Q: 首次下载经常中断（IncompleteRead）怎么办？**

- 属于网络稳定性问题，重试即可；若在公司网络，优先配置可访问 nodejs.org / npm registry 的网络策略。
