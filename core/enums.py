"""
写作助手工坊 — 枚举类型系统

受 NovelWriter 的 nwItemType / Class / Layout 三层约束设计启发，
为章节、场景、伏笔、角色关系、写作目标提供类型安全的枚举约束。

每个枚举类均包含：
  - 字符串值（可直接用于 JSON 序列化）
  - .description 属性（用于 API 文档展示 / OpenAPI schema）
  - __str__ 返回枚举值本身
"""

from enum import Enum


class ChapterStatus(str, Enum):
    """章节状态"""

    DRAFT = "draft"
    REVIEWING = "reviewing"
    FINAL = "final"
    ABANDONED = "abandoned"

    @property
    def description(self) -> str:
        return {
            "draft": "草稿，仍在编写中",
            "reviewing": "审阅中，等待修改或确认",
            "final": "定稿，不再修改",
            "abandoned": "废弃，不再使用",
        }[self.value]

    def __str__(self) -> str:
        return self.value


class SceneType(str, Enum):
    """场景类型，描述一个场景的核心叙事功能"""

    NARRATION = "narration"
    DIALOGUE = "dialogue"
    ACTION = "action"
    REFLECTION = "reflection"
    TRANSITION = "transition"

    @property
    def description(self) -> str:
        return {
            "narration": "叙事，以描写和叙述为主推进情节",
            "dialogue": "对话密集，角色间交流是核心内容",
            "action": "动作场景，包含打斗、追逐等动态描写",
            "reflection": "内心独白，展示角色内心世界与思绪",
            "transition": "过渡，连接前后场景的桥段",
        }[self.value]

    def __str__(self) -> str:
        return self.value


class ForeshadowingType(str, Enum):
    """伏笔类型，标记伏笔作用的对象维度"""

    PLOT = "plot"
    CHARACTER = "character"
    OBJECT = "object"
    LORE = "lore"

    @property
    def description(self) -> str:
        return {
            "plot": "情节伏笔，为后续事件埋下线索",
            "character": "角色伏笔，揭示角色隐藏的身份或动机",
            "object": "物品伏笔，特定物品将在后续发挥关键作用",
            "lore": "世界观伏笔，暗示世界设定中的深层秘密",
        }[self.value]

    def __str__(self) -> str:
        return self.value


class ForeshadowingStatus(str, Enum):
    """伏笔状态，追踪伏笔从埋设到回收的完整生命周期"""

    PENDING = "pending"
    REVEALED = "revealed"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"

    @property
    def description(self) -> str:
        return {
            "pending": "待回收，伏笔已埋设但尚未揭示",
            "revealed": "已揭示，伏笔已被读者察觉但未完全解决",
            "resolved": "已回收，伏笔已完整收束",
            "abandoned": "已废弃，不再追踪或主动放弃回收",
        }[self.value]

    def __str__(self) -> str:
        return self.value


class RelationType(str, Enum):
    """角色关系类型，描述两个角色之间的基本关系属性"""

    FRIEND = "friend"
    RIVAL = "rival"
    NEUTRAL = "neutral"
    FAMILY = "family"
    MENTOR = "mentor"
    ENEMY = "enemy"

    @property
    def description(self) -> str:
        return {
            "friend": "朋友，友好互助关系",
            "rival": "对手，良性竞争关系",
            "neutral": "中立，无明显倾向",
            "family": "家人，血缘或亲情纽带",
            "mentor": "师徒，教导与传承关系",
            "enemy": "敌人，敌对冲突关系",
        }[self.value]

    def __str__(self) -> str:
        return self.value


class GoalStatus(str, Enum):
    """写作目标状态"""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @property
    def description(self) -> str:
        return {
            "active": "进行中，目标尚未完成",
            "completed": "已完成，目标达成",
            "cancelled": "已取消，不再追求此目标",
        }[self.value]

    def __str__(self) -> str:
        return self.value
