"""
统一工具路由 — 参照 MCP 协议实现

三个端点（路径前缀 /api/v1/tools）：
  GET    /api/v1/tools              — 列出所有工具（name+description+inputSchema）
  POST   /api/v1/tools/{name}/call  — 调用指定工具（args 参数）
  GET    /api/v1/tools/{name}       — 获取单个工具详情

与 routers/tools.py 共存，后者保持原有 subprocess 白名单路由不变。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from core.tools import get_registry
from core.tool_definitions import register_all_tools

router = APIRouter(prefix="/tools", tags=["tools-mcp"])


# ─── 启动时注册工具 ───

try:
    register_all_tools()
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"工具注册失败（main 启动后会重试）: {e}")


# ─── Pydantic 模型 ───


class ToolCallRequest(BaseModel):
    args: dict = Field(default_factory=dict, description="工具参数（JSON 对象）")


class ToolSchema(BaseModel):
    name: str
    description: str
    inputSchema: dict


class ToolListResponse(BaseModel):
    tools: list[ToolSchema]
    total: int


class ToolCallResponse(BaseModel):
    content: list[dict]
    isError: bool = False
    meta: dict | None = None


# ─── 路由 ───


@router.get("", response_model=ToolListResponse)
def list_tools():
    """列出所有已注册工具（name + description + inputSchema）"""
    registry = get_registry()
    tools = [ToolSchema(**t.to_dict()) for t in registry.list_all()]
    return ToolListResponse(tools=tools, total=len(tools))


@router.get("/{name}", response_model=ToolSchema)
def get_tool(name: str):
    """获取单个工具的完整信息"""
    registry = get_registry()
    tool = registry.get(name)
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TOOL_NOT_FOUND",
                "message": f"工具 '{name}' 不存在",
                "suggestion": f"可用工具: {[t.name for t in registry.list_all()]}",
            },
        )
    return ToolSchema(**tool.to_dict())


@router.post("/{name}/call", response_model=ToolCallResponse)
def call_tool(name: str, body: ToolCallRequest):
    """调用指定工具并返回结果"""
    registry = get_registry()
    result = registry.call(name, body.args)

    # 错误提取
    is_error = result.get("isError", False)
    content = result.get("content", [])
    meta = result.get("meta")

    if is_error:
        error_text = content[0]["text"] if content else "未知错误"
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TOOL_EXECUTION_ERROR",
                "message": error_text,
                "tool": name,
            },
        )

    return ToolCallResponse(content=content, isError=False, meta=meta)
