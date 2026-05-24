"""Midscene 配置。"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class MidsceneConfig:
    """Midscene AI 模型配置。

    最小配置容器，默认从环境变量或 `.env` 读取。"""

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    model_family: Optional[str] = None

    def __post_init__(self) -> None:
        load_dotenv()
        self.base_url = self.base_url or os.environ.get("MIDSCENE_MODEL_BASE_URL")
        self.api_key = self.api_key or os.environ.get("MIDSCENE_MODEL_API_KEY")
        self.model_name = self.model_name or os.environ.get("MIDSCENE_MODEL_NAME")
        self.model_family = self.model_family or os.environ.get("MIDSCENE_MODEL_FAMILY") or "openai"

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
            raise OSError(
                "Missing required environment variables for MidsceneConfig: "
                + ", ".join(missing)
            )

    @classmethod
    def from_env(cls) -> MidsceneConfig:
        return cls()

    def to_node_env(self) -> dict[str, str]:
        return {
            "MIDSCENE_MODEL_BASE_URL": self.base_url,
            "MIDSCENE_MODEL_API_KEY": self.api_key,
            "MIDSCENE_MODEL_NAME": self.model_name,
            "MIDSCENE_MODEL_FAMILY": self.model_family,
        }
