"""
拼写检查路由

POST /api/v1/spell/check  — 检查文本拼写

路径前缀 /api/v1/spell
"""

from __future__ import annotations

import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/spell", tags=["spell"])

# 按需加载 — 只有英文检查时使用该库
_spellchecker = None


def _get_checker():
    global _spellchecker
    if _spellchecker is None:
        from spellchecker import SpellChecker

        _spellchecker = SpellChecker()
    return _spellchecker


class SpellCheckBody(BaseModel):
    text: str = Field(..., min_length=1, description="要检查的文本")
    language: str = Field(
        default="en",
        description="语言代码，zh=中文/混合，en=英文",
    )


class MisspellingItem(BaseModel):
    word: str
    suggestions: list[str]
    start: int
    end: int


class SpellCheckResponse(BaseModel):
    misspellings: list[MisspellingItem]


def _en_check(text: str) -> list[MisspellingItem]:
    """英文拼写检查"""
    checker = _get_checker()

    # 用正则提取英文单词（排除数字、带数字的 token、空串）
    tokens = re.finditer(r"[A-Za-z][A-Za-z\']*", text)
    candidates: list[tuple[str, int, int]] = []
    for m in tokens:
        word = m.group()
        start = m.start()
        end = m.end()
        # 跳过首字母大写的专有名词（仅首字母大写且后面全是小写）
        # 但保留全大写的缩写和混合大小写
        candidates.append((word, start, end))

    misspelled_words = checker.unknown([w for w, _, _ in candidates])
    if not misspelled_words:
        return []

    results: list[MisspellingItem] = []
    for word, start, end in candidates:
        if word.lower() not in misspelled_words:
            continue
        suggestions = list(checker.candidates(word) or [])
        # 过滤掉 None
        suggestions = [s for s in suggestions if s is not None]
        # 排序：编辑距离短的优先
        suggestions.sort(key=lambda s: len(s) - len(word) if len(s) >= len(word) else 999)
        results.append(
            MisspellingItem(
                word=word,
                suggestions=suggestions[:5],  # 最多 5 条
                start=start,
                end=end,
            )
        )

    return results


@router.post("/check")
def spell_check(body: SpellCheckBody):
    """对文本执行拼写检查"""
    text = body.text
    lang = (body.language or "en").strip().lower()

    if not text.strip():
        return SpellCheckResponse(misspellings=[])

    if lang.startswith("zh"):
        # 中文暂不处理（pyspellchecker 仅支持英文）
        misspellings: list[MisspellingItem] = []
    else:
        misspellings = _en_check(text)

    return SpellCheckResponse(misspellings=misspellings)
