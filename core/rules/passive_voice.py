"""
被动语态检测规则

检测"被"字句，提示改为主动语态。
"""

from __future__ import annotations

import re

from core.writing_rules import WritingIssue, WritingRule

_PASSIVE_PATTERN = re.compile(r"被[\u4e00-\u9fff]+")


class PassiveVoiceRule(WritingRule):
    name = "passive_voice"
    description = "检测被动语态（被字句）"
    severity = "warning"

    def check(self, text: str) -> list[WritingIssue]:
        issues: list[WritingIssue] = []
        for line_idx, line_text in enumerate(text.split("\n"), 1):
            stripped = line_text.strip()
            if not stripped:
                continue
            for match in _PASSIVE_PATTERN.finditer(stripped):
                issues.append(
                    WritingIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        line=line_idx,
                        content=match.group(),
                        suggestion=(
                            "被动语态使动作主体模糊。尝试改为主动语态，"
                            "明确谁做了什么。"
                        ),
                    )
                )
        return issues
