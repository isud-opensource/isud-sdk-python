"""结果展示与导出 helper —— 示例项目直接复用，减少样板代码。"""

from __future__ import annotations

import csv
import io
import time
from typing import Any, Mapping, Sequence

# 风险等级展示顺序与符号（未知值兜底，见 SDK-DESIGN.md §9）
_RISK_ORDER = ("high", "medium", "low", "none")
_STATUS_ZH = {
    "Filed": "已申请", "Published": "已公布", "Registered": "已注册",
    "Expired": "已失效", "Withdrawn": "已撤回", "Refused": "已驳回", "Opposed": "异议中",
}


def format_date_ms(ms: int | None) -> str:
    """Unix 毫秒时间戳 → YYYY-MM-DD；0/None 返回 '未知'。"""
    if not ms:
        return "未知"
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ms / 1000))
    except (OverflowError, OSError, ValueError):
        return "未知"


def risk_summary(data: Mapping[str, Any] | None) -> str:
    """把检索结果的风险分级压成一行摘要。"""
    if not data:
        return "无结果"
    parts = [
        f"命中 {data.get('total', 0)} 件",
        f"高 {data.get('highRisk', 0)}",
        f"中 {data.get('mediumRisk', 0)}",
        f"低 {data.get('lowRisk', 0)}",
    ]
    return " | ".join(parts)


def format_search_result(data: Mapping[str, Any] | None, *, limit: int = 10) -> str:
    """人类可读的检索结果文本（给示例/终端直接打印）。"""
    if not data:
        return "（无结果）"
    lines = [
        f"法域: {data.get('jurisdictionCode', '-')}  关键词: {data.get('keyword', '-')}",
        risk_summary(data),
        f"结论: {data.get('conclusion', '-')}",
        f"来源: {data.get('source', '-')}  耗时: {data.get('elapsedMs', '-')}ms",
        "",
    ]
    items = data.get("items") or []
    if not items:
        lines.append("  没有近似商标记录。")
    for i, it in enumerate(items[:limit], 1):
        status = it.get("status", "-")
        status_zh = _STATUS_ZH.get(status, status)
        lines.append(
            f"  {i:>2}. {it.get('markText') or '(图形)':<20} "
            f"[{it.get('riskLevel', '-')}] {status_zh}  "
            f"{it.get('ownerName') or '-'}  "
            f"申请号 {it.get('applicationNumber') or '-'}  "
            f"到期 {format_date_ms(it.get('expiryDate'))}"
        )
    if len(items) > limit:
        lines.append(f"  ... 还有 {len(items) - limit} 条（用 size/current 翻页查看）")
    return "\n".join(lines)


def to_csv(
    rows: Sequence[Mapping[str, Any]],
    *,
    columns: Sequence[str] | None = None,
) -> str:
    """把记录列表导出成 CSV 字符串（UTF-8, 带 BOM 便于 Excel 打开中文）。"""
    if not rows:
        return ""
    cols = list(columns or rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in cols})
    return "\ufeff" + buf.getvalue()


def write_csv(path: str, rows: Sequence[Mapping[str, Any]], *, columns: Sequence[str] | None = None) -> int:
    """写 CSV 文件，返回写入行数。"""
    content = to_csv(rows, columns=columns)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return len(rows)


__all__ = [
    "format_search_result", "to_csv", "write_csv", "risk_summary", "format_date_ms",
]
