"""
MidsceneAgent：Python 侧的 AI 操作接口。

每个 Android 设备对应一个 MidsceneAgent 实例（内部对应 Node.js 侧一个 session）。
多个 Agent 共享同一个 Node.js 微服务进程，通过 sessionId 隔离。

使用方式：不直接实例化，通过设备类的 .ai property 获取：

    device.ai.act("点击登录按钮")
    device.ai.tap("搜索框")
    device.ai.assert_("页面显示欢迎信息")
"""

import json
import logging
import uuid
from typing import Any, Optional

import requests

from ._node_manager import NodeServiceManager

logger = logging.getLogger(__name__)

# 单次 RPC 调用的默认超时（秒）
# aiAct 等规划类操作耗时较长，设置宽松一些
_DEFAULT_TIMEOUT = 120


class MidsceneRPCError(Exception):
    """Node.js 侧返回的业务错误。"""

    def __init__(self, message: str, code: int = -1, stack: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.stack = stack


class MidsceneAgent:
    """
    对应 Midscene JS 侧的 AndroidAgent。

    API 分为三类：
      - Auto Planning : act()
      - Instant Actions: tap() / input() / scroll() / long_press() /
                         double_click() / key_press() / clear_input()
      - Utility       : assert_() / query() / wait_for() / open_url()
    """

    def __init__(
            self,
            device_id: str,
            node_manager: "NodeServiceManager",
            *,
            agent_options: Optional[dict] = None,
            device_options: Optional[dict] = None,
            rpc_timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        """
        device_id:
            ADB 设备 ID，如 "emulator-5554" 或 "192.168.1.100:5555"
        node_manager:
            Node.js 服务管理器（进程级单例）
        agent_options:
            透传给 Midscene AndroidAgent 构造函数的选项，如：
            { "generateReport": True, "aiActContext": "关闭弹窗后再操作" }
        device_options:
            透传给 Midscene AndroidDevice 构造函数的选项，如：
            { "androidAdbPath": "/custom/path/adb" }
        rpc_timeout:
            单次 RPC 调用超时时间（秒）
        """
        self._device_id = device_id
        self._nm = node_manager
        self._agent_options = agent_options or {}
        self._device_options = device_options or {}
        self._rpc_timeout = rpc_timeout
        self._session_id: Optional[str] = None
        self._closed = False

        self._init_session()

    # ── 内部 RPC ───────────────────────────────────────────────────────────────

    def _rpc(self, method: str, timeout: Optional[int] = None, **params: Any) -> Any:
        """
        发起一次 JSON-RPC 2.0 调用。

        自动注入 sessionId（createSession 除外）。
        """
        if self._closed:
            raise RuntimeError("MidsceneAgent has been destroyed")

        if self._session_id is not None:
            params["sessionId"] = self._session_id

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        url = f"http://127.0.0.1:{self._nm.port}/rpc"
        actual_timeout = timeout if timeout is not None else self._rpc_timeout

        logger.debug("RPC → %s %s", method, {k: v for k, v in params.items() if k != "sessionId"})
        try:
            resp = requests.post(url, json=payload, timeout=actual_timeout)
            resp.raise_for_status()
            raw = resp.content
        except requests.RequestException as e:
            raise MidsceneRPCError(f"Failed to connect to Midscene Node service: {e}") from e

        response = json.loads(raw)

        if "error" in response:
            err = response["error"]
            raise MidsceneRPCError(
                message=err.get("message", "Unknown RPC error"),
                code=err.get("code", -1),
                stack=err.get("stack"),
            )

        result = response.get("result")
        logger.debug("RPC ← %s", result)
        return result

    def _init_session(self) -> None:
        """创建 Node 侧 session，获取 sessionId。"""
        result = self._rpc(
            "createSession",
            deviceId=self._device_id,
            deviceOptions=self._device_options,
            agentOptions=self._agent_options,
        )
        self._session_id = result["sessionId"]
        logger.debug("Midscene session created: %s", self._session_id)

    # ── Auto Planning ──────────────────────────────────────────────────────────

    def act(self, prompt: str, *, cacheable: bool = False) -> None:
        """
        AI 自动规划并执行。对应 agent.aiAct()。

        Midscene 会将 prompt 拆解为若干步骤并依次执行，
        适合描述多步目标，如 "打开设置，找到蓝牙选项并开启"。

        Parameters
        ----------
        prompt:
            自然语言描述的操作目标
        cacheable:
            是否启用规划缓存（相同 prompt 复用上次规划结果）
        """
        self._rpc("aiAct", prompt=prompt, options={"cacheable": cacheable})

    # ── Instant Actions ────────────────────────────────────────────────────────

    def tap(self, locate: str, *, deep_think: bool = False) -> None:
        """
        点击元素。对应 agent.aiTap()。

        AI 负责在当前屏幕截图中定位 locate 描述的元素，然后点击其中心。

        Parameters
        ----------
        locate:
            自然语言描述的元素，如 "登录按钮"、"右上角的关闭图标"
        deep_think:
            启用精细定位模式，适合密集 UI（速度变慢但更准确）
        """
        self._rpc("aiTap", locate=locate, options={"deepThink": deep_think})

    def input(self, locate: str, text: str) -> None:
        """
        在指定元素中输入文本。对应 agent.aiInput()。

        Parameters
        ----------
        locate:
            自然语言描述的输入框，如 "用户名输入框"
        text:
            要输入的文本
        """
        self._rpc("aiInput", locate=locate, text=text)

    def clear_input(self, locate: str) -> None:
        """清空输入框内容。对应 agent.aiClearInput()。"""
        self._rpc("aiClearInput", locate=locate)

    def scroll(
            self,
            locate: str,
            direction: str = "down",
            *,
            distance: Optional[str] = None,
            scroll_type: Optional[str] = None,
    ) -> None:
        """
        滚动操作。对应 agent.aiScroll()。

        Parameters
        ----------
        locate:
            自然语言描述的滚动区域，如 "商品列表"
        direction:
            滚动方向：'up' | 'down' | 'left' | 'right'
        distance:
            滚动幅度：'small' | 'medium' | 'large'（可选）
        scroll_type:
            滚动类型（可选，透传给 Midscene）
        """
        self._rpc(
            "aiScroll",
            locate=locate,
            direction=direction,
            distance=distance,
            scrollType=scroll_type,
        )

    def long_press(self, locate: str) -> None:
        """长按元素。对应 agent.aiLongPress()。"""
        self._rpc("aiLongPress", locate=locate)

    def double_click(self, locate: str) -> None:
        """双击元素。对应 agent.aiDoubleClick()。"""
        self._rpc("aiDoubleClick", locate=locate)

    def key_press(self, key: str) -> None:
        """
        模拟按键。对应 agent.aiKeyboardPress()。

        Parameters
        ----------
        key:
            按键名称，如 'Enter'、'Back'、'Home'、'VolumeUp' 等
        """
        self._rpc("aiKeyboardPress", key=key)

    # ── Utility ────────────────────────────────────────────────────────────────

    def assert_(self, assertion: str, *, msg: Optional[str] = None) -> None:
        """
        AI 视觉断言。对应 agent.aiAssert()。

        断言失败时抛出 AssertionError，可集成 pytest 断言机制。

        Parameters
        ----------
        assertion:
            自然语言描述的断言条件，如 "当前页面显示用户首页"
        msg:
            断言失败时的附加错误信息
        """
        result = self._rpc("aiAssert", assertion=assertion)
        if not result.get("pass"):
            reason = result.get("reason", "")
            base_msg = f"AI assertion failed: {assertion!r}"
            if reason:
                base_msg += f"\nReason: {reason}"
            if msg:
                base_msg += f"\n{msg}"
            raise AssertionError(base_msg)

    def query(self, schema: str) -> Any:
        """
        从当前屏幕提取结构化数据。对应 agent.aiQuery()。

        Parameters
        ----------
        schema:
            Midscene query schema，描述期望的数据结构，如：
            '{"title": string, "price": number}[]'
            '"当前登录用户名"'

        Returns
        -------
        Any
            根据 schema 提取的结构化数据，JSON 可序列化
        """
        result = self._rpc("aiQuery", schema=schema)
        return result.get("data")

    def wait_for(
            self,
            condition: str,
            *,
            timeout_ms: int = 15000,
            check_interval_ms: Optional[int] = None,
    ) -> None:
        """
        等待条件满足。对应 agent.aiWaitFor()。

        Parameters
        ----------
        condition:
            自然语言描述的等待条件，如 "加载动画消失"
        timeout_ms:
            超时时间（毫秒），默认 15000ms
        check_interval_ms:
            检查间隔（毫秒），可选
        """
        rpc_timeout = max(self._rpc_timeout, timeout_ms // 1000 + 10)
        self._rpc(
            "aiWaitFor",
            condition=condition,
            timeoutMs=timeout_ms,
            checkIntervalMs=check_interval_ms,
            timeout=rpc_timeout,
        )

    def open_url(self, uri: str) -> None:
        """
        打开网页 URL 或 App。对应 AndroidAgent.openUrl()。

        Parameters
        ----------
        uri:
            网页 URL（如 'https://example.com'）
            或 App 包名（如 'com.android.settings'）
            或 Activity（如 'com.android.settings/.Settings'）
        """
        self._rpc("openUrl", uri=uri)

    # ── 生命周期 ───────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """
        销毁当前 session，释放 Node 侧资源。
        通常由设备类的 __exit__ 自动调用，无需手动调用。
        """
        if self._closed:
            return
        if self._session_id:
            try:
                self._rpc("destroySession")
            except Exception as e:
                logger.debug("Error destroying session %s: %s", self._session_id, e)
            finally:
                self._session_id = None
        self._closed = True
        logger.debug("MidsceneAgent destroyed.")