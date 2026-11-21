# isud-sdk-python

优标宝商标数据开放 API 的 Python SDK —— 商标排查、档案查询、外观设计的**契约驱动**客户端。

- **依赖极简**：运行时只要 `httpx`
- **契约驱动**：数据模型从 [OpenAPI 3.1 契约](https://docs.isud.cn/openapi.yaml) 自动生成
- **体验完整**：自动 Retry-After 退避、幂等键、扣点回读、分页迭代、友好异常

> 密钥从[控制台](https://app.isud.cn)创建（**注册即送调用次数**），仅创建时完整展示一次。

## 安装

```bash
pip install isud-sdk
```

## 3 分钟上手

```bash
export ISUD_API_KEY="lgr_live_你的密钥"   # Windows 用 set 或 PowerShell $env:
python hello.py
```

`hello.py`：

```python
from isud_sdk import Client

client = Client()  # 自动读取环境变量 ISUD_API_KEY
result = client.search_trademarks(jurisdictionCode="CN", keyword="优标宝")
print(result["conclusion"])
print("本次扣点:", client.last_meta.credits_charged)
```

运行输出：

```
存在中度相似商标，建议进一步人工评估
本次扣点: 10
```

## 核心能力

```python
from isud_sdk import Client, RateLimitError

client = Client(api_key="lgr_live_...")

# 1. 商标排查（自动幂等 + 429 退避 + 扣点回读）
r = client.search_trademarks(
    jurisdictionCode="CN", keyword="优标宝", niceClasses=["35"]
)

# 2. 分页迭代：自动翻完所有页，无需关心 current/size
for item in client.iter_trademarks(keyword="优标", size=50):
    print(item["markText"], item["status"])

# 3. 用量自助对账
usage = client.get_usage()
print("余额:", usage["balance"])

# 4. 失败有语义，不裸 traceback
try:
    client.search_trademarks(jurisdictionCode="XX", keyword="x")
except RateLimitError as e:
    print(e.friendly())       # 含错误码、建议、requestId
    print("请等", e.retry_after, "秒")
```

所有方法：

| 方法 | 说明 |
|---|---|
| `search_trademarks()` | 商标检索与冲突判定（10 点） |
| `search_designs()` | 外观设计检索（10 点） |
| `list_trademarks()` / `iter_trademarks()` | 商标档案分页 / 自动翻页迭代 |
| `list_reports()` | 排查报告分页 |
| `get_workbench_stats()` | 工作台汇总统计 |
| `get_usage()` | 点数余额与用量 |
| `query_request_log(requestId)` | 按追踪 ID 回查调用结果 |
| `get_mcp_health()` / `call_mcp()` | MCP 探活 / JSON-RPC 调用 |

## 示例项目

- [`examples/conflict_check`](examples/conflict_check) —— 近似商标排查（输入商标名 → 风险分级）
- [`examples/batch_screen`](examples/batch_screen) —— 批量风险筛查（CSV 批量读 → 汇总导出）

每个示例都是 `clone → 填 key → run` 三步跑通，出错给友好提示。

## 错误处理

| 异常 | 触发 | 可重试 |
|---|---|---|
| `AuthenticationError` | 8889 / 401，密钥问题 | 否 |
| `RateLimitError` | 9002/9003 / 429 限流 | 是（按 Retry-After） |
| `ValidationError` | 9001 参数错误 | 否 |
| `CapabilityError` | 0002 数据源未接入 | 否 |
| `ApiError` | 0001 通用业务错误 | 视信封 |
| `NetworkError` | 超时/连接失败/5xx | 是 |

## 重新生成模型层

数据模型由 OpenAPI 契约生成，**不要手改** `src/isud_sdk/models.py`：

```bash
python -m datamodel_codegen \
  --input openapi.yaml --input-file-type openapi \
  --output-model-type dataclasses.dataclass \
  --target-python-version 3.11 \
  --output src/isud_sdk/models.py
```

## 契约与文档

- 契约源：<https://docs.isud.cn/openapi.yaml>
- 完整文档：<https://docs.isud.cn/>
- 设计规范：[SDK-DESIGN.md](SDK-DESIGN.md)

## License

MIT
