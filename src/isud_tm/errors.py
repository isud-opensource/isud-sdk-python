"""异常体系 —— 错误码/HTTP 状态码到 Python 异常的映射。

设计见 SDK-DESIGN.md §3。两语言异常类名保持一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResponseMeta:
    """每次调用都解析的响应元数据（扣点/追踪/限流），成功失败都有。"""

    request_id: str | None = None
    credits_charged: int | None = None
    credits_remaining: int | None = None
    rate_limit: int | None = None
    rate_remaining: int | None = None
    idempotent_replay: bool = False
    http_status: int | None = None

    def __str__(self) -> str:
        return (
            f"request_id={self.request_id} "
            f"credits_charged={self.credits_charged} "
            f"credits_remaining={self.credits_remaining}"
        )


class SdkError(Exception):
    """所有 SDK 异常的基类。

    Attributes:
        message: 人类可读错误文案
        code: 信封业务错误码（如 "8889"）
        request_id: 请求追踪 ID，报障时提供给服务端
        suggestion: 服务端给出的下一步建议
        retryable: 是否可原样重试
        meta: 响应元数据
    """

    default_retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        request_id: str | None = None,
        suggestion: str | None = None,
        retryable: bool | None = None,
        meta: ResponseMeta | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.request_id = request_id
        self.suggestion = suggestion
        self.retryable = self.default_retryable if retryable is None else retryable
        self.meta = meta or ResponseMeta()
        self.status_code = status_code
        super().__init__(self._render())

    def _render(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"[code={self.code}]")
        if self.suggestion:
            parts.append(f"建议: {self.suggestion}")
        if self.request_id:
            parts.append(f"(requestId={self.request_id})")
        return " ".join(parts)

    def friendly(self) -> str:
        """给示例/终端用的完整友好提示（不裸 traceback）。"""
        lines = [f"✗ {self.message}"]
        if self.code:
            lines.append(f"  错误码: {self.code}")
        if self.suggestion:
            lines.append(f"  建议: {self.suggestion}")
        if self.request_id:
            lines.append(f"  追踪ID: {self.request_id}（报障时提供）")
        if self.meta.credits_charged is not None:
            lines.append(f"  本次扣点: {self.meta.credits_charged}")
        return "\n".join(lines)


class AuthenticationError(SdkError):
    """8889 / HTTP 401：密钥缺失、无效、禁用、过期或 scope 不足。不可重试。"""

    default_retryable = False


class RateLimitError(SdkError):
    """9002 限流 / 9003 每日额度：HTTP 429，携带 retry_after 秒数。"""

    default_retryable = True

    def __init__(self, *args: Any, retry_after: int | None = None, **kwargs: Any) -> None:
        self.retry_after = retry_after
        super().__init__(*args, **kwargs)


class ValidationError(SdkError):
    """9001 参数错误（含幂等键误用）。不可重试，带 suggestion。"""

    default_retryable = False


class CapabilityError(SdkError):
    """0002：数据源未接入/类型未开放。不可重试，不扣点。"""

    default_retryable = False


class ApiError(SdkError):
    """0001 通用业务错误。retryable 由信封字段决定。"""


class NetworkError(SdkError):
    """连接失败、超时、5xx。可重试。"""

    default_retryable = True


# 错误码 -> 异常类（HTTP 401/429 在 client 层优先判定）
CODE_TO_ERROR: dict[str, type[SdkError]] = {
    "8889": AuthenticationError,
    "9001": ValidationError,
    "9002": RateLimitError,
    "9003": RateLimitError,
    "0002": CapabilityError,
    "0001": ApiError,
}


def raise_for_envelope(
    envelope: dict[str, Any],
    *,
    http_status: int,
    meta: ResponseMeta,
) -> None:
    """根据信封 + HTTP 状态码抛出对应异常。成功（0000）时静默返回。

    优先级：先看 HTTP 状态码（401/429），再看信封 code。
    """
    code = str(envelope.get("code", ""))
    msg = envelope.get("msg") or "请求失败"
    request_id = envelope.get("requestId") or meta.request_id
    suggestion = envelope.get("suggestion")
    retryable = envelope.get("retryable")
    retry_after = envelope.get("retryAfter")

    if code == "0000":
        return

    common = dict(
        code=code,
        request_id=request_id,
        suggestion=suggestion,
        retryable=retryable,
        meta=meta,
        status_code=http_status,
    )

    if http_status == 401 or code == "8889":
        raise AuthenticationError(msg, **common)
    if http_status == 429 or code in ("9002", "9003"):
        ra = retry_after if isinstance(retry_after, int) else None
        raise RateLimitError(msg, retry_after=ra, **common)

    exc_cls = CODE_TO_ERROR.get(code, ApiError)
    raise exc_cls(msg, **common)


__all__ = [
    "ResponseMeta",
    "SdkError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
    "CapabilityError",
    "ApiError",
    "NetworkError",
    "CODE_TO_ERROR",
    "raise_for_envelope",
]
