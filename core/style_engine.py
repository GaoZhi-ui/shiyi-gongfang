"""
写法引擎 — 可复用的写作风格资产系统

提供 Style（风格定义）、StyleRegistry（注册中心管理）、风格匹配分析。
对齐 MCP 工具架构，供 tool_definitions.py 注册使用。

类结构：
  Style          — 一个可复用的写作风格定义（含特征画像）
  StyleRegistry  — 全局风格注册中心（register / get / list / match）

全局入口：get_registry() 返回单例，自动注册 3 个内置风格。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


# ══════════════════════════════════════════════════════════════
# 正则预编译
# ══════════════════════════════════════════════════════════════

_RE_SENTENCE_END = re.compile(r"[。！？\n]+")
_RE_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_RE_DIALOGUE = re.compile(r"「[^」]*」|『[^』]*』|\u201c[^\u201d]*\u201d|\u2018[^\u2019]*\u2019")


# ══════════════════════════════════════════════════════════════
# Style 类
# ══════════════════════════════════════════════════════════════


@dataclass
class Style:
    """一个可复用的写法风格定义

    核心字段：
      name, description, rules, sample_text — 给编辑器/用户阅读使用

    特征画像（用于 match 算法）：
      sentence_mean_target     — 目标平均句长（CJK 字数）
      sentence_std_target      — 目标句长标准差
      dialogue_density_target  — 目标对话密度（对话CJK字数 / 总CJK字数）
      forbidden_words          — 禁用词列表（命中扣分）
      preferred_vocab          — 偏好词汇（仅信息，不计入评分）
    """

    name: str = ""
    description: str = ""
    rules: list[dict[str, Any]] = field(default_factory=list)
    sample_text: str = ""

    # ── 特征画像（match 用） ──
    sentence_mean_target: float = 20.0
    sentence_std_target: float = 8.0
    dialogue_density_target: float = 0.3
    forbidden_words: list[str] = field(default_factory=list)
    preferred_vocab: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 序列化的字典"""
        return {
            "name": self.name,
            "description": self.description,
            "rules": self.rules,
            "profile": {
                "sentence_mean_target": self.sentence_mean_target,
                "sentence_std_target": self.sentence_std_target,
                "dialogue_density_target": self.dialogue_density_target,
                "forbidden_words": list(self.forbidden_words),
                "preferred_vocab": list(self.preferred_vocab),
            },
            "sample_text": (
                self.sample_text[:200] + ("..." if len(self.sample_text) > 200 else "")
            ),
        }


# ══════════════════════════════════════════════════════════════
# 文本特征提取
# ══════════════════════════════════════════════════════════════


