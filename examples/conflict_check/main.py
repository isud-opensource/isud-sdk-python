#!/usr/bin/env python3
"""示例 1：近似商标排查。

输入商标名 → 调 search_trademarks → 打印风险分级与结论。
演示点：key 从环境变量读、信封解析、扣点回读、友好异常。

运行（3 步跑通）:
    pip install isud-tm
    export ISUD_API_KEY="lgr_live_你的密钥"      # Windows: set ISUD_API_KEY=...
    python main.py 优标宝 CN
"""

from __future__ import annotations

import os
import sys

from isud_tm import Client, SdkError
from isud_tm.extras import format_search_result


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "优标宝"
    jurisdiction = sys.argv[2] if len(sys.argv) > 2 else "CN"

    key = os.environ.get("ISUD_API_KEY")
    if not key:
        print("✗ 请先设置环境变量 ISUD_API_KEY")
        print("  获取方式：注册 https://app.isud.cn 后在控制台创建密钥（注册即送调用次数）")
        return 2

    try:
        client = Client(api_key=key)
        data = client.search_trademarks(
            jurisdictionCode=jurisdiction, keyword=keyword, size=10
        )
        print(format_search_result(data))
        print()
        print(
            f"✓ 本次扣点 {client.last_meta.credits_charged} "
            f"| 剩余 {client.last_meta.credits_remaining} "
            f"| requestId {client.last_meta.request_id}"
        )
        client.close()
        return 0
    except SdkError as e:
        print(e.friendly())  # 友好提示，不裸 traceback
        return 1


if __name__ == "__main__":
    sys.exit(main())
