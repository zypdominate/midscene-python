"""MidsceneAgent：Python 侧 Android AI 操作接口。"""

import uuid
from typing import Any, Optional

import requests

from .config import MidsceneConfig
from .exceptions import MidsceneRPCError
from .node_service import NodeServiceManager

_TIMEOUT = 120


class MidsceneAgent:
    def __init__(
            self,
            device_id: str,
            config: Optional[MidsceneConfig] = None,
    ):
        self._device_id = device_id
        self._session_id: Optional[str] = None
        self._closed = False
        self._config = config or MidsceneConfig.from_env()
        self._node_manager = NodeServiceManager(self._config)
        self._node_manager.ensure_started()
        self._port = self._node_manager.port
        self._session_id = self._rpc("createSession", deviceId=device_id)["sessionId"]

    def _rpc(self, method: str, timeout: int = _TIMEOUT, **params: Any) -> dict[str, Any]:
        if self._session_id is not None and method != "createSession":
            params["sessionId"] = self._session_id

        resp = requests.post(
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
        self._rpc(
            "aiScroll",
            locate=locate,
            direction=direction,
            scrollType=scroll_type,
            distance=distance,
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

    def run_adb_shell(self, command: str, timeout: Optional[int] = None) -> str:
        rpc_timeout = max(_TIMEOUT, timeout // 1000 + 10) if timeout else _TIMEOUT
        result = self._rpc("runAdbShell", timeout=rpc_timeout, command=command, timeoutMs=timeout)
        return result.get("output", "")

    def destroy(self) -> None:
        if self._closed:
            return
        if self._session_id:
            try:
                self._rpc("destroySession", sessionId=self._session_id)
            except Exception as e:
                print(f"Error destroying session {self._session_id}: {e}")
        self._session_id = None
        self._closed = True

    def is_closed(self) -> bool:
        return self._closed
