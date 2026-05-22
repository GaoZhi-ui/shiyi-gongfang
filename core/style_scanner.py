"""
句式密度扫描器 — 检测写作惯性句式
在保存时自动运行，标记过度使用的句式模式
"""

import re
from pathlib import Path

# 需要监控的句式模式
PATTERNS = [
    {
        "name": "不是而是",
        "regex": r'不是[^。。，；！？]*?是[^。。，；！？]*?[。。，]',
        "limit": 2,
        "message": '"不是A而是B"句式: 建议改为直接肯定句',
    },
    {
        "name": "但",
        "regex": r'[。，；！？]但',
        "limit": 8,
        "message": '段落开头"但"字过多: 尝试用"可是""不过""然而"交替',
    },
    {
        "name": "却",
        "regex": r'，却',
        "limit": 3,
        "message": '"却"字过密: 考虑直接陈述对比',
    },
    {
        "name": "没有……只有",
        "regex": r'没有[^。]*只有',
        "limit": 2,
        "message": '"没有……只有"句式: 尝试改为直接描写',
    },
]


def scan_patterns(text: str) -> list[dict]:
    """扫描文本中的句式模式，返回超出阈值的模式列表"""
    results = []
    lines = text.split("\n")
    
    for pattern in PATTERNS:
        count = 0
        positions = []
        for i, line in enumerate(lines, 1):
            for m in re.finditer(pattern["regex"], line):
                count += 1
                positions.append({
                    "line": i,
                    "content": m.group()[:40],
                })
        
        if count > pattern["limit"]:
            results.append({
                "name": pattern["name"],
                "count": count,
                "limit": pattern["limit"],
                "message": pattern["message"],
                "positions": positions,
            })
    
    return results


def density_report(text: str) -> dict:
    """返回完整密度报告"""
    issues = []
    
    # 句式模式
    patterns = scan_patterns(text)
    for p in patterns:
        issues.append({
            "type": "pattern_density",
            "severity": "warning" if p["count"] > p["limit"] + 2 else "info",
            "message": f'{p["message"]}（当前{p["count"]}次，上限{p["limit"]}次）',
        })
    
    return {
        "issues": issues,
        "pattern_count": len(patterns),
    }
