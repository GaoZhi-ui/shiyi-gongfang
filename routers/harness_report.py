"""
工具调用 Harness 统计报告

提供工具调用的实时运行统计信息，数据保存在内存中。
不落盘，重启后统计清零。

GET /api/v1/harness/stats — 返回工具调用的统计信息
"""

from __future__ import annotations

import time
import threading
from fastapi import APIRouter

router = APIRouter(prefix="/harness", tags=["harness"])

# ─── 内存统计存储（线程安全） ───

_lock = threading.Lock()

_stats = {
    "total_calls": 0,
    "total_errors": 0,
    "total_time_ms": 0.0,
    "per_tool": {},
    "started_at": None,  # type: float | None
}


def _ensure_tool(name: str) -> None:
    """确保该工具已存在于 per_tool 统计字典中"""
    if name not in _stats["per_tool"]:
        _stats["per_tool"][name] = {
            "calls": 0,
            "errors": 0,
            "total_time_ms": 0.0,
        }


def record_call(tool_name: str, duration_ms: float, is_error: bool = False) -> None:
    """记录一次工具调用

    Args:
        tool_name: 工具名称
        duration_ms: 执行耗时（毫秒）
        is_error: 是否出错
    """
    with _lock:
        if _stats["started_at"] is None:
            _stats["started_at"] = time.time()

        _stats["total_calls"] += 1
        _stats["total_time_ms"] += duration_ms
        if is_error:
            _stats["total_errors"] += 1

        _ensure_tool(tool_name)
        _stats["per_tool"][tool_name]["calls"] += 1
        _stats["per_tool"][tool_name]["total_time_ms"] += duration_ms
        if is_error:
            _stats["per_tool"][tool_name]["errors"] += 1


def _compute_stats() -> dict:
    """从原始统计数据计算汇总指标（带锁）"""
    with _lock:
        total = _stats["total_calls"]
        avg_time = round(_stats["total_time_ms"] / total, 2) if total > 0 else 0.0
        fail_rate = round(_stats["total_errors"] / total * 100, 2) if total > 0 else 0.0

        per_tool = {}
        for name, data in _stats["per_tool"].items():
            t = data["calls"]
            per_tool[name] = {
                "calls": t,
                "errors": data["errors"],
                "avg_time_ms": round(data["total_time_ms"] / t, 2) if t > 0 else 0.0,
                "fail_rate": round(data["errors"] / t * 100, 2) if t > 0 else 0.0,
            }

        uptime = round(time.time() - (_stats["started_at"] or time.time()))

        return {
            "total_calls": total,
            "total_errors": _stats["total_errors"],
            "fail_rate": fail_rate,
            "avg_time_ms": avg_time,
            "uptime_seconds": uptime,
            "per_tool": per_tool,
        }


# ─── 路由 ───


@router.get("/stats")
def get_harness_stats():
    """返回工具调用的统计信息（总调用次数、失败率、平均耗时、按工具细分）"""
    return _compute_stats()


@router.get("/stats/reset")
def reset_harness_stats():
    """重置统计信息（仅开发/调试用）"""
    with _lock:
        _stats["total_calls"] = 0
        _stats["total_errors"] = 0
        _stats["total_time_ms"] = 0.0
        _stats["per_tool"].clear()
        _stats["started_at"] = None
    return {"status": "reset"}
