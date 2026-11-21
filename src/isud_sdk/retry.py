"""Retry-After 退避策略 —— 两语言行为对齐，见 SDK-DESIGN.md §4。"""

from __future__ import annotations

import email.utils
import random
import time
from datetime import datetime, timezone
from typing import Callable

from .errors import NetworkError, RateLimitError, SdkError

# 单次等待上限：即便服务端 Retry-After 很长，也不长时间阻塞用户
MAX_WAIT_SECONDS = 60
# 指数退避参数
BASE_BACKOFF = 1.0
MAX_BACKOFF = 30.0


def parse_retry_after(value: str | None) -> int | None:
    """解析 Retry-After 头：整数秒 或 HTTP-date。无法解析返回 None。"""
    if not value:
        return None
    value = value.strip()
    # 整数秒
    if value.isdigit():
        return int(value)
    # HTTP-date (RFC 7231)
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = dt - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def exponential_backoff(attempt: int, *, jitter: bool = True) -> float:
    """第 attempt 次（从 0 起）指数退避秒数，可选抖动防惊群。"""
    raw = min(BASE_BACKOFF * (2**attempt), MAX_BACKOFF)
    if jitter:
        raw = raw * (0.5 + random.random() * 0.5)
    return raw


def resolve_wait(
    exc: SdkError,
    *,
    attempt: int,
    max_wait: float = MAX_WAIT_SECONDS,
) -> float:
    """决定本次重试等待秒数。

    优先级：信封 retryAfter > Retry-After 头 > 指数退避。
    实际等待不超过 max_wait。
    """
    wait: float
    if isinstance(exc, RateLimitError):
        # retry_after 已由 client 从信封 retryAfter 或头解析好
        if exc.retry_after is not None:
            wait = float(exc.retry_after)
        else:
            wait = exponential_backoff(attempt)
    elif isinstance(exc, NetworkError):
        wait = exponential_backoff(attempt)
    else:
        wait = exponential_backoff(attempt)
    return max(0.0, min(wait, max_wait))


def with_retry(
    fn: Callable[[], object],
    *,
    max_retries: int,
    should_retry: Callable[[SdkError], bool],
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[SdkError, int, float], None] | None = None,
):
    """通用重试执行器。

    Args:
        fn: 实际发起请求的函数（无参）
        max_retries: 最大重试次数（不含首次）
        should_retry: 判断某异常是否可重试
        sleep: 可注入的休眠函数（测试用）
        on_retry: 每次重试前的回调（异常、第几次、等待秒数），用于日志/示例展示
    """
    attempt = 0
    while True:
        try:
            return fn()
        except SdkError as exc:
            if attempt >= max_retries or not exc.retryable or not should_retry(exc):
                raise
            wait = resolve_wait(exc, attempt=attempt)
            if on_retry:
                on_retry(exc, attempt + 1, wait)
            sleep(wait)
            attempt += 1


__all__ = [
    "parse_retry_after",
    "exponential_backoff",
    "resolve_wait",
    "with_retry",
    "MAX_WAIT_SECONDS",
]
