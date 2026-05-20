"""
填充词检测规则

检测可删除而不影响句意的冗余填充词：
突然、然后、其实、竟然、忽然、似乎、仿佛、有点、有些、开始
"""

from __future__ import annotations

import re

from core.writing_rules import WritingIssue, WritingRule

_FILLER_PATTERN = re.compile(
    r"(突然|然后|其实|竟然|忽然|似乎|仿佛|有点|有些|开始)"
)


class FillerWordsRule(WritingRule):
    name = "filler_words"
    description = "检测填充词（突然、然后、其实、竟然等）"
    severity = "warning"

    def check(self, text: str) -> list[WritingIssue]:
        issues: list[WritingIssue] = []
        for line_idx, line_text in enumerate(text.split("\n"), 1):
            stripped = line_text.strip()
            if not stripped:
                continue
            for match in _FILLER_PATTERN.finditer(stripped):
                issues.append(
                    WritingIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        line=line_idx,
                        content=match.group(),
                        suggestion=(
                            "填充词通常可删除而不影响句意。删除后句子更紧凑。"
                            "若需保留节奏感，可替换为更具象的描写。"
                        ),
                    )
                )
        return issues
