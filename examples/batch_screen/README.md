# 示例 2：批量风险筛查

读 CSV 批量检索商标，汇总高/中/低风险，导出结果 CSV。适合知产代理人日常批量排查。

## 运行（3 步）

```bash
pip install isud-tm
export ISUD_API_KEY="lgr_live_你的密钥"
python main.py marks.sample.csv results.csv CN
```

> 密钥从 https://app.isud.cn 控制台创建，**注册即送调用次数**。

## 输入 / 输出

输入 `marks.sample.csv`：每行一个商标名，`#` 开头为注释。

输出 `results.csv`：商标名、命中总数、高/中/低风险、结论、requestId（可用 `client.query_request_log()` 回查每次调用）。

## 演示的能力

- **幂等键**：用业务序号当 `idempotency_key`，脚本重跑不重复扣点
- **429 退避**：检索类 30 次/分钟，SDK 自动按 Retry-After 退避；示例额外做了 2s 节流
- **用量对账**：跑完调 `get_usage()` 看剩余点数
- **批量容错**：单个商标失败不影响整批，错误逐行记录
