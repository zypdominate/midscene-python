"""
AI 模型配置管理。

支持的模型家族（model_family）：
  - openai    : OpenAI GPT 系列
  - qwen      : 阿里通义千问视觉模型
  - doubao    : 字节豆包视觉模型
  - gemini    : Google Gemini 系列
  - claude    : Anthropic Claude 系列（需支持 vision）

model_family 对应 Midscene 的 MIDSCENE_MODEL_FAMILY 环境变量。
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MidsceneConfig:
    """
    Midscene AI 模型配置。

    api_key 支持明文传入，内部统一以 base64 存储，
    传递给 Node.js 进程时再解码为明文注入环境变量。

    Examples::

        # 直接传明文 key
        config = MidsceneConfig(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-xxxxxx",
            model_name="qwen-vl-max",
            model_family="qwen",
        )

        # 也可以传 base64 编码的 key（框架内部自动识别）
        config = MidsceneConfig(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="c2steHh4eHh4",   # base64("sk-xxxxxx")
            model_name="qwen-vl-max",
            model_family="qwen",
        )

        # 从环境变量读取
        config = MidsceneConfig.from_env()
    """

    base_url: str
    api_key: str
    model_name: str
    model_family: str = "openai"
    # 可选：截图缩放比例，不建议手动调整，透传给 AndroidDevice
    screenshot_resize_scale: Optional[float] = None

    def __post_init__(self) -> None:
        # 统一转为 base64 存储
        self._api_key_b64 = _to_base64(self.api_key)

    # ── 工厂方法 ──────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "MidsceneConfig":
        """
        从环境变量读取配置，变量名与 Midscene 官方一致：

          MIDSCENE_MODEL_BASE_URL
          MIDSCENE_MODEL_API_KEY
          MIDSCENE_MODEL_NAME
          MIDSCENE_MODEL_FAMILY
        """
        required = {
            "base_url": "MIDSCENE_MODEL_BASE_URL",
            "api_key": "MIDSCENE_MODEL_API_KEY",
            "model_name": "MIDSCENE_MODEL_NAME",
        }
        kwargs: dict = {}
        missing = []
        for attr, env_var in required.items():
            val = os.environ.get(env_var)
            if not val:
                missing.append(env_var)
            else:
                kwargs[attr] = val
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables for MidsceneConfig: "
                f"{', '.join(missing)}"
            )
        kwargs["model_family"] = os.environ.get("MIDSCENE_MODEL_FAMILY", "openai")
        return cls(**kwargs)

    @classmethod
    def from_dict(cls, d: dict) -> "MidsceneConfig":
        return cls(
            base_url=d["base_url"],
            api_key=d["api_key"],
            model_name=d["model_name"],
            model_family=d.get("model_family", "openai"),
            screenshot_resize_scale=d.get("screenshot_resize_scale"),
        )

    # ── 内部接口 ──────────────────────────────────────────────────────────────

    def to_node_env(self) -> dict[str, str]:
        """
        转换为注入 Node.js 子进程的环境变量字典。
        api_key 在此处解码为明文。
        """
        env: dict[str, str] = {
            "MIDSCENE_MODEL_BASE_URL": self.base_url,
            "MIDSCENE_MODEL_API_KEY": _from_base64(self._api_key_b64),
            "MIDSCENE_MODEL_NAME": self.model_name,
            "MIDSCENE_MODEL_FAMILY": self.model_family,
        }
        return env


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def _is_base64(s: str) -> bool:
    """判断字符串是否已经是 base64 编码（宽松判断）。"""
    if not s:
        return False
    try:
        decoded = base64.b64decode(s, validate=True)
        # 重新编码后与原始值相同才认为是 base64
        return base64.b64encode(decoded).decode() == s
    except Exception:
        return False


def _to_base64(s: str) -> str:
    """若已经是 base64 则原样返回，否则编码。"""
    if _is_base64(s):
        return s
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _from_base64(s: str) -> str:
    """base64 解码为明文。"""
    return base64.b64decode(s).decode("utf-8")