def extract_features(text: str) -> dict[str, Any]:
    """从一段文本中提取可测量的语言特征

    返回：
      total_cjk             — 中文字符总数
      avg_sentence_length   — 平均句长（字）
      sentence_length_std   — 句长标准差
      dialogue_density      — 对话密度（0.0 ~ 1.0）
      sentence_count        — 句子数
    """
    if not text or not text.strip():
        return {
            "total_cjk": 0,
            "avg_sentence_length": 0.0,
            "sentence_length_std": 0.0,
            "dialogue_density": 0.0,
            "sentence_count": 0,
        }

    # 中文字符
    cjk_chars = _RE_CJK.findall(text)
    total_cjk = len(cjk_chars)

    # 分句（按 。！？ 断开）
    raw_sentences = _RE_SENTENCE_END.split(text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    sentence_lengths = [
        len(_RE_CJK.findall(s)) for s in sentences if _RE_CJK.search(s)
    ]
    sentence_count = len(sentence_lengths)

    # 平均句长
    avg_length = sum(sentence_lengths) / sentence_count if sentence_count > 0 else 0.0

    # 句长标准差
    if sentence_count > 1:
        variance = sum((l - avg_length) ** 2 for l in sentence_lengths) / sentence_count
        std_length = math.sqrt(variance)
    else:
        std_length = 0.0

    # 对话密度
    dialogue_chars = 0
    for m in _RE_DIALOGUE.finditer(text):
        dialogue_chars += len(_RE_CJK.findall(m.group()))
    dialogue_density = dialogue_chars / total_cjk if total_cjk > 0 else 0.0

    return {
        "total_cjk": total_cjk,
        "avg_sentence_length": round(avg_length, 2),
        "sentence_length_std": round(std_length, 2),
        "dialogue_density": round(dialogue_density, 4),
        "sentence_count": sentence_count,
    }


# ══════════════════════════════════════════════════════════════
# 风格匹配
# ══════════════════════════════════════════════════════════════


def _gaussian_score(diff: float, sigma: float) -> float:
    """高斯衰减评分 — diff 越小越接近 1.0，超出 sigma 迅速衰减"""
    if sigma <= 0:
        return 1.0 if diff == 0 else 0.0
    return math.exp(-((diff / sigma) ** 2) / 2)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def match_style(text: str, style: Style) -> dict[str, Any]:
    """计算一段文本与某个风格的匹配度，返回详细评分

    四个维度加权综合：
      - 句长均值匹配（35%）
      - 句长方差匹配（15%）
      - 对话密度匹配（25%）
      - 禁用词罚分（25%，反向）
    """
    features = extract_features(text)
    total_cjk = features["total_cjk"]

    if total_cjk == 0:
        return {
            "style": style.name,
            "score": 0.0,
            "details": {},
            "features": features,
            "forbidden_word_hits": None,
        }

    # ── 1. 句长均值匹配（权重 0.35） ──
    length_diff = abs(features["avg_sentence_length"] - style.sentence_mean_target)
    # sigma 为目标均值的 30%，至少 3 字
    sigma_len = max(style.sentence_mean_target * 0.3, 3.0)
    length_score = _gaussian_score(length_diff, sigma_len)

    # ── 2. 句长标准差匹配（权重 0.15） ──
    std_diff = abs(features["sentence_length_std"] - style.sentence_std_target)
    sigma_std = max(style.sentence_std_target * 0.3, 2.0)
    std_score = _gaussian_score(std_diff, sigma_std)

    # ── 3. 对话密度匹配（权重 0.25） ──
    density_diff = abs(features["dialogue_density"] - style.dialogue_density_target)
    sigma_density = 0.2  # 对话密度偏离 20% 开始明显衰减
    density_score = _gaussian_score(density_diff, sigma_density)

    # ── 4. 禁用词罚分（权重 0.25，反向） ──
    forbidden_hits: dict[str, int] = {}
    forbidden_penalty = 0.0
    if style.forbidden_words:
        for word in style.forbidden_words:
            count = text.count(word)
            if count > 0:
                forbidden_hits[word] = count
                # 每 100 字命中一次扣 5%
                penalty = (count / max(total_cjk / 100, 1)) * 0.05
                forbidden_penalty += penalty
        forbidden_penalty = min(forbidden_penalty, 1.0)
    forbidden_score = 1.0 - forbidden_penalty

    # ── 综合评分（百分制） ──
    raw_score = (
        length_score * 0.35
        + std_score * 0.15
        + density_score * 0.25
        + forbidden_score * 0.25
    )
    final_score = round(_clamp(raw_score * 100), 1)

    # 只保留命中的禁用词
    hits = forbidden_hits if forbidden_hits else None

    return {
        "style": style.name,
        "score": final_score,
        "details": {
            "sentence_length_match": round(_clamp(length_score * 100), 1),
            "sentence_std_match": round(_clamp(std_score * 100), 1),
            "dialogue_density_match": round(_clamp(density_score * 100), 1),
            "forbidden_word_penalty": round(_clamp(forbidden_penalty * 100), 1),
        },
        "features": features,
        "forbidden_word_hits": hits,
    }


# ══════════════════════════════════════════════════════════════
# StyleRegistry
# ══════════════════════════════════════════════════════════════


class StyleRegistry:
    """写法风格注册中心 — 管理所有可复用的写作风格资产

    用法：
      registry = get_registry()
      style = registry.get("冷峻克制")
      results = registry.match("一段文本...")
    """

    def __init__(self) -> None:
        self._styles: dict[str, Style] = {}

    # ── 增删查 ──

    def register(self, style: Style) -> None:
        """注册一个风格。同名不可重复注册。"""
        if not isinstance(style, Style):
            raise TypeError(f"Expected Style instance, got {type(style).__name__}")
        if style.name in self._styles:
            raise ValueError(f"Style '{style.name}' is already registered")
        self._styles[style.name] = style

    def get(self, name: str) -> Style | None:
        """按名称获取风格"""
        return self._styles.get(name)

    def list(self) -> list[Style]:
        """列出所有已注册的风格"""
        return list(self._styles.values())

    def clear(self) -> None:
        """清空所有注册（仅测试用）"""
        self._styles.clear()

    # ── 匹配 ──

    def match(self, text: str) -> list[dict[str, Any]]:
        """分析文本，返回按匹配度降序排列的风格评分列表"""
        if not text or not text.strip():
            return []

        results = [match_style(text, style) for style in self._styles.values()]
        results.sort(key=lambda r: r["score"], reverse=True)
        return results


# ══════════════════════════════════════════════════════════════
# 全局单例 + 内置风格注册
# ══════════════════════════════════════════════════════════════

_default_registry: StyleRegistry | None = None


def get_registry() -> StyleRegistry:
    """获取全局 StyleRegistry 单例，首次调用自动注册 3 个内置风格"""
    global _default_registry
    if _default_registry is None:
        _default_registry = StyleRegistry()
        _register_builtin_styles(_default_registry)
    return _default_registry


def _register_builtin_styles(registry: StyleRegistry) -> None:
    """注册 3 个内置写法风格"""

    # ═══════════════════════════════════════════
    # 1. 冷峻克制 — 冷色调叙事风格
    # ═══════════════════════════════════════════

    registry.register(Style(
        name="冷峻克制",
        description=(
            "冷色调叙事风格，克制抒情，"
            "以军旅视角观察异世界。用最短的句子传递最重的信息。"
            "留白优先，不帮读者总结。适合战争、历史、反思场景。"
        ),
        rules=[
            {
                "type": "sentence_length",
                "description": "中短句为主，平均 15-25 字，避免超过 40 字的长句",
                "params": {"min": 8, "max": 40, "target": 18},
            },
            {
                "type": "dialogue_density",
                "description": "对话篇幅控制在 30% 以下",
                "params": {"target": 0.25},
            },
            {
                "type": "metaphor",
                "description": "克制使用比喻，偏好军事术语、历史典故、地理意象",
                "params": {},
            },
            {
                "type": "forbidden_words",
                "description": "禁用过度阐释的副词和判断词",
                "params": {},
            },
            {
                "type": "rhythm",
                "description": "章节衔接情绪不归零、不重复。地震级信息用最短的句子。",
                "params": {},
            },
        ],
        sample_text=(
            "他站在城墙上，看着远处的地平线。\n"
            "那里曾经有一座城。\n"
            "现在只剩下废墟。\n\n"
            "「走吧。」队长说，声音没有起伏。\n\n"
            "他最后看了一眼。转身。\n"
            "身后是废墟。前方也是废墟。\n"
            "区别在于，前方的废墟还有人活着。"
        ),
        sentence_mean_target=18.0,
        sentence_std_target=10.0,
        dialogue_density_target=0.25,
        forbidden_words=[
            "明显", "显然", "突然", "忽然",
            "似乎", "仿佛", "居然", "竟然",
            "大概", "也许", "可能",
        ],
        preferred_vocab=[
            "沉默", "寂静", "废墟", "钢铁", "水泥",
            "荒野", "地平线", "界限", "秩序", "规则",
        ],
    ))

    # ═══════════════════════════════════════════
    # 2. 轻快日常
    # ═══════════════════════════════════════════

    registry.register(Style(
        name="轻快日常",
        description=(
            "轻松明快的日常叙事风格。节奏活泼，对话密集，"
            "适合日常互动、轻松场景、人物交流。短句搭配口语化表达，"
            "比喻偏好生活化意象。"
        ),
        rules=[
            {
                "type": "sentence_length",
                "description": "短句为主，平均 10-18 字，避免沉闷的长叙述",
                "params": {"min": 3, "max": 30, "target": 14},
            },
            {
                "type": "dialogue_density",
                "description": "对话比例高，50% 以上",
                "params": {"target": 0.55},
            },
            {
                "type": "metaphor",
                "description": "生活化比喻，偏好食物、动物、日常物品",
                "params": {},
            },
            {
                "type": "forbidden_words",
                "description": "避免冗长修饰语叠放、矫情抒情",
                "params": {},
            },
            {
                "type": "tone",
                "description": "语言轻快活泼，可适当使用语气词和口语表达",
                "params": {},
            },
        ],
        sample_text=(
            "「今天吃什么？」她趴在桌上，下巴搁在胳膊上。\n\n"
            "「随便。」\n\n"
            "「又是随便！上次随便你点了个凉菜都辣哭了。」\n\n"
            "他翻了个白眼。「这次真随便，你定。」\n\n"
            "她眼睛亮了，像只偷到鱼的猫。"
        ),
        sentence_mean_target=14.0,
        sentence_std_target=7.0,
        dialogue_density_target=0.55,
        forbidden_words=[
            "凄美", "氤氲", "缱绻", "旖旎", "潸然", "莞尔",
            "无比", "极致", "万分", "极其",
        ],
        preferred_vocab=[
            "笑", "暖", "甜", "软", "亮",
            "暖洋洋", "慢悠悠", "晃悠", "嘀咕", "嘟囔",
        ],
    ))

    # ═══════════════════════════════════════════
    # 3. 严肃叙事
    # ═══════════════════════════════════════════

    registry.register(Style(
        name="严肃叙事",
        description=(
            "厚重、沉着的严肃叙事。中长句交替，节奏稳健，"
            "适合正史、宏大场景、沉重主题。偏好史诗感和自然意象，"
            "避免轻浮表达和语气词。"
        ),
        rules=[
            {
                "type": "sentence_length",
                "description": "中长句交替，平均 18-30 字，允许 40-60 字的长句",
                "params": {"min": 10, "max": 60, "target": 24},
            },
            {
                "type": "dialogue_density",
                "description": "对话比例中低，20-40%",
                "params": {"target": 0.30},
            },
            {
                "type": "metaphor",
                "description": "宏大叙事类比，偏好史诗、战争、自然意象",
                "params": {},
            },
            {
                "type": "forbidden_words",
                "description": "禁用语气词、轻浮表达、网络用语",
                "params": {},
            },
            {
                "type": "tone",
                "description": "保持庄重克制的语调，叙述者视角稳定",
                "params": {},
            },
        ],
        sample_text=(
            "潮水拍打着礁石，一遍又一遍，像时间本身一样不知疲倦。\n\n"
            "这座岛屿曾经是一个帝国的边境哨站。三百年来，驻军换了一茬又一茬，"
            "灯塔上的火从未熄灭。直到某个平常的黄昏，补给船再也没有出现。\n\n"
            "「帝国已经不存在了。」老灯塔看守人说这话的时候，语气平淡得像在说天气。\n\n"
            "没有人追问。也不需要追问。大海知道一切，而大海从不说话。"
        ),
        sentence_mean_target=24.0,
        sentence_std_target=12.0,
        dialogue_density_target=0.30,
        forbidden_words=[
            "哈哈", "嘻嘻", "嘿嘿", "哇塞",
            "哎呀", "哎哟", "我去", "卧槽",
            "～", "啦", "呗", "嘛", "喔",
        ],
        preferred_vocab=[
            "时间", "大地", "天空", "海", "山", "风", "火",
            "血", "铁", "秩序", "宿命", "轮回", "苍茫",
        ],
    ))
