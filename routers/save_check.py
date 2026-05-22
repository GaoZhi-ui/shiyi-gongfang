"""
保存检查 — 章节保存时自动运行审查规则
在保存响应中返回 issues 列表，不等收到邮件才发现问题
"""

import re
from pathlib import Path

CJK = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

def check_chapter(content: str) -> list[dict]:
    """
    对章节内容运行自动检查，返回 issues 列表。
    每个 issue: { type, severity, message }
    """
    issues = []
    parts = content.split("---")
    body = parts[0]
    diary = parts[1] if len(parts) > 1 else ""

    cjk = len(CJK.findall(body))
    if cjk < 2000:
        issues.append({
            "type": "word_count",
            "severity": "error",
            "message": f"正文字数{cjk}（需2000+）"
        })

    # 句式重复：不是A而是B
    ptn = r'不是[^。。，；！？]*是[^。。，；！？]*[。。，；！？]'
    n = len(list(re.finditer(ptn, body)))
    if n >= 2:
        issues.append({
            "type": "sentence_pattern",
            "severity": "warning",
            "message": f'"不是A而是B"句式{n}次（上限2次）'
        })

    # 句号密度
    stops = body.count(chr(12290))
    if cjk > 0:
        d = stops / cjk * 100
        if d > 6:
            issues.append({
                "type": "period_density",
                "severity": "warning",
                "message": f"句号密度{d:.1f}/百字"
            })

    # "好的"过渡
    hao_de = len(re.findall(r'。好的，', body))
    if hao_de > 0:
        issues.append({
            "type": "transition",
            "severity": "info",
            "message": f'"好的"过渡{hao_de}处'
        })

    # 日记
    dcjk = len(CJK.findall(diary))
    if dcjk > 0:
        has_fact = bool(re.search(r'(天|到了|找到|遇到|发现)', diary))
        has_obs = bool(re.search(r'(看到|注意到|发现|想起)', diary))
        if not has_fact or not has_obs:
            tags = []
            if not has_fact: tags.append("缺事实")
            if not has_obs: tags.append("缺观察")
            issues.append({
                "type": "diary",
                "severity": "warning",
                "message": f"日记{''.join(tags)}"
            })

    return issues
