"""优标宝商标数据开放 API 的 Python SDK。

三步跑通::

    import os
    from isud_tm import Client

    client = Client(api_key=os.environ["ISUD_API_KEY"])
    result = client.search_trademarks(jurisdictionCode="CN", keyword="优标宝")
    print(result["conclusion"])
"""

from .client import Client, DEFAULT_BASE_URL, MCP_BASE_URL
from .errors import (
    ApiError,
    AuthenticationError,
    CapabilityError,
    NetworkError,
    RateLimitError,
    ResponseMeta,
    SdkError,
    ValidationError,
)

__version__ = "1.0.3"

__all__ = [
    "Client",
    "DEFAULT_BASE_URL",
    "MCP_BASE_URL",
    "SdkError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
    "CapabilityError",
    "ApiError",
    "NetworkError",
    "ResponseMeta",
    "__version__",
]
