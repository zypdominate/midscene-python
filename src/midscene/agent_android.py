"""MidsceneAgent：Python 侧 Android AI 操作接口（基于 midscene 共享底层）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base_agent import BaseAgent
from .config import MidsceneConfig
from .runtime import ServiceSpec

#: Android 平台的 Node 服务定义（缓存在 ~/.midscene/android/node_service/）
ANDROID_SERVICE_SPEC = ServiceSpec(
    name="android",
    dist_name="midscene",
    source_dir=Path(__file__).parent / "_node_driver" / "android" / "service",
    label="@midscene/android",
)


class MidsceneAgent(BaseAgent):
    """AI 驱动的 Android 设备操作接口。

    继承自 :class:`midscene.BaseAgent`，复用全部跨平台 ``ai_*`` 方法，
    并扩展 Android 设备/系统专有操作。
    """

    SERVICE_SPEC = ANDROID_SERVICE_SPEC

    def __init__(
            self,
            device_id: str | None = None,
            config: MidsceneConfig | None = None,
    ):
        self._device_id = device_id
        create_params: dict[str, Any] = {}
        if device_id:
            create_params["deviceId"] = device_id
        super().__init__(config, create_params=create_params)

    def _on_session_created(self, result: dict[str, Any]) -> None:
        self._device_id = result.get("deviceId") or self._device_id

    # ── Android 专有 AI 手势 ──────────────────────────────────────────────────────

    def ai_pinch(
            self,
            direction: str,
            locate: str | None = None,
            distance: int | None = None,
            duration: int | None = None,
    ) -> None:
        self._rpc(
            "aiPinch",
            locate=locate,
            direction=direction,
            distance=distance,
            duration=duration,
        )

    def ai_long_press(
            self,
            locate: str,
            duration: int | None = None,
    ) -> None:
        self._rpc("aiLongPress", locate=locate, duration=duration)

    # ── Device & System Actions ──────────────────────────────────────────────────

    def back(self) -> None:
        """Press the back button."""
        self._rpc("back")

    def home(self) -> None:
        """Press the home button."""
        self._rpc("home")

    def recent_apps(self) -> None:
        """Open the recent apps screen."""
        self._rpc("recentApps")

    def launch_app(self, package_name: str) -> None:
        """Launch an app by its package name."""
        self._rpc("launchApp", packageName=package_name)

    def terminate_app(self, package_name: str) -> None:
        """Terminate an app by its package name."""
        self._rpc("terminateApp", packageName=package_name)

    def run_adb_shell(self, command: str, timeout_ms: int | None = None) -> str:
        """Run an ADB shell command on the connected device.

        Args:
            command: The shell command to execute.
            timeout_ms: Timeout in **milliseconds**. Defaults to None (uses the
                Node service default). Example: ``timeout_ms=5000`` for 5 seconds.

        Returns:
            The stdout output of the command as a string.
        """
        rpc_timeout = max(self.DEFAULT_TIMEOUT, timeout_ms // 1000 + 10) if timeout_ms else self.DEFAULT_TIMEOUT
        result = self._rpc("runAdbShell", timeout=rpc_timeout, command=command, timeoutMs=timeout_ms)
        return result.get("output", "")
