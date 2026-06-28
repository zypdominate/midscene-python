"""Shared pytest fixtures for midscene tests."""

from __future__ import annotations

from typing import Any, Generator

import pytest

from midscene import node_bootstrap, MidsceneConfig


@pytest.fixture(scope="session", autouse=True)
def ensure_node_runtime_once() -> None:
    """Session 级：首次测试前下载 Node/npm 到 ~/.midscene/node_runtime/。"""
    node_bootstrap.ensure_node_runtime()


@pytest.fixture(scope="module")
def fixture_dummy_config() -> Generator[MidsceneConfig, Any, None]:
    """Node 服务本身启动不需要真实 AI Key，用占位值即可。"""
    config = MidsceneConfig(
        base_url="https://placeholder.example.com/v1",
        api_key="dummy-key-for-node-service-test",
        model_name="placeholder-model",
        model_family="openai",
    )
    yield config
