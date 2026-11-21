# 示例 1：近似商标排查

输入一个商标名，返回近似商标的风险分级（高/中/低）与结论文案。

## 运行

```bash
pip install isud-sdk
export ISUD_API_KEY="lgr_live_你的密钥"
python main.py 优标宝 CN
```

> 密钥从 https://app.isud.cn 控制台创建，**注册即送调用次数**。

## 输出示例

```
法域: CN  关键词: 优标宝
命中 3 件 | 高 0 | 中 1 | 低 2
结论: 存在中度相似商标，建议进一步人工评估
来源: cnipa  耗时: 2150ms

   1. 优标                   [medium] 已申请  西安优标工贸有限公司  申请号 48659599  到期 2025-08-01
   2. 优标宝科技             [low] 已注册  ...
✓ 本次扣点 10 | 剩余 990 | requestId req_feceda8ebe11ee0c
```

演示的能力：环境变量读 key、响应信封解析、扣点回读、错误友好提示（不裸 traceback）。
