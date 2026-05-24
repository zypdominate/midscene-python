"""MidsceneAgent：Python 侧 AI 操作接口。"""

import uuid

import requests

from .config import MidsceneConfig
from .exceptions import MidsceneRPCError
from .node_service import NodeServiceManager

_TIMEOUT = 120


class MidsceneAgent:
    def __init__(self, device_id: str):
        self._device_id = device_id
        self._session_id = None
        self._closed = False
        nm = NodeServiceManager(MidsceneConfig.from_env())
        nm.ensure_started()
        self._port = nm.port
        self._session_id = self._rpc("createSession", deviceId=device_id)["sessionId"]

    def _rpc(self, method: str, timeout: int = _TIMEOUT, **params):
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
        return body.get("result")

    def act(self, prompt: str):
        self._rpc("aiAct", prompt=prompt)

    def tap(self, locate: str):
        self._rpc("aiTap", locate=locate)

    def input(self, locate: str, text: str):
        self._rpc("aiInput", locate=locate, text=text)

    def scroll(self, locate: str, direction: str = "down", distance: str | None = None):
        self._rpc("aiScroll", locate=locate, direction=direction, distance=distance)

    def key_press(self, key: str):
        self._rpc("aiKeyboardPress", key=key)

    def assert_(self, assertion: str):
        result = self._rpc("aiAssert", assertion=assertion)
        if not result.get("pass"):
            reason = result.get("reason", "")
            msg = f"AI assertion failed: {assertion!r}"
            if reason:
                msg += f"\nReason: {reason}"
            raise AssertionError(msg)

    def query(self, schema: str):
        return self._rpc("aiQuery", schema=schema).get("data")

    def wait_for(self, condition: str, timeout_ms: int = 15000):
        rpc_timeout = max(_TIMEOUT, timeout_ms // 1000 + 10)
        self._rpc(
            "aiWaitFor",
            timeout=rpc_timeout,
            condition=condition,
            timeoutMs=timeout_ms,
        )

    def destroy(self):
        if self._closed:
            return
        if self._session_id:
            try:
                self._rpc("destroySession", sessionId=self._session_id)
            except Exception as e:
                print(f"Error destroying session {self._session_id}: {e}")
        self._session_id = None
        self._closed = True

    def is_closed(self):
        return self._closed
