"""midscene_android 异常类。"""


class MidsceneError(Exception):
    """midscene_android 的基础异常。"""


class MidsceneNodeServiceError(MidsceneError):
    """Node.js 服务启动或通信失败。"""


class MidsceneSetupError(MidsceneError):
    """初始化失败（如 Node 二进制缺失、npm install 失败）。"""


class MidsceneConfigError(MidsceneSetupError):
    """配置缺失或无效（如必填环境变量未设置）。"""


class MidsceneRPCError(MidsceneError):
    """Node.js 侧返回的业务错误（RPC level error）。"""

    def __init__(self, message: str, code: int = -1, stack: str | None = None):
        super().__init__(message)
        self.code = code
        self.stack = stack

    def __str__(self) -> str:
        base = super().__str__()
        if self.stack:
            return f"{base}\n\nNode.js stack:\n{self.stack}"
        return base
