"""
风格检查引擎

检测写作中的常见风格问题：填充词、冗余修饰、弱词、被动语态、长句。
每条检查结果返回 {rule, line, content, suggestion} 结构。

用法：
    checker = StyleChecker()
    results = checker.check("一段文本...")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ─── 结果结构 ───


@dataclass
class CheckResult:
    """单条检查结果"""

    rule: str  # 规则标识
    line: int  # 行号（1-indexed）
    content: str  # 命中的原文片段
    suggestion: str  # 修改建议


# ══════════════════════════════════════════════════════════════
# 规则定义
# ══════════════════════════════════════════════════════════════

# 填充词：可删除而不影响句意的冗余词
_FILLER_WORDS_PATTERN = re.compile(
    r"(突然|然后|其实|竟然|忽然|似乎|仿佛|有点|有些|开始)"
)

# 冗余修饰：副词 + 形容词组合（"非常漂亮"、"极其寒冷"、"太危险"、"很快"）
_REDUNDANT_MODIFIERS_PATTERN = re.compile(
    r"(非常|极其|太|很|十分|特别|相当|无比|极度)\s*[\u4e00-\u9fff]+"
)

# 弱词：表达模糊、缺乏力度的词汇
_WEAK_WORDS_PATTERN = re.compile(
    r"(觉得|感到|认为|好像|也许|大概|可能)")
# 注意：排除"感到"在特定语境下的合理使用，
# 但作为通用规则先全部检出，由人工判断。

# 被动语态："被"字句
_PASSIVE_VOICE_PATTERN = re.compile(r"被[\u4e00-\u9fff]+")

# 长句：超过 40 个字的句子
_LONG_SENTENCE_PATTERN = re.compile(r"[^。！？\n]+[。！？\n]")

_RE_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


# ─── 建议映射 ───

_SUGGESTIONS: dict[str, str] = {
    "filler_words": (
        "填充词通常可删除而不影响句意。删除后句子更紧凑。"
        "若需保留节奏感，可替换为更具象的描写。"
    ),
    "redundant_modifiers": (
        "冗余修饰削弱了表达的力度。尝试用更精准的动词或名词替代，"
        "或用具体细节证明而非直接评价。"
    ),
    "weak_words": (
        "弱词使表达模糊。尝试用具体行为或感官描写替代主观判断。"
        "展示，而非告诉。"
    ),
    "passive_voice": (
        "被动语态使动作主体模糊。尝试改为主动语态，"
        "明确谁做了什么。"
    ),
    "long_sentence": (
        "句子过长影响阅读节奏。建议拆分为 2-3 个短句，"
        "每个句子承载一个核心信息。"
    ),
}


# ══════════════════════════════════════════════════════════════
# StyleChecker
# ══════════════════════════════════════════════════════════════


class StyleChecker:
    """写作风格检查器。

    内置规则：
      - filler_words:      检测填充词（突然、然后、其实、竟然等）
      - redundant_modifiers: 检测冗余修饰（非常/极其/太/很 + 形容词）
      - weak_words:        检测弱词（觉得、感到、认为、好像等）
      - passive_voice:     检测被动语态（被字句）
      - long_sentence:     检测超过 40 个中文字的长句

    用法：
        checker = StyleChecker()
        results = checker.check("一段文字...")
        # 可选启用特定规则：
        results = checker.check("...", rules=["filler_words", "long_sentence"])
    """

    def __init__(self):
        self._rule_registry: dict[str, dict[str, Any]] = {
            "filler_words": {
                "pattern": _FILLER_WORDS_PATTERN,
                "suggestion": _SUGGESTIONS["filler_words"],
                "description": "检测填充词",
            },
            "redundant_modifiers": {
                "pattern": _REDUNDANT_MODIFIERS_PATTERN,
                "suggestion": _SUGGESTIONS["redundant_modifiers"],
                "description": "检测冗余修饰",
            },
            "weak_words": {
                "pattern": _WEAK_WORDS_PATTERN,
                "suggestion": _SUGGESTIONS["weak_words"],
                "description": "检测弱词",
            },
            "passive_voice": {
                "pattern": _PASSIVE_VOICE_PATTERN,
                "suggestion": _SUGGESTIONS["passive_voice"],
                "description": "检测被动语态",
            },
            "long_sentence": {
                "pattern": _LONG_SENTENCE_PATTERN,
                "suggestion": _SUGGESTIONS["long_sentence"],
                "description": "检测长句（超过40字）",
            },
        }

    def list_rules(self) -> list[dict[str, str]]:
        """列出所有可用的检查规则"""
        return [
            {
                "name": name,
                "description": info["description"],
                "suggestion": info["suggestion"],
            }
            for name, info in self._rule_registry.items()
        ]

    def check(
        self,
        text: str,
        rules: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """对文本执行风格检查。

        Args:
            text: 要检查的文本
            rules: 要启用的规则列表，None 表示全部启用

        Returns:
            按行号排序的检查结果列表，每项含：
              rule, line, content, suggestion
        """
        if not text or not text.strip():
            return []

        # 确定启用的规则
        if rules is None:
            active_rules = list(self._rule_registry.keys())
        else:
            active_rules = [
                r for r in rules if r in self._rule_registry
            ]

        results: list[CheckResult] = []

        # 行级规则：逐行扫描（filler_words, redundant_modifiers, weak_words, passive_voice）
        lines = text.split("\n")
        for line_idx, line_text in enumerate(lines, 1):
            stripped = line_text.strip()
            if not stripped:
                continue

            for rule_name in active_rules:
                if rule_name == "long_sentence":
                    continue  # 长句是跨行规则，单独处理

                info = self._rule_registry[rule_name]
                for match in info["pattern"].finditer(stripped):
                    results.append(
                        CheckResult(
                            rule=rule_name,
                            line=line_idx,
                            content=match.group(),
                            suggestion=info["suggestion"],
                        )
                    )

        # 长句规则：跨行，按句号/问号/感叹号/换行分句
        if "long_sentence" in active_rules:
            info = self._rule_registry["long_sentence"]
            # 用正则分句，保留句子结束符
            sentences = _LONG_SENTENCE_PATTERN.findall(text)
            for sentence in sentences:
                stripped_sent = sentence.strip()
                if not stripped_sent:
                    continue
                # 统计中文字数
                cjk_count = len(_RE_CJK.findall(stripped_sent))
                if cjk_count > 40:
                    # 定位行号：在原文中查找该句
                    line_no = _find_line_number(text, stripped_sent)
                    results.append(
                        CheckResult(
                            rule="long_sentence",
                            line=line_no,
                            content=stripped_sent,
                            suggestion=info["suggestion"],
                        )
                    )

        # 按行号排序
        results.sort(key=lambda r: (r.line, r.rule))

        return [r.__dict__ for r in results]


def _find_line_number(text: str, target: str) -> int:
    """在文本中定位目标字符串首次出现的行号（1-indexed）"""
    idx = text.find(target)
    if idx == -1:
        return 1
    return text[:idx].count("\n") + 1
