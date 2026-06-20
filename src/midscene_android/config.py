"""Midscene 配置。"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

from .exceptions import MidsceneConfigError

# 模块加载时执行一次，override=False 保留进程中已有的环境变量
load_dotenv(override=False)


@dataclass
class MidsceneConfig:
    """Midscene AI 模型配置。

    最小配置容器，默认从环境变量或 `.env` 读取。"""

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    model_family: Optional[str] = None
    ai_action_context: Optional[str] = None

    def __post_init__(self) -> None:
        self.base_url = self.base_url or os.environ.get("MIDSCENE_MODEL_BASE_URL")
        self.api_key = self.api_key or os.environ.get("MIDSCENE_MODEL_API_KEY")
        self.model_name = self.model_name or os.environ.get("MIDSCENE_MODEL_NAME")
        self.model_family = self.model_family or os.environ.get("MIDSCENE_MODEL_FAMILY") or "openai"
        self.ai_action_context = self.ai_action_context or os.environ.get("MIDSCENE_AI_ACTION_CONTEXT")

        missing = [
            env_var
            for value, env_var in (
                (self.base_url, "MIDSCENE_MODEL_BASE_URL"),
                (self.api_key, "MIDSCENE_MODEL_API_KEY"),
                (self.model_name, "MIDSCENE_MODEL_NAME"),
            )
            if not value
        ]
        if missing:
            raise MidsceneConfigError(
                "Missing required environment variables for MidsceneConfig: "
                + ", ".join(missing)
            )

    @classmethod
    def from_env(cls) -> "MidsceneConfig":
        return cls()

    def to_node_env(self) -> dict[str, str]:
        # __post_init__ 已校验必填项，此处收窄 Optional 以满足 dict[str, str]。
        assert self.base_url is not None
        assert self.api_key is not None
        assert self.model_name is not None
        assert self.model_family is not None
        env: dict[str, str] = {
            "MIDSCENE_MODEL_BASE_URL": self.base_url,
            "MIDSCENE_MODEL_API_KEY": self.api_key,
            "MIDSCENE_MODEL_NAME": self.model_name,
            "MIDSCENE_MODEL_FAMILY": self.model_family,
        }
        if self.ai_action_context:
            env["MIDSCENE_AI_ACTION_CONTEXT"] = self.ai_action_context
        return env
