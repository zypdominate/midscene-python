"""Shared pytest fixtures for midscene-android."""

from __future__ import annotations

import pytest

from midscene_android import node_bootstrap


@pytest.fixture(scope="session", autouse=True)
def ensure_node_runtime_once() -> None:
    """Session 级：首次测试前下载 Node/npm 到 ~/.midscene_android/node_runtime/。"""
    node_bootstrap.ensure_node_runtime()
