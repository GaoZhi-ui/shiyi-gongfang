"""
可扩展 WritingRule 插件系统

写作规则基类与注册中心。
规则文件置于 core/rules/ 目录下，继承 WritingRule 并注册即可自动生效。

用法：
    registry = RuleRegistry()
    registry.register(MyRule())
    issues = registry.check_all("一段文本...")
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ══════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════


@dataclass
class WritingIssue:
    """单条检查结果"""

    rule_name: str  # 规则标识
    severity: str  # error / warning / info
    line: int  # 行号（1-indexed）
    content: str  # 命中的原文片段
    suggestion: str  # 修改建议


# ══════════════════════════════════════════════════════════════
# 基类
# ══════════════════════════════════════════════════════════════


class WritingRule(ABC):
    """写作检查规则基类。

    子类需覆写以下类/实例属性：
      name, description, severity

    子类需实现：
      check(text) -> list[WritingIssue]
    """

    # ── 类级元数据 ──
    name: str = ""
    description: str = ""
    severity: str = "info"  # error / warning / info

    def __init_subclass__(cls, **kwargs):
        """自动校验子类是否定义了必要属性"""
        super().__init_subclass__(**kwargs)
        if cls is WritingRule:
            return
        # 只对非抽象子类做校验
        if not getattr(cls, "__abstractmethods__", frozenset()):
            if not cls.name:
                raise TypeError(f"{cls.__name__} 必须设置 name")
            if not cls.description:
                raise TypeError(f"{cls.__name__} 必须设置 description")

    @property
    def severity_level(self) -> int:
        """severity 对应的数值权重，用于排序"""
        return {"error": 3, "warning": 2, "info": 1}.get(self.severity, 1)

    @abstractmethod
    def check(self, text: str) -> list[WritingIssue]:
        """对文本执行检查，返回发现的写作问题列表"""
        ...

    def to_dict(self) -> dict[str, str]:
        """返回规则的元数据字典"""
        return {
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
        }


# ══════════════════════════════════════════════════════════════
# 注册中心（单例）
# ══════════════════════════════════════════════════════════════


class RuleRegistry:
    """写作规则注册中心（单例模式）

    管理所有 WritingRule 的注册、注销、查询和批量执行。
    """

    _instance: RuleRegistry | None = None
    _rules: dict[str, WritingRule] = field(default_factory=dict)

    def __new__(cls) -> RuleRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._rules = {}
        return cls._instance

    def register(self, rule: WritingRule) -> None:
        """注册一条规则"""
        if not isinstance(rule, WritingRule):
            raise TypeError(f"只能注册 WritingRule 子类实例，收到 {type(rule).__name__}")
        if rule.name in self._rules:
            raise ValueError(f"规则 '{rule.name}' 已注册")
        self._rules[rule.name] = rule

    def unregister(self, name: str) -> None:
        """注销一条规则"""
        if name not in self._rules:
            raise KeyError(f"规则 '{name}' 未注册")
        del self._rules[name]

    def get(self, name: str) -> WritingRule | None:
        """按名称获取规则实例"""
        return self._rules.get(name)

    def list(self) -> list[dict[str, str]]:
        """列出所有已注册规则的元数据"""
        return [rule.to_dict() for rule in self._rules.values()]

    def check_all(
        self,
        text: str,
        rule_names: list[str] | None = None,
    ) -> list[WritingIssue]:
        """对所有（或指定）规则执行检查。

        Args:
            text: 要检查的文本
            rule_names: 要启用的规则名称列表，None 表示全部

        Returns:
            按行号排序的 WritingIssue 列表
        """
        if not text or not text.strip():
            return []

        if rule_names is None:
            targets = list(self._rules.values())
        else:
            targets = [
                self._rules[name] for name in rule_names if name in self._rules
            ]

        issues: list[WritingIssue] = []
        for rule in targets:
            issues.extend(rule.check(text))

        # 按 line -> severity_level 降序（严重问题在前）排序
        issues.sort(key=lambda i: (i.line, -{"error": 3, "warning": 2, "info": 1}.get(i.severity, 1)))
        return issues


# ── 快捷引用 ──

registry = RuleRegistry()


# ══════════════════════════════════════════════════════════════
# 自动发现工具
# ══════════════════════════════════════════════════════════════


def discover_and_register(package_path: str | Path) -> int:
    """扫描指定目录/包，自动发现并注册所有 WritingRule 子类

    Args:
        package_path: Python 包路径（如 "core.rules" 或 Path 对象）

    Returns:
        成功注册的规则数量
    """
    if isinstance(package_path, Path):
        # 从目录路径导入
        package_str = _path_to_package(package_path)
    else:
        package_str = package_path

    count = 0
    try:
        package = importlib.import_module(package_str)
    except ImportError as e:
        raise ImportError(f"无法导入规则包 '{package_str}': {e}")

    for importer, modname, ispkg in pkgutil.iter_modules(
        package.__path__, prefix=package_str + "."
    ):
        if ispkg:
            continue
        try:
            module = importlib.import_module(modname)
        except Exception as e:
            continue  # 静默跳过无法导入的模块

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, WritingRule)
                and obj is not WritingRule
                and not getattr(obj, "__abstractmethods__", frozenset())
            ):
                try:
                    instance = obj()
                    registry.register(instance)
                    count += 1
                except (ValueError, TypeError):
                    continue  # 已注册或类型不匹配，跳过

    return count


def _path_to_package(path: Path) -> str:
    """将路径转为点分隔的包名"""
    # 找到包含 __init__.py 的最近父目录作为包根
    resolved = path.resolve()
    parts = []
    for parent in resolved.parents:
        if (parent / "__init__.py").exists():
            break
    # 从包根开始计算子模块路径
    rel = resolved.relative_to(parent)
    return ".".join([parent.name] + list(rel.parts))
