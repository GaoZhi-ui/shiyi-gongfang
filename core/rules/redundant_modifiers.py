"""
冗余修饰检测规则

检测"副词 + 形容词"的冗余修饰组合：
非常/极其/太/很/十分/特别/相当/无比/极度 + 形容词
"""

from __future__ import annotations

import re

from core.writing_rules import WritingIssue, WritingRule

_MODIFIERS_PATTERN = re.compile(
    r"(非常|极其|太|很|十分|特别|相当|无比|极度)\s*[\u4e00-\u9fff]+"
)


class RedundantModifiersRule(WritingRule):
    name = "redundant_modifiers"
    description = "检测冗余修饰（非常/极其/太/很 + 形容词）"
    severity = "warning"

    def check(self, text: str) -> list[WritingIssue]:
        issues: list[WritingIssue] = []
        for line_idx, line_text in enumerate(text.split("\n"), 1):
            stripped = line_text.strip()
            if not stripped:
                continue
            for match in _MODIFIERS_PATTERN.finditer(stripped):
                issues.append(
                    WritingIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        line=line_idx,
                        content=match.group(),
                        suggestion=(
                            "冗余修饰削弱了表达的力度。尝试用更精准的动词或名词替代，"
                            "或用具体细节证明而非直接评价。"
                        ),
                    )
                )
        return issues
