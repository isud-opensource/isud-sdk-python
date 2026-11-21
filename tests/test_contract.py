"""契约测试：验证 9 端点覆盖、信封解析、异常映射、退避、幂等、分页、本地校验。

全部使用 mock transport，不依赖真实 API key / 不发真实请求 / 不受限流影响。
"""

from __future__ import annotations

import httpx
import pytest

from isud_sdk import Client
from isud_sdk import errors as E
from conftest import Recorder, envelope, json_response


def make_client(rec: Recorder, **kwargs) -> Client:
    return Client(api_key="lgr_live_test", transport=rec.transport(), **kwargs)


# ---------------------------------------------------------------- 信封/成功
def test_success_returns_data_and_meta():
    rec = Recorder()
    rec.handler = lambda r: json_response(
        envelope({"conclusion": "安全", "total": 0}, requestId="req_abc"),
        headers={
            "X-Credits-Charged": "10",
            "X-Credits-Remaining": "990",
            "X-RateLimit-Limit": "30",
            "X-RateLimit-Remaining": "29",
        },
    )
    with make_client(rec) as c:
        data = c.search_trademarks(jurisdictionCode="CN", keyword="优标宝")
        assert data["conclusion"] == "安全"
        assert c.last_meta.request_id == "req_abc"
        assert c.last_meta.credits_charged == 10
        assert c.last_meta.credits_remaining == 990
        assert c.last_meta.rate_limit == 30


def test_idempotency_key_auto_injected():
    rec = Recorder()
    rec.handler = lambda r: json_response(envelope({"total": 0}))
    with make_client(rec) as c:
        c.search_trademarks(jurisdictionCode="CN", keyword="x")
        key = rec.calls[0].headers.get("idempotency-key")
        assert key and len(key) == 32  # uuid4().hex


def test_custom_idempotency_key():
    rec = Recorder()
    rec.handler = lambda r: json_response(
        envelope({"total": 0}), headers={"Idempotency-Replayed": "true"}
    )
    with make_client(rec) as c:
        c.search_trademarks(jurisdictionCode="CN", keyword="x", idempotency_key="ORDER-123")
        assert rec.calls[0].headers["idempotency-key"] == "ORDER-123"
        assert c.last_meta.idempotent_replay is True


# ---------------------------------------------------------------- 异常映射
@pytest.mark.parametrize(
    "status,code,exc_type",
    [
        (401, "8889", E.AuthenticationError),
        (200, "9001", E.ValidationError),
        (200, "0002", E.CapabilityError),
        (200, "0001", E.ApiError),
    ],
)
def test_error_mapping(status, code, exc_type):
    rec = Recorder()
    rec.handler = lambda r: json_response(
        envelope(None, code=code, msg="出错啦", suggestion="换个关键词", requestId="req_err"),
        status=status,
    )
    with make_client(rec) as c:
        with pytest.raises(exc_type) as ei:
            c.get_usage()
        assert ei.value.code == code
        assert ei.value.request_id == "req_err"
        assert "换个关键词" in str(ei.value)
        assert "req_err" in ei.value.friendly()


def test_rate_limit_429_uses_envelope_retry_after():
    rec = Recorder()
    rec.handler = lambda r: json_response(
        envelope(None, code="9002", msg="太频繁", retryAfter=7, retryable=True),
        status=429,
        headers={"Retry-After": "99"},  # 信封应优先
    )
    with make_client(rec) as c:
        with pytest.raises(E.RateLimitError) as ei:
            c.get_usage()  # GET 会重试但每次都 429，重试耗尽
        assert ei.value.retry_after == 7


def test_rate_limit_header_fallback():
    rec = Recorder()
    rec.handler = lambda r: json_response(
        envelope(None, code="9002", msg="限流"),
        status=429,
        headers={"Retry-After": "12"},
    )
    with make_client(rec, max_retries=0) as c:
        with pytest.raises(E.RateLimitError) as ei:
            c.get_usage()
        assert ei.value.retry_after == 12


# ---------------------------------------------------------------- 退避
def test_retry_succeeds_after_transient_network_error(monkeypatch):
    rec = Recorder()
    state = {"n": 0}

    def handler(r):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("boom")
        return json_response(envelope({"ok": True}))

    rec.handler = handler
    import isud_sdk.retry as retry_mod

    monkeypatch.setattr(retry_mod.time, "sleep", lambda s: None)
    with make_client(rec, max_retries=2) as c:
        data = c.get_usage()
        assert data["ok"] is True
        assert state["n"] == 2  # 首次失败 + 1 次重试成功


def test_no_retry_on_auth_error(monkeypatch):
    rec = Recorder()
    state = {"n": 0}

    def handler(r):
        state["n"] += 1
        return json_response(envelope(None, code="8889", msg="key 无效"), status=401)

    rec.handler = handler
    with make_client(rec, max_retries=5) as c:
        with pytest.raises(E.AuthenticationError):
            c.get_usage()
        assert state["n"] == 1  # 鉴权失败绝不重试


# ---------------------------------------------------------------- 本地校验
def test_local_validation_size_and_keyword():
    rec = Recorder()
    rec.handler = lambda r: json_response(envelope({}))
    with make_client(rec) as c:
        with pytest.raises(E.ValidationError):
            c.search_trademarks(jurisdictionCode="CN", keyword="x", size=0)
        with pytest.raises(E.ValidationError):
            c.search_trademarks(jurisdictionCode="CN", size=10)  # keyword/owner 都缺
        with pytest.raises(E.ValidationError):
            c.query_request_log("x" * 65)
        assert rec.calls == []  # 校验失败不应发任何请求


# ---------------------------------------------------------------- 分页迭代
def test_iter_trademarks_auto_paging():
    rec = Recorder()

    def handler(r):
        url = str(r.url)
        if "current=1" in url:
            return json_response(envelope({"total": 3, "records": [
                {"markText": "A"}, {"markText": "B"}]}))
        elif "current=2" in url:
            return json_response(envelope({"total": 3, "records": [{"markText": "C"}]}))
        return json_response(envelope({"total": 3, "records": []}))

    rec.handler = handler
    with make_client(rec) as c:
        items = list(c.iter_trademarks(size=2))
        assert [i["markText"] for i in items] == ["A", "B", "C"]
        assert len(rec.calls) == 2


# ---------------------------------------------------------------- 9 端点覆盖
def test_all_nine_endpoints_exist():
    methods = [
        "search_trademarks", "list_trademarks", "search_designs", "list_reports",
        "get_workbench_stats", "get_usage", "query_request_log",
        "get_mcp_health", "call_mcp",
    ]
    for m in methods:
        assert callable(getattr(Client, m, None)), m


def test_mcp_uses_correct_base_url():
    rec = Recorder()
    rec.handler = lambda r: json_response({"status": "ok", "toolCount": 13})
    with make_client(rec) as c:
        c.get_mcp_health()
        assert "/api/v1/mcp/health" in rec.calls[0].url
        assert "/api/v1/open" not in rec.calls[0].url
