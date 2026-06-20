# 贡献指南

感谢你愿意为 midscene-android 做出贡献！本文档说明如何参与开发。

## 开发环境

```bash
git clone https://github.com/zypdominate/midscene-python.git
cd midscene-python

# 安装开发依赖
pip install -e ".[dev]"
```

首次运行测试会自动从 nodejs.org 下载 Node 运行时到 `~/.midscene_android/node_runtime/`，
并执行 `npm install @midscene/android`，需要联网，约 1～2 分钟。

## 代码规范

提交前请确保通过以下检查：

```bash
# 代码风格与静态检查
ruff check .
ruff format --check .

# 类型检查
mypy

# 测试（无需 Android 设备；首次需联网）
pytest tests/ -m "not device" -v
```

- 代码风格遵循 `ruff`（配置见 `pyproject.toml`），行宽 88。
- 公共 API 请补充类型标注；本包已声明 `py.typed`。
- 注释解释“为什么”，避免复述代码本身。

## 测试说明

测试分三个层次（详见 `tests/test_agent_integration.py` 顶部说明）：

- **Level 1 / 2**：无需 Android 设备，验证缓存逻辑与 Node 服务生命周期。
- **Level 3**（`@pytest.mark.device`）：需要真机/模拟器 + 有效 AI Key，默认在 CI 中跳过。

运行需要设备的测试：

```bash
pytest tests/ -m device -v -s
```

## 提交信息

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 风格，例如：

```
fix(node-service): 修复 stdout 管道写满导致的阻塞
feat(cli): 新增 doctor 自检命令
docs(readme): 补充配置说明
```

## 提交 Pull Request

1. 从 `master` 创建特性分支。
2. 保证 lint / 类型检查 / 非 device 测试通过。
3. 在 `CHANGELOG.md` 的「未发布」区块记录你的改动。
4. 提交 PR 并清晰描述动机与影响范围。

## 发布流程

发布到 PyPI 的完整步骤见 [RELEASE_GUIDE.md](RELEASE_GUIDE.md)。
