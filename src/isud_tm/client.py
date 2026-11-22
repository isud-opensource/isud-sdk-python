"""优标宝开放 API Python 客户端 —— 手写体验层核心。

生成层在 models.py（勿手改），本文件实现 SDK-DESIGN.md 定义的全部体验：
鉴权、信封解析、异常映射、Retry-After 退避、幂等键、扣点回读、分页、本地校验。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

from .errors import (
    ApiError,
    NetworkError,
    RateLimitError,
    ResponseMeta,
    SdkError,
    ValidationError,
    raise_for_envelope,
)
from .retry import parse_retry_after, with_retry

DEFAULT_BASE_URL = "https://app.isud.cn/api/v1/open"
MCP_BASE_URL = "https://app.isud.cn/api/v1"  # MCP 挂在 /api/v1，不在 /open 下


class Client:
    """优标宝开放 API 客户端。

    用法::

        from isud_tm import Client

        client = Client(api_key=os.environ["ISUD_API_KEY"])
        result = client.search_trademarks(jurisdictionCode="CN", keyword="优标宝")
        print(result.conclusion, client.last_meta.credits_charged)

    也可不传 api_key，从环境变量 ``ISUD_API_KEY`` 自动读取。
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        key = api_key or os.environ.get("ISUD_API_KEY")
        if not key:
            raise ValidationError(
                "缺少 API 密钥：请传入 api_key 或设置环境变量 ISUD_API_KEY。"
                "密钥在控制台创建（注册即送调用次数）。"
            )
        self._api_key = key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.last_meta: ResponseMeta = ResponseMeta()

        headers = {
            "X-API-Key": key,
            "User-Agent": "isud-sdk-python/1.0.2",
            "Accept": "application/json",
        }
        if transport is not None:
            self._http = httpx.Client(headers=headers, timeout=timeout, transport=transport)
            self._owns_http = True
        else:
            self._http = httpx.Client(headers=headers, timeout=timeout)
            self._owns_http = True

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # 内部：请求管线
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_meta(response: httpx.Response, envelope: dict[str, Any]) -> ResponseMeta:
        def as_int(name: str) -> int | None:
            v = response.headers.get(name)
            if v is None:
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        rid = envelope.get("requestId") or response.headers.get("X-Request-Id")
        return ResponseMeta(
            request_id=rid,
            credits_charged=as_int("X-Credits-Charged"),
            credits_remaining=as_int("X-Credits-Remaining"),
            rate_limit=as_int("X-RateLimit-Limit"),
            rate_remaining=as_int("X-RateLimit-Remaining"),
            idempotent_replay=response.headers.get("Idempotency-Replayed", "").lower() == "true",
            http_status=response.status_code,
        )

    @staticmethod
    def _parse_retry_after_from_response(exc: SdkError, response: httpx.Response) -> None:
        """把响应头 Retry-After 补进 RateLimitError（信封 retryAfter 优先，已由异常携带）。"""
        if isinstance(exc, RateLimitError) and exc.retry_after is None:
            header_val = response.headers.get("Retry-After")
            parsed = parse_retry_after(header_val)
            if parsed is not None:
                exc.retry_after = parsed

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        idempotent: bool = False,
        idempotency_key: str | None = None,
        base_url: str | None = None,
        retries: int | None = None,
        envelope: bool = True,
    ) -> Any:
        """统一请求管线：鉴权头已注入；这里做信封解析、异常映射、退避重试。

        envelope=False 用于返回裸对象的端点（如 /mcp/health，契约里不含 code 信封）。
        """
        root = (base_url or self.base_url).rstrip("/")
        url = root + path
        attempts = self.max_retries if retries is None else retries

        extra_headers: dict[str, str] = {}
        if idempotent:
            key = idempotency_key or uuid.uuid4().hex
            if not (1 <= len(key) <= 128):
                raise ValidationError("幂等键长度必须在 1~128 字符之间。")
            extra_headers["Idempotency-Key"] = key

        def do_once() -> Any:
            try:
                response = self._http.request(
                    method, url, params=params, json=json_body, headers=extra_headers
                )
            except (httpx.TimeoutException, httpx.RequestError) as e:
                raise NetworkError(f"网络请求失败: {e}") from e

            # 解析响应体（可能是非 JSON 错误体）
            try:
                payload = response.json()
            except ValueError:
                payload = {
                    "code": "0001",
                    "msg": f"HTTP {response.status_code} 返回了非 JSON 内容",
                    "data": None,
                }

            if not isinstance(payload, dict):
                payload = {"code": "0001", "msg": "响应格式异常", "data": None}

            # 裸响应端点（如 MCP health）没有 code 信封
            if not envelope:
                if response.status_code >= 400:
                    meta_bare = self._build_meta(response, {})
                    self.last_meta = meta_bare
                    # 已拿到 HTTP 响应（服务端返回的 4xx/5xx）归 ApiError；
                    # 真正的连接/超时失败在 _request 的 except 分支仍归 NetworkError。
                    raise ApiError(
                        f"HTTP {response.status_code}: {str(payload)[:200]}",
                        meta=meta_bare, status_code=response.status_code,
                    )
                self.last_meta = self._build_meta(response, {})
                return payload

            meta = self._build_meta(response, payload)
            self.last_meta = meta

            try:
                raise_for_envelope(payload, http_status=response.status_code, meta=meta)
            except SdkError as exc:
                self._parse_retry_after_from_response(exc, response)
                raise

            return payload.get("data")

        def should_retry(exc: SdkError) -> bool:
            # 只对幂等安全请求重试：GET 或带幂等键的 POST
            safe = method.upper() == "GET" or idempotent
            return safe

        return with_retry(
            do_once,
            max_retries=attempts,
            should_retry=should_retry,
            on_retry=lambda exc, n, wait: None,  # 示例可用日志替换
        )

    # ------------------------------------------------------------------ #
    # 本地参数校验（避免无谓扣点，见 SDK-DESIGN.md §5）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_size(size: int | None) -> None:
        if size is not None and not (1 <= size <= 100):
            raise ValidationError("size 必须在 1~100 之间（收到 %r）。" % size)

    @staticmethod
    def _check_search_input(keyword: str | None, owner: str | None) -> None:
        if not keyword and not owner:
            raise ValidationError("keyword 与 owner 至少提供一项。")

    # ------------------------------------------------------------------ #
    # 9 个端点方法（与 operationId 对齐）
    # ------------------------------------------------------------------ #
    def search_trademarks(
        self,
        *,
        jurisdictionCode: str,
        keyword: str | None = None,
        owner: str | None = None,
        niceClasses: list[str] | None = None,
        status: list[str] | None = None,
        current: int = 1,
        size: int = 50,
        saveReport: bool = False,
        reportTitle: str | None = None,
        intentMark: str | None = None,
        connectorCode: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """商标检索与冲突判定（扣 10 点，自动注入幂等键）。"""
        self._check_size(size)
        self._check_search_input(keyword, owner)
        body: dict[str, Any] = {
            "jurisdictionCode": jurisdictionCode,
            "current": current,
            "size": size,
        }
        optional = dict(
            keyword=keyword,
            owner=owner,
            niceClasses=niceClasses,
            status=status,
            saveReport=saveReport,
            reportTitle=reportTitle,
            intentMark=intentMark,
            connectorCode=connectorCode,
        )
        body.update({k: v for k, v in optional.items() if v is not None})
        data = self._request(
            "POST", "/ip/trademark/search", json_body=body,
            idempotent=True, idempotency_key=idempotency_key,
        )
        return data

    def search_designs(
        self,
        *,
        jurisdictionCode: str,
        keyword: str,
        locarnoClasses: list[str] | None = None,
        status: list[str] | None = None,
        owner: str | None = None,
        saveReport: bool = False,
        reportTitle: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """外观设计检索（扣 10 点）。注意 CN 法域暂未开放。"""
        body: dict[str, Any] = {
            "jurisdictionCode": jurisdictionCode,
            "keyword": keyword,
        }
        optional = dict(
            locarnoClasses=locarnoClasses, status=status, owner=owner,
            saveReport=saveReport, reportTitle=reportTitle,
        )
        body.update({k: v for k, v in optional.items() if v is not None})
        return self._request(
            "POST", "/ip/design/search", json_body=body,
            idempotent=True, idempotency_key=idempotency_key,
        )

    def list_trademarks(
        self,
        *,
        current: int = 1,
        size: int = 10,
        keyword: str | None = None,
        markText: str | None = None,
        ownerName: str | None = None,
        status: str | None = None,
        niceClass: str | None = None,
        markType: str | None = None,
        riskLevel: str | None = None,
        sortBy: str | None = None,
        isOwned: bool | None = None,
        isWatched: bool | None = None,
    ) -> Any:
        """分页查询商标档案。"""
        self._check_size(size)
        params: dict[str, Any] = {"current": current, "size": size}
        optional = dict(
            keyword=keyword, markText=markText, ownerName=ownerName, status=status,
            niceClass=niceClass, markType=markType, riskLevel=riskLevel, sortBy=sortBy,
        )
        params.update({k: v for k, v in optional.items() if v is not None})
        for k, v in (("isOwned", isOwned), ("isWatched", isWatched)):
            if v is not None:
                params[k] = str(v).lower()
        return self._request("GET", "/ip/trademark/list", params=params)

    def iter_trademarks(self, *, size: int = 50, max_pages: int | None = None, **filters: Any) -> Iterator[dict[str, Any]]:
        """自动翻页迭代商标档案，yield 单条记录。"""
        self._check_size(size)
        page = 1
        pages = 0
        while True:
            if max_pages is not None and pages >= max_pages:
                return
            result = self.list_trademarks(current=page, size=size, **filters) or {}
            records = result.get("records") or []
            for rec in records:
                yield rec
            pages += 1
            total = result.get("total") or 0
            total_pages = (total + size - 1) // size
            if not records or page >= total_pages:
                return
            page += 1

    def list_reports(self, *, current: int = 1, size: int = 10) -> Any:
        """分页查询排查报告。"""
        self._check_size(size)
        return self._request("GET", "/ip/report/list", params={"current": current, "size": size})

    def get_workbench_stats(self) -> Any:
        """工作台汇总统计。"""
        return self._request("GET", "/ip/workbench/stats")

    def get_usage(self) -> Any:
        """点数余额与用量查询（实时，no-store）。"""
        return self._request("GET", "/ip/usage")

    def query_request_log(self, requestId: str) -> Any:
        """按 requestId 回查请求日志。查不到返回 None。"""
        if not requestId or len(requestId) > 64:
            raise ValidationError("requestId 必须为 1~64 字符。")
        return self._request("GET", "/ip/requests", params={"requestId": requestId})

    def get_mcp_health(self) -> Any:
        """MCP 服务健康检查（无需鉴权，返回裸对象）。

        注意：健康检查端点 /mcp/health 在 openapi 规范中未覆盖 servers，
        继承全局 /api/v1/open；只有 MCP JSON-RPC 主端点 /mcp 挂在 /api/v1。
        因此这里不传 base_url，走默认 DEFAULT_BASE_URL（/api/v1/open）。
        """
        return self._request("GET", "/mcp/health", retries=0, envelope=False)

    def call_mcp(self, method: str, params: dict[str, Any] | None = None, *, id: int = 1) -> Any:
        """MCP JSON-RPC 调用（scope: mcp）。默认不自动重试。"""
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": id}
        if params is not None:
            payload["params"] = params
        return self._request(
            "POST", "/mcp", json_body=payload, base_url=MCP_BASE_URL,
            retries=0, envelope=False,
        )


__all__ = ["Client", "DEFAULT_BASE_URL", "MCP_BASE_URL"]
