"""
工具注册中心 — 参照 MCP 协议实现

每个功能注册为一个标准化的 Tool，统一通过 /api/v1/tools/{name}/call 调用。

Tool 结构（对齐 MCP normalizeTool）：
  - name: str            — 工具标识，唯一
  - description: str     — 描述文本
  - inputSchema: dict    — JSON Schema，{type:"object", properties:{...}}
  - handler: callable    — 处理函数，接收 args(dict) 返回 dict

返回格式（对齐 MCP normalizeMcpToolResult）：
  { "content": [{"type": "text", "text": "..."}] }
  异常时返回：
  { "isError": true, "content": [{"type": "text", "text": "..."}] }
"""

from __future__ import annotations
import json
from typing import Any, Callable


# ─── Tool 类 ───


class Tool:
    """一个标准化的工具定义，对齐 MCP Tool 结构"""

    def __init__(
        self,
        name: str,
        description: str,
        inputSchema: dict | None = None,
        handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        context_hint: str | None = None,
    ):
        if not name or not isinstance(name, str):
            raise ValueError("Tool name must be a non-empty string")
        self.name = name
        self.description = description or ""
        self.inputSchema = (
            inputSchema
            if inputSchema and isinstance(inputSchema, dict)
            else {"type": "object", "properties": {}}
        )
        self.handler = handler
        self.context_hint = context_hint or ""

    def to_dict(self) -> dict:
        """序列化为 MCP 兼容格式"""
        d = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema,
        }
        if self.context_hint:
            d["context_hint"] = self.context_hint
        return d

    def execute(self, args: dict[str, Any] | None = None) -> dict:
        """执行工具，返回 MCP 兼容结果"""
        if self.handler is None:
            return _error_result(f"Tool '{self.name}' has no handler registered")
        try:
            result = self.handler(args or {})
            return _normalize_result(result)
        except Exception as e:
            return _error_result(f"Tool '{self.name}' failed: {type(e).__name__}: {e}")


# ─── ToolRegistry 单例 ───


class ToolRegistry:
    """工具注册中心单例 — register / get / list_all / call"""

    _instance: ToolRegistry | None = None

    def __new__(cls) -> ToolRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: dict[str, Tool] = {}
        return cls._instance

    def register(self, tool: Tool) -> None:
        """注册一个工具"""
        if not isinstance(tool, Tool):
            raise TypeError("Only Tool instances can be registered")
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名称获取工具"""
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """列出所有已注册的工具"""
        return list(self._tools.values())

    def call(self, name: str, args: dict[str, Any] | None = None) -> dict:
        """调用指定工具，返回 MCP 兼容结果"""
        tool = self.get(name)
        if tool is None:
            return _error_result(f"Tool '{name}' not found")
        return tool.execute(args)

    def clear(self) -> None:
        """清空所有注册（仅测试用）"""
        self._tools.clear()


# ─── 结果规范化 ───


def _normalize_result(value: Any) -> dict:
    """对齐 MCP normalizeMcpToolResult"""
    if isinstance(value, dict) and "content" in value:
        # 已经是 MCP 格式
        if isinstance(value["content"], list):
            return value
        return {"content": [{"type": "text", "text": str(value["content"])}]}
    if isinstance(value, str):
        return {"content": [{"type": "text", "text": value}]}
    if value is None:
        return {"content": [{"type": "text", "text": ""}]}
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, default=str)}]}


def _error_result(text: str) -> dict:
    """对齐 MCP mcpToolError"""
    return {
        "isError": True,
        "content": [{"type": "text", "text": text}],
    }


# ─── 便捷函数 ───


def get_registry() -> ToolRegistry:
    """获取全局 ToolRegistry 单例"""
    return ToolRegistry()
