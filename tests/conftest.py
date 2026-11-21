"""测试基础设施：httpx.MockTransport handler 工厂，记录请求便于断言。"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx


@dataclass
class Call:
    method: str
    url: str
    headers: dict[str, str]
    body: Any


@dataclass
class Recorder:
    calls: list[Call] = field(default_factory=list)
    handler: Callable[[httpx.Request], httpx.Response] | None = None

    def transport(self) -> httpx.MockTransport:
        def h(request: httpx.Request) -> httpx.Response:
            body = None
            if request.content:
                try:
                    body = json.loads(request.content)
                except ValueError:
                    body = request.content.decode("utf-8", "replace")
            self.calls.append(Call(request.method, str(request.url), dict(request.headers), body))
            if self.handler is None:
                raise AssertionError("测试未设置 handler")
            return self.handler(request)

        return httpx.MockTransport(h)


def envelope(data: Any = None, *, code: str = "0000", msg: str = "成功", **extra: Any) -> dict[str, Any]:
    e: dict[str, Any] = {"code": code, "msg": msg, "data": data}
    e.update(extra)
    return e


def json_response(
    payload: dict[str, Any],
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    return httpx.Response(status, json=payload, headers=h)
