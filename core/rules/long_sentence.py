"""
长句检测规则

检测超过 40 个中文字符的长句，
提示拆分为短句以改善阅读节奏。
"""

from __future__ import annotations

import re

from core.writing_rules import WritingIssue, WritingRule

_SENTENCE_SPLIT = re.compile(r"[^。！？\n]+[。！？\n]")
_RE_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_MAX_CJK = 40


class LongSentenceRule(WritingRule):
    name = "long_sentence"
    description = "检测长句（超过40个中文字）"
    severity = "info"

    def check(self, text: str) -> list[WritingIssue]:
        issues: list[WritingIssue] = []

        for sentence in _SENTENCE_SPLIT.findall(text):
            stripped = sentence.strip()
            if not stripped:
                continue
            cjk_count = len(_RE_CJK.findall(stripped))
            if cjk_count > _MAX_CJK:
                line_no = self._find_line(text, stripped)
                issues.append(
                    WritingIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        line=line_no,
                        content=stripped,
                        suggestion=(
                            "句子过长影响阅读节奏。建议拆分为 2-3 个短句，"
                            "每个句子承载一个核心信息。"
                        ),
                    )
                )

        return issues

    @staticmethod
    def _find_line(text: str, target: str) -> int:
        """在文本中定位目标字符串首次出现的行号（1-indexed）"""
        idx = text.find(target)
        if idx == -1:
            return 1
        return text[:idx].count("\n") + 1
