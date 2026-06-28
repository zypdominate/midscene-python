"""
BaseAgent：跨平台共享的 AI 操作接口。

android / web 平台包各自继承 :class:`BaseAgent`，复用这里的 RPC 通道与
全部跨平台 ``ai_*`` 方法，仅需提供：

- 类属性 ``SERVICE_SPEC``（指向各自的 Node 服务）；
- ``createSession`` 的平台参数（构造时通过 ``create_params`` 传入）；
- 平台专有方法（Android 的设备操作、Web 的页面导航等）。
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from .config import MidsceneConfig
from .exceptions import MidsceneError
from .node_service import NodeServiceManager
from .runtime import ServiceSpec

logger = logging.getLogger("midscene.agent")

_DEFAULT_TIMEOUT = 120


class BaseAgent:
    #: 子类必须覆盖：指向该平台的 Node 服务
    SERVICE_SPEC: ClassVar[ServiceSpec]

    #: RPC 默认超时（秒）
    DEFAULT_TIMEOUT: ClassVar[int] = _DEFAULT_TIMEOUT

    def __init__(
            self,
            config: MidsceneConfig | None = None,
            *,
            create_params: dict[str, Any] | None = None,
    ) -> None:
        if not hasattr(type(self), "SERVICE_SPEC"):
            raise NotImplementedError(
                f"{type(self).__name__} must define a SERVICE_SPEC class attribute"
            )
        self._closed = False
        self._session_id: str | None = None
        self._config = config or MidsceneConfig.from_env()
        self._node_manager = NodeServiceManager.get(self.SERVICE_SPEC, self._config)
        self._node_manager.ensure_started()

        params: dict[str, Any] = dict(create_params or {})
        if self._config.ai_action_context and "aiActionContext" not in params:
            params["aiActionContext"] = self._config.ai_action_context

        result = self._rpc("createSession", **params)
        self._session_id = result["sessionId"]
        self._on_session_created(result)

    def _on_session_created(self, result: dict[str, Any]) -> None:
        """子类钩子：会话创建后保存平台相关信息（如 deviceId）。"""

    # ── Context manager ──────────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *_: Any) -> None:
        self.destroy()

    # ── Internal RPC ─────────────────────────────────────────────────────────────

    def _rpc(self, method: str, *, timeout: int | None = None, **params: Any) -> dict[str, Any]:
        if self._closed:
            raise MidsceneError("Agent has been destroyed; create a new agent instance")

        if self._session_id is not None and method != "createSession":
            params["sessionId"] = self._session_id

        return self._node_manager.rpc(
            method,
            timeout=timeout if timeout is not None else self.DEFAULT_TIMEOUT,
            **params,
        )

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
            locate: str | None = None,
            direction: str = "down",
            scroll_type: str | None = None,
            distance: Any = None,
    ) -> None:
        """
        滚动操作。具体行为由后端平台实现决定。

        当 scroll_type='singleAction' 时，后端通常忽略 distance 参数，
        执行固定长度的单次滑动手势。
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

    def ai_double_click(self, locate: str) -> None:
        self._rpc("aiDoubleClick", locate=locate)

    def ai_keyboard_press(self, key_name: str, locate: str | None = None) -> None:
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
        rpc_timeout = max(self.DEFAULT_TIMEOUT, timeout_ms // 1000 + 10)
        self._rpc(
            "aiWaitFor",
            timeout=rpc_timeout,
            assertion=assertion,
            timeoutMs=timeout_ms,
        )

    # ── Shared helpers ───────────────────────────────────────────────────────────

    def get_screenshot(self) -> str:
        """获取当前界面的 base64 截图。"""
        return self._rpc("getScreenshot").get("screenshot", "")

    def set_ai_act_context(self, ai_action_context: str) -> None:
        """设置后续 AI 操作的上下文。"""
        self._rpc("setAIActContext", aiActionContext=ai_action_context)

    def run_yaml(self, yaml_content: str) -> Any:
        """运行 Midscene YAML 脚本。"""
        return self._rpc("runYaml", yamlContent=yaml_content).get("result")

    def get_report_file(self) -> str | None:
        """返回当前 agent 的报告文件路径（如有）。"""
        return self._rpc("getReportFile").get("reportPath")

    def get_status(self) -> dict[str, Any]:
        """返回当前 agent 会话状态。"""
        return self._rpc("getStatus")

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        if self._closed:
            return
        if self._session_id:
            try:
                self._rpc("destroySession", sessionId=self._session_id)
            except Exception as e:
                logger.warning("Error destroying session %s: %s", self._session_id, e)
        self._session_id = None
        self._closed = True

    def is_closed(self) -> bool:
        return self._closed
