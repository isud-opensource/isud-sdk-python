#!/usr/bin/env python3
"""示例 2：批量风险筛查。

读 CSV（每行一个商标名）→ 逐个检索 → 汇总风险 → 导出结果 CSV。
演示点：幂等键、429 退避（SDK 自动）、用量查询、批量场景的节流友好提示。

运行:
    pip install isud-tm
    export ISUD_API_KEY="lgr_live_你的密钥"
    python main.py marks.csv results.csv CN
"""

from __future__ import annotations

import csv
import os
import sys

from isud_tm import Client, SdkError, RateLimitError
from isud_tm.extras import write_csv

# 检索类 30 次/分钟；批量场景放慢一点更稳妥（SDK 已有 429 退避兜底）
BATCH_PAUSE = 2.0


def read_marks(path: str) -> list[str]:
    marks: list[str] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip() or row[0].strip().startswith("#"):
                continue
            marks.append(row[0].strip())
    return marks


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: python main.py <输入.csv> <输出.csv> [法域]")
        print("输入 CSV：每行一个商标名（可用 # 注释）")
        return 2
    in_path, out_path = sys.argv[1], sys.argv[2]
    jurisdiction = sys.argv[3] if len(sys.argv) > 3 else "CN"

    key = os.environ.get("ISUD_API_KEY")
    if not key:
        print("✗ 请先设置环境变量 ISUD_API_KEY（控制台创建，注册即送调用次数）")
        return 2

    marks = read_marks(in_path)
    if not marks:
        print("✗ 输入文件没有有效商标名")
        return 2

    client = Client(api_key=key)
    results: list[dict] = []
    print(f"开始筛查 {len(marks)} 个商标（法域 {jurisdiction}）...")
    for i, mark in enumerate(marks, 1):
        try:
            # 用业务序号当幂等键：重跑不重复扣点
            data = client.search_trademarks(
                jurisdictionCode=jurisdiction, keyword=mark,
                idempotency_key=f"batch-{jurisdiction}-{i:04d}",
            ) or {}
            row = {
                "商标名": mark,
                "命中总数": data.get("total", 0),
                "高风险": data.get("highRisk", 0),
                "中风险": data.get("mediumRisk", 0),
                "低风险": data.get("lowRisk", 0),
                "结论": data.get("conclusion", ""),
                "requestId": client.last_meta.request_id or "",
            }
            results.append(row)
            print(f"  [{i}/{len(marks)}] {mark}: 高{row['高风险']} 中{row['中风险']} 低{row['低风险']}")
        except RateLimitError as e:
            print(f"  [{i}/{len(marks)}] {mark}: 触发限流，SDK 已自动退避；仍失败 -> {e.message}")
            results.append({"商标名": mark, "结论": "限流失败", "requestId": e.request_id or ""})
        except SdkError as e:
            print(f"  [{i}/{len(marks)}] {mark}: {e.message}")
            results.append({"商标名": mark, "结论": f"失败:{e.code}", "requestId": e.request_id or ""})

        if i < len(marks) and BATCH_PAUSE:
            import time
            time.sleep(BATCH_PAUSE)

    n = write_csv(out_path, results)
    usage = None
    try:
        usage = client.get_usage()
    except SdkError:
        pass
    client.close()

    print(f"\n✓ 完成，已写出 {n} 行到 {out_path}")
    if usage:
        print(f"  剩余点数: {usage.get('balance')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
