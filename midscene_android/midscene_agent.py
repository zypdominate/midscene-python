"""MidsceneAgent：Python 侧 Android AI 操作接口。"""

import logging
import uuid
from typing import Any, Optional

import requests

from .config import MidsceneConfig
from .exceptions import MidsceneError, MidsceneRPCError
from .node_service import NodeServiceManager

logger = logging.getLogger(__name__)

_TIMEOUT = 120


class MidsceneAgent:
    def __init__(
            self,
            device_id: Optional[str] = None,
            config: Optional[MidsceneConfig] = None,
    ):
        self._device_id = device_id
        self._session_id: Optional[str] = None
        self._closed = False
        self._config = config or MidsceneConfig.from_env()
        self._node_manager = NodeServiceManager(self._config)
        self._node_manager.ensure_started()
        self._port = self._node_manager.port
        self._http_session = requests.Session()

        create_params = {}
        if device_id:
            create_params["deviceId"] = device_id
        if self._config.ai_action_context:
            create_params["aiActionContext"] = self._config.ai_action_context

        result = self._rpc("createSession", **create_params)
        self._session_id = result["sessionId"]
        self._device_id = result.get("deviceId") or device_id

    # ── Context manager ──────────────────────────────────────────────────────────

    def __enter__(self) -> "MidsceneAgent":
        return self

    def __exit__(self, *_: Any) -> None:
        self.destroy()

    # ── Internal RPC ─────────────────────────────────────────────────────────────

    def _rpc(self, method: str, timeout: int = _TIMEOUT, **params: Any) -> dict[str, Any]:
        if self._closed:
            raise MidsceneError("Agent has been destroyed; create a new MidsceneAgent instance")

        if self._session_id is not None and method != "createSession":
            params["sessionId"] = self._session_id

        resp = self._http_session.post(
            f"http://127.0.0.1:{self._port}/rpc",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": method,
                "params": params,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            err = body["error"]
            raise MidsceneRPCError(
                err.get("message", "RPC error"),
                err.get("code", -1),
                err.get("stack"),
            )
        return body.get("result", {})

    # ── AI actions ───────────────────────────────────────────────────────────────

    def ai_action(self, prompt: str) -> None:
        self._rpc("aiAct", prompt=prompt)

    def ai_tap(self, locate: str) -> None:
        self._rpc("aiTap", locate=locate)

    def ai_input(self, locate: str, value: str) -> None:
        self._rpc("aiInput", locate=locate, value=value)

    def ai_clear_input(self, locate: str) -> None:
        self._rpc("aiClearInput", locate=locate)

    def ai_scroll(
            self,
            locate: Optional[str] = None,
            direction: str = "down",
            scroll_type: Optional[str] = None,
            distance: Any = None,
    ) -> None:
        """
        真正决定滚动行为的是后端的 Android 实现。
        当 scroll_type='singleAction' 时，后端忽略 distance 参数，执行固定长度的单次滑动手势，
        因此 distance=500 与 distance=1000 的效果相同。
        """
        if isinstance(distance, str):
            distance_map = {"small": 200, "medium": 400, "large": 600}
            distance_value = distance_map.get(distance, distance)
        else:
            distance_value = distance
        if isinstance(scroll_type, str):
            scroll_type_map = {
                "SingleAction": "singleAction",
                "ScrollToBottom": "scrollToBottom",
                "ScrollToTop": "scrollToTop",
                "ScrollToRight": "scrollToRight",
                "ScrollToLeft": "scrollToLeft",
            }
            scroll_type = scroll_type_map.get(scroll_type, scroll_type)
        self._rpc(
            "aiScroll",
            locate=locate,
            direction=direction,
            scrollType=scroll_type,
            distance=distance_value,
        )

    def ai_pinch(
            self,
            direction: str,
            locate: Optional[str] = None,
            distance: Optional[int] = None,
            duration: Optional[int] = None,
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
            duration: Optional[int] = None,
    ) -> None:
        self._rpc("aiLongPress", locate=locate, duration=duration)

    def ai_double_click(self, locate: str) -> None:
        self._rpc("aiDoubleClick", locate=locate)

    def ai_keyboard_press(self, key_name: str, locate: Optional[str] = None) -> None:
        self._rpc("aiKeyboardPress", locate=locate, keyName=key_name)

    def ai_ask(self, prompt: str) -> Any:
        return self._rpc("aiAsk", prompt=prompt).get("data")

    def ai_query(self, data_demand: Any) -> Any:
        return self._rpc("aiQuery", dataDemand=data_demand).get("data")

    def ai_boolean(self, prompt: str) -> bool:
        return bool(self._rpc("aiBoolean", prompt=prompt).get("data"))

    def ai_number(self, prompt: str) -> Any:
        return self._rpc("aiNumber", prompt=prompt).get("data")

    def ai_string(self, prompt: str) -> str:
        data = self._rpc("aiString", prompt=prompt).get("data")
        return "" if data is None else str(data)

    def ai_locate(self, locate_prompt: str) -> Any:
        return self._rpc("aiLocate", locate=locate_prompt).get("data")

    def ai_assert(self, assertion: str) -> None:
        result = self._rpc("aiAssert", assertion=assertion)
        if not result.get("pass"):
            reason = result.get("reason", "")
            msg = f"AI assertion failed: {assertion!r}"
            if reason:
                msg += f"\nReason: {reason}"
            raise AssertionError(msg)

    def ai_wait_for(self, assertion: str, timeout_ms: int = 15000) -> None:
        rpc_timeout = max(_TIMEOUT, timeout_ms // 1000 + 10)
        self._rpc(
            "aiWaitFor",
            timeout=rpc_timeout,
            assertion=assertion,
            timeoutMs=timeout_ms,
        )

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

    def get_screenshot(self) -> str:
        """Get a base64 encoded screenshot of the device."""
        return self._rpc("getScreenshot").get("screenshot", "")

    # ── Advanced Automation ──────────────────────────────────────────────────────

    def set_ai_act_context(self, ai_action_context: str) -> None:
        """Set the context for subsequent AI actions."""
        self._rpc("setAIActContext", aiActionContext=ai_action_context)

    def run_yaml(self, yaml_content: str) -> Any:
        """Run a Midscene YAML script."""
        return self._rpc("runYaml", yamlContent=yaml_content).get("result")

    def get_report_file(self) -> Optional[str]:
        """Get the path to the current agent's report file, if any."""
        return self._rpc("getReportFile").get("reportPath")

    def get_status(self) -> dict[str, Any]:
        """Get the current status of the agent session."""
        return self._rpc("getStatus")

    def run_adb_shell(self, command: str, timeout_ms: Optional[int] = None) -> str:
        """Run an ADB shell command on the connected device.

        Args:
            command: The shell command to execute.
            timeout_ms: Timeout in **milliseconds**. Defaults to None (uses the
                Node service default). Example: ``timeout_ms=5000`` for 5 seconds.

        Returns:
            The stdout output of the command as a string.
        """
        rpc_timeout = max(_TIMEOUT, timeout_ms // 1000 + 10) if timeout_ms else _TIMEOUT
        result = self._rpc("runAdbShell", timeout=rpc_timeout, command=command, timeoutMs=timeout_ms)
        return result.get("output", "")

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        if self._closed:
            return
        if self._session_id:
            try:
                self._rpc("destroySession", sessionId=self._session_id)
            except Exception as e:
                logger.warning(f"Error destroying session {self._session_id}: {e}")
        self._session_id = None
        self._closed = True
        self._http_session.close()

    def is_closed(self) -> bool:
        return self._closed
