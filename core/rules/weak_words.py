"""
弱词检测规则

检测表达模糊、缺乏力度的词汇：
觉得、感到、认为、好像、也许、大概、可能
"""

from __future__ import annotations

import re

from core.writing_rules import WritingIssue, WritingRule

_WEAK_PATTERN = re.compile(
    r"(觉得|感到|认为|好像|也许|大概|可能)"
)


class WeakWordsRule(WritingRule):
    name = "weak_words"
    description = "检测弱词（觉得、感到、认为、好像等）"
    severity = "warning"

    def check(self, text: str) -> list[WritingIssue]:
        issues: list[WritingIssue] = []
        for line_idx, line_text in enumerate(text.split("\n"), 1):
            stripped = line_text.strip()
            if not stripped:
                continue
            for match in _WEAK_PATTERN.finditer(stripped):
                issues.append(
                    WritingIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        line=line_idx,
                        content=match.group(),
                        suggestion=(
                            "弱词使表达模糊。尝试用具体行为或感官描写替代主观判断。"
                            "展示，而非告诉。"
                        ),
                    )
                )
        return issues
